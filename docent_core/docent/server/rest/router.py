import hashlib
import itertools
import json
import os
import tempfile
import time
import zipfile
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Literal

import anyio
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, model_validator
from pydantic_core import to_jsonable_python
from sqlalchemy import or_, select
from sqlalchemy.inspection import inspect as sqla_inspect

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import AgentRun, FilterableField
from docent.loaders import load_inspect
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server._auth.session import (
    COOKIE_KEY,
    create_user_session,
    invalidate_user_session,
)
from docent_core._server.util import sse_stream
from docent_core.docent.ai_tools.assistant.summarizer import (
    HighLevelAction,
    LowLevelAction,
    ObservationType,
    group_actions_into_high_level_steps,
    interesting_agent_observations,
    summarize_agent_actions,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.filters import (
    ComplexFilter,
)
from docent_core.docent.db.schemas.auth_models import (
    Permission,
    ResourceType,
    SubjectType,
    User,
)
from docent_core.docent.db.schemas.collab_models import CollectionCollaborator
from docent_core.docent.db.schemas.tables import (
    JobStatus,
    SQLAAccessControlEntry,
    SQLAJob,
)
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.database import (
    get_mono_svc,
    require_collection_exists,
)
from docent_core.docent.server.dependencies.permissions import (
    require_collection_permission,
    require_view_permission,
)
from docent_core.docent.server.dependencies.user import (
    get_authenticated_user,
    get_default_view_ctx,
    get_user_anonymous_ok,
)
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)

public_router = APIRouter()
# FIXME(mengk): we should move all API endpoints to another router that explicitly requires API key auth
#   This router creates an anonymous user for each session, which is an anti-pattern for API endpoints.
user_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])

####################
# Public endpoints #
####################


@public_router.get("/ping")
async def ping():
    return {"status": "ok", "message": "pong"}


class UserCreateRequest(BaseModel):
    """Request model for creating a new user."""

    email: str
    password: str

    class Config:
        extra = "forbid"


@public_router.post("/signup")
async def signup(
    request: UserCreateRequest,
    response: Response,
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """
    User signup endpoint. Creates a new user with the provided email.
    Fails if a user with that email already exists.

    Args:
        request: UserCreateRequest containing email
        response: FastAPI Response object to set cookies
        db: Database service dependency

    Returns:
        UserResponse with user_id and email

    Raises:
        HTTPException: 409 if a user with this email already exists
    """
    # Check if user already exists
    existing_user = await mono_svc.get_user_by_email(request.email)
    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="A user with this email address already exists. Please use the login page.",
        )

    user = await mono_svc.create_user(request.email, request.password)

    # Create a session for the new user
    session_id = await create_user_session(user.id, response, mono_svc)

    # Need to return session id in body so that Next.js app can set a cookie for its own domain
    return {"user": user, "session_id": session_id}


class LoginRequest(BaseModel):
    email: str
    password: str


@public_router.post("/login")
async def login(
    request: LoginRequest, response: Response, mono_svc: MonoService = Depends(get_mono_svc)
):
    """
    User login endpoint. Authenticates a user and creates a session.

    Args:
        request: LoginRequest containing email and password
        response: FastAPI Response object to set cookies
        db: Database service dependency

    Returns:
        UserResponse with user_id and email
    """
    user = await mono_svc.verify_user_password(request.email, request.password)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Create a new session
    session_id = await create_user_session(user.id, response, mono_svc)

    # Need to return session id in body so that Next.js app can set a cookie for its own domain
    return {"user": user, "session_id": session_id}


@public_router.post("/anonymous_session")
async def create_anonymous_session(
    response: Response, mono_svc: MonoService = Depends(get_mono_svc)
):
    """
    Create anonymous user endpoint. Creates a temporary anonymous user and session.

    Args:
        response: FastAPI Response object to set cookies
        db: Database service dependency

    Returns:
        User object with anonymous properties
    """
    # Create and persist anonymous user
    anonymous_user = await mono_svc.create_anonymous_user()

    # Create a session for the anonymous user
    session_id = await create_user_session(anonymous_user.id, response, mono_svc)

    # Need to return session id in body so that Next.js app can set a cookie for its own domain
    return {"user": anonymous_user, "session_id": session_id}


###########################
# Authenticated endpoints #
###########################


@user_router.get("/me")
async def get_current_user(request: Request, mono_svc: MonoService = Depends(get_mono_svc)):
    """
    Get current user endpoint. Retrieves user information from session cookie.

    Args:
        request: FastAPI Request object to access cookies
        db: Database service dependency

    Returns:
        UserResponse with user_id, email, and organization_ids

    Raises:
        HTTPException: 401 if session is invalid or expired
    """
    # Get session ID from cookie
    session_id = request.cookies.get(COOKIE_KEY)
    if not session_id:
        raise HTTPException(status_code=401, detail="No session found")

    # Get user by session ID
    user = await mono_svc.get_user_by_session_id(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return user


@user_router.post("/logout")
async def logout(
    request: Request, response: Response, mono_svc: MonoService = Depends(get_mono_svc)
):
    """
    User logout endpoint. Invalidates the current session.

    Args:
        request: FastAPI Request object to access cookies
        response: FastAPI Response object to clear cookies
        mono_svc: MonoService instance for database operations

    Returns:
        Success message
    """
    # Get session ID from cookie
    session_id = request.cookies.get(COOKIE_KEY)
    if session_id:
        # Invalidate the session using the auth helper
        await invalidate_user_session(session_id, response, mono_svc)

    return {"message": "Logged out successfully"}


##############
# Raw access #
##############


# class RawQueryRequest(BaseModel):
#     query: str


# # @user_router.post("/raw_query")
# # async def raw_query(request: RawQueryRequest, db: DBService = Depends(get_db)):
# #     return await mono_svc.run_raw_query(request.query)


#############
# Collection #
#############


@user_router.get("/collections")
async def get_collections(
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    sqla_collections = await mono_svc.get_collections(user)  # Filter to only the user's collections
    return [
        # Get all columns from the SQLAlchemy object
        {c.key: getattr(obj, c.key) for c in sqla_inspect(obj).mapper.column_attrs}
        for obj in sqla_collections
        if await mono_svc.has_permission(
            user,
            resource_type=ResourceType.COLLECTION,
            resource_id=obj.id,
            permission=Permission.READ,
        )
    ]


@user_router.get("/{collection_id}/collection")
async def get_collection_name(
    collection_id: str = Depends(require_collection_exists),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    collection = await mono_svc.get_collection(collection_id)
    return {"name": collection.name if collection else None}


class CreateCollectionRequest(BaseModel):
    collection_id: str | None = None
    name: str | None = None
    description: str | None = None


@user_router.post("/create")
async def create_collection(
    request: CreateCollectionRequest = CreateCollectionRequest(),
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    collection_id = await mono_svc.create_collection(
        user=user,
        collection_id=request.collection_id,
        name=request.name,
        description=request.description,
    )

    # Track with PostHog
    analytics.track_event(
        "collection_created",
        properties={
            "collection_id": collection_id,
            "name": request.name,
            "description": request.description,
        },
    )

    return {"collection_id": collection_id}


class UpdateCollectionRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@user_router.put("/{collection_id}/collection")
async def update_collection(
    collection_id: str,
    request: UpdateCollectionRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    await mono_svc.update_collection(
        collection_id, name=request.name, description=request.description
    )


@user_router.delete("/{collection_id}/collection")
async def delete_collection(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.ADMIN)),
):
    await mono_svc.delete_collection(collection_id)


##############
# Agent runs #
##############


def validate_inspect_filename(filename: str | None) -> str:
    if filename is None:
        raise HTTPException(status_code=400, detail="File must have a filename")
    if filename.endswith(".eval"):
        return "eval"
    elif filename.endswith(".json"):
        return "json"
    else:
        raise HTTPException(status_code=400, detail="File must be an .eval or .json file")


@user_router.post("/{collection_id}/preview_import_runs_from_file")
async def preview_import_runs_from_file(
    collection_id: str,
    file: UploadFile = File(...),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> dict[str, Any]:
    """
    Preview what would be imported from an Inspect log file without modifying the database.

    Args:
        collection_id: Collection ID (for permission checking)
        file: Uploaded file containing Inspect evaluation log
        db: Database service dependency
        ctx: View context dependency

    Returns:
        dict: Preview of what would be imported

    Raises:
        HTTPException: If file processing fails
    """
    format = validate_inspect_filename(file.filename)

    count_runs = 0
    previews: list[AgentRun] = []

    # Gather statistics about what would be imported
    scores_keys: set[str] = set()
    models: set[str] = set()
    task_ids: set[str] = set()

    try:
        file_info, runs = load_inspect.runs_from_file(file.file, format)
        for run in runs:
            model = getattr(run.metadata, "model", None)
            if model is not None:
                models.add(str(model))

            task_id = getattr(run.metadata, "task_id", None)
            if task_id is not None:
                task_ids.add(str(task_id))

            if "scores" in run.metadata:
                scores_keys.update(run.metadata["scores"].keys())

            count_runs += 1

            if len(previews) < 10:
                previews.append(run)

        file_info = {
            "filename": file.filename,
            "task": file_info.get("task"),
            "model": file_info.get("model"),
            "total_samples": count_runs,
        }
    except zipfile.BadZipfile:
        raise HTTPException(status_code=400, detail=f"Unable to read {file.filename} as a zip file")

    return {
        "status": "preview",
        "would_import": {
            "num_agent_runs": count_runs,
            "models": sorted(list(models)),
            "task_ids": sorted(list(task_ids)),
            "score_types": sorted(list(scores_keys)),
        },
        "file_info": file_info,
        "sample_preview": [
            {
                "metadata": to_jsonable_python(run.metadata),
                "num_messages": sum(len(transcript.messages) for transcript in run.transcripts),
            }
            for run in previews
        ],
    }


@user_router.post("/{collection_id}/import_runs_from_file")
async def import_runs_from_file(
    collection_id: str,
    file: UploadFile = File(...),
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """
    Import agent runs from an Inspect AI log file and stream progress via SSE.

    The response is a text/event-stream emitting JSON payloads with fields:
      { "phase": "progress" | "complete", "uploaded": int, "total": int, ... }
    """

    # Validate file extension
    format = validate_inspect_filename(file.filename)

    # Stage the uploaded file to a temporary path before returning StreamingResponse
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{format}") as _tmp:
        temp_path = _tmp.name
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            _tmp.write(chunk)

    # Compute counts using the staged file (request body may be closed after return)
    count_new_runs = load_inspect.get_total_samples(Path(temp_path), format)
    await mono_svc.check_space_for_runs(ctx, count_new_runs)

    # Create an in-memory stream for SSE
    send_stream, recv_stream = anyio.create_memory_object_stream[dict[str, Any]](
        max_buffer_size=100_000
    )

    async def _execute():
        t_start = time.perf_counter()

        runs_added = 0

        try:
            # Send initial event so clients can render 0 progress
            await send_stream.send(
                {
                    "phase": "progress",
                    "uploaded": 0,
                    "total": count_new_runs,
                }
            )

            # Open a fresh handle on the staged file for ingestion
            with open(temp_path, "rb") as _fh_ingest:
                file_info, runs_generator = load_inspect.runs_from_file(_fh_ingest, format)

                batches = itertools.batched(runs_generator, 100)
                async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
                    for batch in batches:
                        await mono_svc.add_agent_runs(ctx, batch)
                        runs_added += len(batch)

                        # Stream progress update
                        await send_stream.send(
                            {
                                "phase": "progress",
                                "uploaded": runs_added,
                                "total": count_new_runs,
                            }
                        )

            t_end = time.perf_counter()

            # Track with PostHog
            analytics.track_event(
                "agent_runs_ingested",
                properties={
                    "collection_id": collection_id,
                    "num_runs": runs_added,
                    "source": "file_upload",
                    "filename": file_info.get("filename"),
                    "task": file_info.get("task"),
                    "model": file_info.get("model"),
                    "time_taken_seconds": t_end - t_start,
                },
            )

            # Final completion event
            await send_stream.send(
                {
                    "phase": "complete",
                    "message": f"Successfully imported {runs_added} agent runs from {file_info.get('filename')}",
                    "uploaded": runs_added,
                    "total": count_new_runs,
                }
            )
        finally:
            await send_stream.aclose()
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    return StreamingResponse(
        sse_stream(_execute, send_stream, recv_stream), media_type="text/event-stream"
    )


@user_router.get("/{collection_id}/agent_run_metadata_fields")
async def agent_run_metadata_fields(
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
) -> dict[str, list[FilterableField]]:
    fields: list[FilterableField] = await mono_svc.get_agent_run_metadata_fields(ctx)
    fields.append({"name": "created_at", "type": "str"})

    return {"fields": fields}


@user_router.get("/{collection_id}/agent_run_sortable_fields")
async def agent_run_sortable_fields(
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
) -> dict[str, list[FilterableField]]:
    """Get sortable fields for agent runs. Currently supports metadata.x.y fields and created_at."""
    fields: list[FilterableField] = await mono_svc.get_agent_run_metadata_fields(ctx)
    # Include metadata fields for sorting (metadata.x.y format)
    fields = [field for field in fields if field["name"].startswith("metadata.")]
    # Add agent_run_id first, then created_at field as sortable fields
    fields.insert(0, {"name": "agent_run_id", "type": "str"})
    fields.append({"name": "created_at", "type": "str"})
    return {"fields": fields}


@user_router.get("/{collection_id}/field_values/{field_name}")
async def get_field_values(
    field_name: str,
    search: str | None = None,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    """Get unique values for a specific metadata field, limited to 100 items."""
    unique_values = await mono_svc.get_unique_field_values(ctx, field_name, search)
    return {"values": unique_values}


@user_router.get("/{collection_id}/agent_run")
async def get_agent_run(
    agent_run_id: str,
    apply_base_where_clause: bool = True,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    """
    Get an agent run by ID.

    Args:
        agent_run_id: The ID of the agent run to get.
        apply_base_where_clause: Whether to apply the base where clause to the query.

    Returns:
        The agent run.
    """

    return await mono_svc.get_agent_run(ctx, agent_run_id, apply_base_where_clause)


@user_router.get("/{collection_id}/agent_run_with_canonical_tree")
async def get_agent_run_with_canonical_tree(
    agent_run_id: str,
    apply_base_where_clause: bool = True,
    full_tree: bool = False,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    agent_run = await mono_svc.get_agent_run(ctx, agent_run_id, apply_base_where_clause)
    if not agent_run:
        raise HTTPException(status_code=404, detail=f"Agent run {agent_run_id} not found")
    else:
        return agent_run, {
            "tree": agent_run.get_canonical_tree(full_tree=full_tree),
            "transcript_ids_ordered": agent_run.get_transcript_ids_ordered(full_tree=full_tree),
        }


@user_router.get("/{collection_id}/agent_run_ids")
async def get_agent_run_ids(
    sort_field: str | None = None,
    sort_direction: Literal["asc", "desc"] = "asc",
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
) -> list[str]:
    return await mono_svc.get_agent_run_ids(
        ctx, sort_field=sort_field, sort_direction=sort_direction
    )


class AgentRunMetadataRequest(BaseModel):
    agent_run_ids: list[str]


@user_router.post("/{collection_id}/agent_run_metadata")
async def get_agent_run_metadata(
    request: AgentRunMetadataRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    # Query metadata directly without loading full agent runs
    data = await mono_svc.get_metadata_for_agent_runs(ctx, request.agent_run_ids)
    return {k: to_jsonable_python(v) for k, v in data.items()}


class PostAgentRunsRequest(BaseModel):
    agent_runs: list[AgentRun]


class DeleteAgentRunsRequest(BaseModel):
    agent_run_ids: list[str]


@user_router.post("/{collection_id}/agent_runs")
async def post_agent_runs(
    collection_id: str,
    request: PostAgentRunsRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        await mono_svc.check_space_for_runs(ctx, len(request.agent_runs))
        await mono_svc.add_agent_runs(ctx, request.agent_runs)

    # Track with PostHog
    analytics.track_event(
        "agent_runs_ingested",
        properties={
            "collection_id": collection_id,
            "num_runs": len(request.agent_runs),
        },
    )


@user_router.delete("/{collection_id}/agent_runs")
async def delete_agent_runs(
    collection_id: str,
    request: DeleteAgentRunsRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Delete specific agent runs from a collection."""
    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        deleted_count = await mono_svc.delete_agent_runs(collection_id, request.agent_run_ids)

    # Track with PostHog
    analytics.track_event(
        "agent_runs_deleted",
        properties={
            "collection_id": collection_id,
            "requested_runs": len(request.agent_run_ids),
            "num_runs_deleted": deleted_count,
        },
    )

    return {"deleted_count": deleted_count, "requested_count": len(request.agent_run_ids)}


########
# View #
########


@user_router.post("/{collection_id}/join")
async def join(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    if not await mono_svc.collection_exists(collection_id):
        raise HTTPException(status_code=404, detail=f"Collection with ID {collection_id} not found")

    return {"collection_id": collection_id, "view_id": ctx.view_id}


class SetIODimsRequest(BaseModel):
    inner_bin_key: str | None = None
    outer_bin_key: str | None = None


class SetIODimWithMetadataKeyRequest(BaseModel):
    metadata_key: str
    type: Literal["inner", "outer"]


class PostBaseFilterRequest(BaseModel):
    filter: ComplexFilter | None


@user_router.post("/{collection_id}/base_filter")
async def post_base_filter(
    collection_id: str,
    request: PostBaseFilterRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        if request.filter is None:
            new_ctx = await mono_svc.clear_view_base_filter(ctx)
        else:
            new_ctx = await mono_svc.set_view_base_filter(ctx, request.filter)

    # Track with PostHog
    analytics.track_event(
        "base_filter_updated",
        properties={
            "collection_id": collection_id,
            "filter": request.filter.model_dump() if request.filter else None,
            "action": "clear" if request.filter is None else "set",
        },
    )

    return new_ctx.base_filter


@user_router.get("/{collection_id}/base_filter")
async def get_base_filter(
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    return ctx.base_filter


# class GetRegexSnippetsRequest(BaseModel):
#     filter_id: str
#     agent_run_ids: list[str]


# @user_router.post("/{collection_id}/get_regex_snippets")
# async def get_regex_snippets_endpoint(
#     request: GetRegexSnippetsRequest,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.READ)),
# ) -> dict[str, list[RegexSnippet]]:
#     filter_id = request.filter_id

#     # Get filter object
#     filter = await mono_svc.get_filter(filter_id)
#     if filter is None:
#         raise ValueError(f"Filter {filter_id} is not found")

#     # Collect all patterns from the filter
#     patterns: list[str] = []
#     if filter.type == "primitive" and filter.op == "~*":
#         patterns.append(str(filter.value))
#     elif filter.type == "complex":

#         # Recursively search for all primitive filters
#         def _search(f: CollectionFilter):
#             if f.type == "primitive" and f.op == "~*":
#                 patterns.append(str(f.value))
#             elif f.type == "complex":
#                 for child in f.filters:
#                     _search(child)

#         _search(filter)

#     if not patterns:
#         return {}

#     agent_runs = await mono_svc.get_agent_runs(ctx, agent_run_ids=request.agent_run_ids)

#     return {
#         d.id: [item for p in patterns for item in get_regex_snippets(d.text, p)] for d in agent_runs
#     }


# @user_router.get("/{collection_id}/state")
# async def get_state(
#     mono_svc: MonoService = Depends(get_mono_svc),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.READ)),
# ):
#     await publish_homepage_state(mono_svc, ctx)


@user_router.get("/users/by-email/{email}")
async def get_user_by_email(email: str, mono_svc: MonoService = Depends(get_mono_svc)):
    """
    Get a user by their email address.
    Args:
        email: The email address to search for
        db: Database service dependency
    Returns:
        User object if found, None otherwise
    """
    return await mono_svc.get_user_by_email(email)


class UserPermissionsResponse(BaseModel):
    collection_permissions: dict[str, str | None]
    view_permissions: dict[str, str | None]


@user_router.get("/{collection_id}/permissions")
async def get_user_permissions(
    collection_id: str = Depends(require_collection_exists),
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    fg_permission = await mono_svc.get_permission_level(
        user=user,
        resource_type=ResourceType.COLLECTION,
        resource_id=collection_id,
    )

    view_permission = await mono_svc.get_permission_level(
        user=user,
        resource_type=ResourceType.VIEW,
        resource_id=ctx.view_id,
    )

    return UserPermissionsResponse(
        collection_permissions={collection_id: fg_permission.value if fg_permission else None},
        view_permissions={ctx.view_id: view_permission.value if view_permission else None},
    )


@user_router.get("/organizations/{org_id}/users")
async def get_org_users(org_id: str, mono_svc: MonoService = Depends(get_mono_svc)):
    return [u for u in await mono_svc.get_users() if not u.is_anonymous]


@user_router.get("/collections/{collection_id}/collaborators")
async def get_collection_collaborators(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    # You need READ permissions to see other people's permissions
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    return [
        CollectionCollaborator.from_sqla_acl(acl)
        for acl in await mono_svc.get_acl_entries(
            resource_id=collection_id,
            resource_type=ResourceType.COLLECTION,
        )
    ]


class UpsertCollaboratorRequest(BaseModel):
    subject_id: str | None = None
    subject_type: SubjectType
    collection_id: str
    permission_level: Permission

    @model_validator(mode="after")
    def validate_user_or_organization(self):
        if self.subject_type == SubjectType.USER and self.subject_id is None:
            raise ValueError("subject_id must be provided for user")
        if self.subject_type == SubjectType.ORGANIZATION and self.subject_id is None:
            raise ValueError("subject_id must be provided for organization")
        return self


@user_router.put("/collections/{collection_id}/collaborators/upsert")
async def upsert_collaborator(
    collection_id: str,
    request: UpsertCollaboratorRequest,
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.ADMIN)),
):
    collaborator = await mono_svc.set_acl_permission(
        subject_type=request.subject_type,
        subject_id=request.subject_id,
        resource_type=ResourceType.COLLECTION,
        resource_id=collection_id,
        permission=request.permission_level,
    )

    return collaborator


class RemoveCollaboratorRequest(BaseModel):
    subject_id: str
    subject_type: SubjectType
    collection_id: str


@user_router.delete("/collections/{collection_id}/collaborators/delete")
async def remove_collaborator(
    collection_id: str,
    request: RemoveCollaboratorRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_collection_permission(Permission.ADMIN)),
):
    async with mono_svc.db.session() as session:
        # Build the delete query with the provided filters
        query = select(SQLAAccessControlEntry).where(
            SQLAAccessControlEntry.collection_id == collection_id
        )

        # Handle subject filtering based on SubjectType
        if request.subject_type == SubjectType.USER:
            query = query.where(SQLAAccessControlEntry.user_id == request.subject_id)
        elif request.subject_type == SubjectType.ORGANIZATION:
            query = query.where(SQLAAccessControlEntry.organization_id == request.subject_id)
        elif request.subject_type == SubjectType.PUBLIC:
            query = query.where(SQLAAccessControlEntry.is_public)
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported subject type: {request.subject_type}"
            )

        # Execute the query
        result = await session.execute(query)
        acl_entry = result.scalar_one_or_none()

        if acl_entry is None:
            raise HTTPException(
                status_code=400, detail=f"Collaborator {request.subject_id} not found"
            )

    await mono_svc.clear_acl_permission(
        subject_type=request.subject_type,
        subject_id=request.subject_id,
        resource_type=ResourceType.COLLECTION,
        resource_id=collection_id,
    )
    return {"status": "success"}


class ShareViewRequest(BaseModel):
    subject_type: Literal["user", "organization", "public"]
    subject_id: str
    level: Literal["read"]


class ShareWithEmailRequest(BaseModel):
    email: str


# @user_router.post("/{collection_id}/share_view")
# async def share_view(
#     collection_id: str,
#     request: ShareViewRequest,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_collection_permission(Permission.READ)),
# ):
#     await mono_svc.set_acl_permission(
#         subject_type=SubjectType(request.subject_type),
#         subject_id=request.subject_id,
#         resource_type=ResourceType.VIEW,
#         resource_id=ctx.view_id,
#         permission=Permission(request.level),
#     )
#     return {"status": "success"}


@user_router.post("/{collection_id}/make_public")
async def make_collection_public(
    collection_id: str,
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.ADMIN)),
):
    """Make a collection publicly accessible to anyone with the link."""
    await mono_svc.set_acl_permission(
        subject_type=SubjectType.PUBLIC,
        subject_id=None,
        resource_type=ResourceType.COLLECTION,
        resource_id=collection_id,
        permission=Permission.READ,
    )

    return {"status": "success", "message": "Collection is now public"}


@user_router.post("/{collection_id}/share_with_email")
async def share_collection_with_email(
    collection_id: str,
    request: ShareWithEmailRequest,
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.ADMIN)),
):
    """Share a collection with a specific user by email address."""
    target_user = await mono_svc.get_user_by_email(request.email)
    if target_user is None:
        raise HTTPException(status_code=404, detail=f"User with email {request.email} not found")

    await mono_svc.set_acl_permission(
        subject_type=SubjectType.USER,
        subject_id=target_user.id,
        resource_type=ResourceType.COLLECTION,
        resource_id=collection_id,
        permission=Permission.READ,
    )

    return {"status": "success", "message": f"Collection shared with {request.email}"}


@user_router.post("/{collection_id}/has_embedding_job")
async def has_embedding_job(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    where_clause = or_(SQLAJob.status == JobStatus.PENDING, SQLAJob.status == JobStatus.RUNNING)
    count = await mono_svc.get_embedding_job_count(collection_id, where_clause)
    return count > 0


####################
# API Key endpoints #
####################


class CreateApiKeyRequest(BaseModel):
    name: str


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    disabled_at: datetime | None
    last_used_at: datetime | None
    is_active: bool


class CreateApiKeyResponse(BaseModel):
    id: str
    name: str
    api_key: str
    created_at: datetime


@user_router.get("/api-keys/test")
async def test_api_key(user: User = Depends(get_authenticated_user)):
    """
    Test endpoint to verify API key authentication.
    Returns user info if authenticated, 401 if not.
    """
    return {
        "message": "API key authentication successful",
        "user_id": user.id,
        "is_anonymous": user.is_anonymous,
    }


@user_router.post("/api-keys", response_model=CreateApiKeyResponse)
async def create_api_key(
    request: CreateApiKeyRequest,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """Create a new API key for the authenticated user."""
    api_key_id, raw_api_key = await mono_svc.create_api_key(user.id, request.name)

    api_keys = await mono_svc.get_user_api_keys(user.id)
    created_key = next(k for k in api_keys if k.id == api_key_id)

    return CreateApiKeyResponse(
        id=created_key.id,
        name=created_key.name,
        api_key=raw_api_key,
        created_at=created_key.created_at,
    )


@user_router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """List all API keys for the authenticated user."""
    api_keys = await mono_svc.get_user_api_keys(user.id)
    return [
        ApiKeyResponse(
            id=key.id,
            name=key.name,
            created_at=key.created_at,
            disabled_at=key.disabled_at,
            last_used_at=key.last_used_at,
            is_active=key.is_active,
        )
        for key in api_keys
    ]


@user_router.delete("/api-keys/{api_key_id}")
async def disable_api_key(
    api_key_id: str,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """Disable an API key."""
    success = await mono_svc.disable_api_key(api_key_id, user.id)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"message": "API key disabled successfully"}


###########################
# Model API Key endpoints #
###########################


class ModelApiKeyResponse(BaseModel):
    id: str
    provider: str
    masked_api_key: str


class UpsertModelApiKeyRequest(BaseModel):
    provider: str
    api_key: str


def _mask_api_key(key: str):
    if len(key) <= 8:
        return "••••••••"
    return key[:4] + "••••••••" + key[-4:]


@user_router.get("/model-api-keys", response_model=list[ModelApiKeyResponse])
async def list_model_api_keys(
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """List all model API keys for the authenticated user."""
    model_api_keys = await mono_svc.get_model_api_keys(user.id)
    return [
        ModelApiKeyResponse(
            id=key.id,
            provider=key.provider,
            masked_api_key=_mask_api_key(key.api_key),
        )
        for key in model_api_keys
    ]


@user_router.put("/model-api-keys", response_model=ModelApiKeyResponse)
async def upsert_model_api_key(
    request: UpsertModelApiKeyRequest,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Create or update a model API key for the authenticated user."""
    # Validate provider
    valid_providers = ["openai", "anthropic", "google"]
    if request.provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider. Must be one of: {', '.join(valid_providers)}",
        )

    model_api_key = await mono_svc.upsert_model_api_key(user.id, request.provider, request.api_key)

    # Track with PostHog
    analytics.track_event(
        "model_api_key_saved",
        properties={
            "provider": model_api_key.provider,
        },
    )

    return ModelApiKeyResponse(
        id=model_api_key.id,
        provider=model_api_key.provider,
        masked_api_key=_mask_api_key(model_api_key.api_key),
    )


@user_router.delete("/model-api-keys/{provider}")
async def delete_model_api_key(
    provider: str,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Delete a model API key for the authenticated user and provider."""
    success = await mono_svc.delete_model_api_key(user.id, provider)
    if not success:
        raise HTTPException(status_code=404, detail="Model API key not found")
    # Track with PostHog
    analytics.track_event(
        "model_api_key_deleted",
        properties={
            "provider": provider,
        },
    )
    return {"message": "Model API key deleted successfully"}


@user_router.post("/{collection_id}/fg_has_embeddings")
async def fg_has_embeddings(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    return await mono_svc.fg_has_embeddings(collection_id)


@user_router.post("/{collection_id}/compute_embeddings")
async def compute_embeddings(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    return
    await mono_svc.add_and_enqueue_embedding_job(ctx)


#######################
# Agent run summaries #
#######################


@user_router.get("/{collection_id}/actions_summary")
async def get_actions_summary(
    agent_run_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    agent_run = await mono_svc.get_agent_run(ctx, agent_run_id, apply_base_where_clause=False)
    if not agent_run:
        raise HTTPException(status_code=404, detail=f"AgentRun {agent_run_id} not found")
    # Get first transcript TODO(mengk): generalize to multi-agent setting
    if len(agent_run.transcripts) == 0:
        raise HTTPException(status_code=404, detail=f"AgentRun {agent_run_id} has no transcripts")
    transcript = agent_run.transcripts[0]

    # Result variables; hashes prevent updating with identical content multiple times
    low_level_actions: list[LowLevelAction] = []
    high_level_actions: list[HighLevelAction] = []
    agent_observations: list[ObservationType] = []
    prev_hash: str | None = None

    # AnyIO queue that we can write intermediate results to
    send_stream, recv_stream = anyio.create_memory_object_stream[dict[str, Any]](
        max_buffer_size=100_000
    )
    lock = anyio.Lock()  # Only one payload can be sent at a time

    def _get_payload():
        nonlocal low_level_actions, high_level_actions, agent_observations, agent_run_id

        payload = {
            "low_level": low_level_actions,
            "high_level": high_level_actions,
            "observations": agent_observations,
            "agent_run_id": agent_run_id,
        }
        payload_hash = hashlib.sha256(
            json.dumps(to_jsonable_python(payload), sort_keys=True).encode()
        ).hexdigest()
        return payload, payload_hash

    async def _send_payload_if_new():
        nonlocal prev_hash
        async with lock:
            payload, payload_hash = _get_payload()

            # Only send if hash is different from previous hash
            if payload_hash != prev_hash:
                await send_stream.send(payload)
                prev_hash = payload_hash

    async def _actions_callback(actions: list[LowLevelAction]):
        nonlocal low_level_actions
        low_level_actions = actions
        await _send_payload_if_new()  # TODO: does this slow things down? should be run in the background, i think

    async def _high_level_actions_callback(actions: list[HighLevelAction]):
        nonlocal high_level_actions
        high_level_actions = actions
        await _send_payload_if_new()

    async def _observations_callback(observations: list[ObservationType]):
        nonlocal agent_observations
        agent_observations = observations
        await _send_payload_if_new()

    # Run agent observations concurrently with the other tasks
    async def _execute():
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                partial(
                    interesting_agent_observations,
                    transcript,
                    streaming_callback=_observations_callback,
                    # api_keys=api_keys,
                )
            )

            # Concurrently, get the low-level actions
            low_level_actions = await summarize_agent_actions(
                transcript,
                streaming_callback=_actions_callback,
                # api_keys=api_keys
            )
            # Wait for low-level actions, then group them into high-level steps
            if low_level_actions:
                await group_actions_into_high_level_steps(
                    low_level_actions,
                    transcript,
                    streaming_callback=_high_level_actions_callback,
                    # api_keys=api_keys,
                )

        # At the very end, close the recv_stream
        await send_stream.aclose()

    return StreamingResponse(
        sse_stream(_execute, send_stream, recv_stream), media_type="text/event-stream"
    )
