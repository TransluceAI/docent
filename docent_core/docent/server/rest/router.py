import itertools
import os
import tempfile
import time
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

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
from sqlalchemy import select
from sqlalchemy.inspection import inspect as sqla_inspect

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import (
    AgentRun,
    AgentRunTree,
    FilterableField,
)
from docent.loaders import load_inspect
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server._auth.session import (
    COOKIE_KEY,
    create_user_session,
    invalidate_user_session,
)
from docent_core._server.util import sse_stream
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.filters import (
    CollectionFilter,
    ComplexFilter,
    parse_filter_dict,
)
from docent_core.docent.db.schemas.auth_models import (
    Permission,
    ResourceType,
    SubjectType,
    User,
)
from docent_core.docent.db.schemas.collab_models import CollectionCollaborator
from docent_core.docent.db.schemas.tables import (
    SQLAAccessControlEntry,
    SQLAFilter,
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


################
# Dependencies #
################


async def require_filter_in_collection(
    collection_id: str,
    filter_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
) -> None:
    """Validate that filter belongs to collection. Raises 404 if not."""
    filter_entry = await mono_svc.get_filter_entry(collection_id=collection_id, filter_id=filter_id)
    if filter_entry is None:
        raise HTTPException(
            status_code=404, detail=f"Filter {filter_id} not found in collection {collection_id}"
        )


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


class ChangePasswordRequest(BaseModel):
    """Request model for updating a user's password."""

    old_password: str
    new_password: str


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


@user_router.post("/change_password")
async def change_password(
    request: ChangePasswordRequest,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """
    Change the authenticated user's password when the current password is provided correctly.
    """
    if not user.email:
        raise HTTPException(status_code=400, detail="User email is required to change password")

    updated = await mono_svc.change_user_password(
        user.email, request.old_password, request.new_password
    )
    if not updated:
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    return {"message": "Password updated successfully"}


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


class CollectionRow(BaseModel):
    """Represents a collection of agent runs.

    A Collection is a container for organizing and managing related agent runs.

    Attributes:
        id: Unique identifier for the collection.
        name: Human-readable name for the collection.
        description: Optional description of the collection's purpose.
        created_by: User ID of the collection creator (if available).
        created_at: Timestamp when the collection was created.
        agent_run_count: Number of agent runs in the collection (if available).
        rubric_count: Number of rubrics in the collection (if available).
        label_set_count: Number of label sets in the collection (if available).
    """

    id: str
    name: str | None = None
    description: str | None = None
    created_by: str | None = None
    created_at: datetime
    agent_run_count: int | None = None
    rubric_count: int | None = None
    label_set_count: int | None = None


@user_router.get("/collections", response_model=list[CollectionRow])
async def get_collections(
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    sqla_collections = await mono_svc.get_collections(user)  # Filter to only the user's collections

    # Extract collection IDs for batch queries
    collection_ids = [obj.id for obj in sqla_collections]

    # Batch query all counts at once
    agent_run_counts = await mono_svc.batch_count_collection_agent_runs(collection_ids)
    rubric_counts = await mono_svc.batch_count_collection_rubrics(collection_ids)
    label_set_counts = await mono_svc.batch_count_collection_label_sets(collection_ids)

    # Build response with counts for each collection
    result: list[dict[str, Any]] = []
    for obj in sqla_collections:
        collection_data: dict[str, Any] = obj.dict()

        # Add counts from batch query results
        collection_data["agent_run_count"] = agent_run_counts[obj.id]
        collection_data["rubric_count"] = rubric_counts[obj.id]
        collection_data["label_set_count"] = label_set_counts[obj.id]

        result.append(collection_data)

    return result


@user_router.get("/{collection_id}/collection_details", response_model=CollectionRow | None)
async def get_collection_details(
    collection_id: str = Depends(require_collection_exists),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get full details about a collection including id, name, description, created_at, created_by, and counts."""
    collection = await mono_svc.get_collection(collection_id)
    if collection is None:
        return None

    # Get all columns from the SQLAlchemy object
    collection_data: dict[str, Any] = {
        c.key: getattr(collection, c.key) for c in sqla_inspect(collection).mapper.column_attrs
    }

    # Batch query all counts (batch functions work efficiently even with a single ID)
    agent_run_counts = await mono_svc.batch_count_collection_agent_runs([collection.id])
    rubric_counts = await mono_svc.batch_count_collection_rubrics([collection.id])
    label_set_counts = await mono_svc.batch_count_collection_label_sets([collection.id])

    # Add counts
    collection_data["agent_run_count"] = agent_run_counts[collection.id]
    collection_data["rubric_count"] = rubric_counts[collection.id]
    collection_data["label_set_count"] = label_set_counts[collection.id]

    return collection_data


@user_router.get("/{collection_id}/exists")
async def collection_exists(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
) -> bool:
    """Return true/false without raising 404 when checking collection existence."""
    return await mono_svc.collection_exists(collection_id)


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


@user_router.get("/{collection_id}/metadata_range/{field_name}")
async def get_metadata_field_range(
    field_name: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    try:
        return await mono_svc.get_metadata_field_range(ctx, field_name)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@user_router.get("/{collection_id}/agent_run_with_tree")
async def get_agent_run_with_tree(
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

    tree = AgentRunTree.from_agent_run(agent_run)
    nodes = tree.nodes if full_tree else tree.nodes_pruned

    return agent_run, {
        "nodes": {k: v.model_dump() for k, v in nodes.items()},
        "transcript_id_to_idx": tree.transcript_id_to_idx,
        "parent_map": tree.parent_map,
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


class EnqueuedJobResponse(BaseModel):
    job_id: str
    status: str
    status_url: str
    message: str


@user_router.post(
    "/{collection_id}/agent_runs", status_code=202, response_model=EnqueuedJobResponse
)
async def post_agent_runs_compressed(
    collection_id: str,
    request: Request,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """
    Enqueue agent runs for background processing.

    This endpoint:
    1. Accepts the raw request body and validates Content-Encoding
    2. Creates a job record in the database
    3. Stores the payload in a separate table (to avoid bloating job metadata)
    4. Enqueues the job for background processing
    5. Returns 202 Accepted with a job_id for tracking

    All heavy processing happens in the worker to keep the endpoint fast.
    """
    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(status_code=400, detail="Request body is empty")

    # Normalize and validate content-encoding header (case-insensitive per HTTP spec)
    content_encoding = request.headers.get("content-encoding")
    normalized_encoding = (content_encoding or "").strip().lower()

    # Validate encoding is supported
    if normalized_encoding and normalized_encoding not in ("", "identity", "gzip"):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported Content-Encoding '{content_encoding}'. Supported encodings: gzip.",
        )

    # Create job, payload, and enqueue for processing
    job_id = await mono_svc.enqueue_agent_run_ingest(
        collection_id=collection_id,
        raw_body=raw_body,
        content_encoding=normalized_encoding,
        ctx=ctx,
    )

    # Track with PostHog
    analytics.track_event(
        "agent_runs_ingestion_enqueued",
        properties={
            "collection_id": collection_id,
            "job_id": job_id,
        },
    )

    status_url = f"/rest/{collection_id}/agent_runs/jobs/{job_id}"
    return EnqueuedJobResponse(
        job_id=job_id,
        status="enqueued",
        status_url=status_url,
        message="Agent runs accepted for processing. Check status at status_url.",
    )


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    type: str
    created_at: datetime
    collection_id: str | None


@user_router.get("/{collection_id}/agent_runs/jobs/{job_id}", response_model=JobStatusResponse)
async def get_agent_run_job_status(
    collection_id: str,
    job_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
):
    """
    Get the status of an agent run ingestion job.

    Returns job status and metadata. Status can be:
    - pending: Job is queued but not yet started
    - running: Job is currently being processed by a worker
    - completed: Job finished successfully
    - canceled: Job failed or was canceled
    """
    job = await mono_svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Verify the job belongs to this collection
    job_collection_id = job.job_json.get("collection_id") if job.job_json else None
    if job_collection_id != collection_id:
        raise HTTPException(
            status_code=404, detail=f"Job {job_id} not found in collection {collection_id}"
        )

    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        type=job.type,
        created_at=job.created_at,
        collection_id=job_collection_id,
    )


class BatchJobStatusRequest(BaseModel):
    job_ids: list[str]

    @model_validator(mode="after")
    def validate_job_ids_limit(self):
        if len(self.job_ids) > 100:
            raise ValueError("Cannot request more than 100 job IDs at once")
        return self


class BatchJobStatusResponse(BaseModel):
    jobs: list[JobStatusResponse]


@user_router.post(
    "/{collection_id}/agent_runs/jobs/batch_status", response_model=BatchJobStatusResponse
)
async def get_agent_run_job_statuses(
    collection_id: str,
    request: BatchJobStatusRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """
    Get the status of multiple agent run ingestion jobs in a single request.

    Args:
        collection_id: The collection ID to filter jobs by.
        request: BatchJobStatusRequest containing up to 100 job_ids.

    Returns:
        Dict with "jobs" list containing status for each found job that belongs to
        this collection. Jobs not found or belonging to other collections are omitted.
    """
    jobs = await mono_svc.get_jobs(request.job_ids)

    # Filter to only jobs belonging to this collection and build response
    results: list[JobStatusResponse] = []
    for job in jobs:
        job_collection_id = job.job_json.get("collection_id") if job.job_json else None
        if job_collection_id == collection_id:
            results.append(
                JobStatusResponse(
                    job_id=job.id,
                    status=job.status.value,
                    type=job.type,
                    created_at=job.created_at,
                    collection_id=job_collection_id,
                )
            )

    return BatchJobStatusResponse(jobs=results)


@user_router.get("/{collection_id}/agent_run_ingest_jobs")
async def get_agent_run_ingest_jobs(
    collection_id: str,
    limit: int = 100,
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """
    Get agent run ingestion jobs for a collection.

    Returns a list of agent run ingest jobs with their status and metadata,
    ordered by creation time (newest first).

    Args:
        collection_id: The collection ID to filter jobs by.
        limit: Maximum number of jobs to return (default 100, max 1000).

    Returns:
        List of jobs with status, type, and timestamps.
    """
    # Cap limit at 1000 to prevent excessive queries
    limit = min(limit, 1000)

    jobs = await mono_svc.get_agent_run_ingest_jobs(collection_id, limit)

    return {
        "jobs": [
            {
                "job_id": job.id,
                "status": job.status.value,
                "type": job.type,
                "created_at": job.created_at.isoformat(),
                "collection_id": collection_id,
            }
            for job in jobs
        ],
        "count": len(jobs),
    }


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


class PostBaseFilterRequest(BaseModel):
    filter: ComplexFilter | None


class CreateFilterRequest(BaseModel):
    filter: CollectionFilter
    name: str | None = None
    description: str | None = None


class StoredFilterResponse(BaseModel):
    id: str
    collection_id: str
    name: str | None
    description: str | None
    filter: CollectionFilter
    created_at: datetime
    created_by: str


class FilterListItemResponse(BaseModel):
    id: str
    name: str | None
    description: str | None
    created_at: datetime
    created_by: str


def _serialize_stored_filter(filter_row: SQLAFilter) -> StoredFilterResponse:
    filter_dict = cast(dict[str, Any], deepcopy(filter_row.filter_dict or {}))
    filter_model = parse_filter_dict(filter_dict)
    return StoredFilterResponse(
        id=filter_row.id,
        collection_id=filter_row.collection_id,
        name=filter_row.name,
        description=filter_row.description,
        filter=filter_model,
        created_at=filter_row.created_at,
        created_by=filter_row.created_by,
    )


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


@user_router.get(
    "/{collection_id}/filters",
    response_model=list[FilterListItemResponse],
)
async def list_filters(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[FilterListItemResponse]:
    filters = await mono_svc.list_filter_entries(collection_id=collection_id)
    return [
        FilterListItemResponse(
            id=filter_row.id,
            name=filter_row.name,
            description=filter_row.description,
            created_at=filter_row.created_at,
            created_by=filter_row.created_by,
        )
        for filter_row in filters
    ]


@user_router.post("/{collection_id}/filters", response_model=StoredFilterResponse)
async def create_filter(
    collection_id: str,
    request: CreateFilterRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    user: User = Depends(get_authenticated_user),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    stored_filter = await mono_svc.create_filter_entry(
        collection_id=collection_id,
        filter_payload=request.filter,
        user=user,
        name=request.name,
        description=request.description,
    )
    return _serialize_stored_filter(stored_filter)


@user_router.get(
    "/{collection_id}/filters/{filter_id}",
    response_model=StoredFilterResponse,
)
async def get_filter(
    collection_id: str,
    filter_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    _filter: None = Depends(require_filter_in_collection),
):
    stored_filter = await mono_svc.get_filter_entry(
        collection_id=collection_id, filter_id=filter_id
    )
    if stored_filter is None:
        raise HTTPException(status_code=404, detail=f"Filter {filter_id} not found")
    return _serialize_stored_filter(stored_filter)


@user_router.delete("/{collection_id}/filters/{filter_id}")
async def delete_filter(
    collection_id: str,
    filter_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _filter: None = Depends(require_filter_in_collection),
):
    deleted = await mono_svc.delete_filter_entry(collection_id=collection_id, filter_id=filter_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Filter {filter_id} not found")
    return {"status": "deleted", "filter_id": filter_id}


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


class PermissionCheckResponse(BaseModel):
    permission: Permission
    has_permission: bool


class CollectionsPermissionsRequest(BaseModel):
    collection_ids: list[str]


class CollectionsPermissionsResponse(BaseModel):
    collection_permissions: dict[str, str | None]


@user_router.post("/collections/permissions", response_model=CollectionsPermissionsResponse)
async def get_collections_permissions(
    request: CollectionsPermissionsRequest,
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    perms = await mono_svc.get_permissions_for_collections(user, request.collection_ids)
    return CollectionsPermissionsResponse(
        collection_permissions={k: (v.value if v else None) for k, v in perms.items()}
    )


@user_router.get("/{collection_id}/has_permission")
async def check_collection_permission(
    permission: Permission = Permission.WRITE,
    collection_id: str = Depends(require_collection_exists),
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
) -> PermissionCheckResponse:
    allowed = await mono_svc.has_permission(
        user=user,
        resource_type=ResourceType.COLLECTION,
        resource_id=collection_id,
        permission=permission,
    )
    return PermissionCheckResponse(permission=permission, has_permission=allowed)


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


@user_router.post("/{collection_id}/compute_embeddings")
async def compute_embeddings(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    pass
