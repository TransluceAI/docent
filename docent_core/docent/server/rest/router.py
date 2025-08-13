import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from functools import partial
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

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
from inspect_ai.log import read_eval_log_async
from pydantic import BaseModel
from pydantic_core import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.inspection import inspect as sqla_inspect

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import AgentRun, AgentRunWithoutMetadataValidator
from docent.data_models.citation import (
    Citation,
    parse_citations_single_run,
)
from docent.data_models.transcript import fake_model_dump
from docent.loaders.load_inspect import load_inspect_log
from docent_core._ai_tools.assistant.chat import make_single_tasst_system_prompt
from docent_core._ai_tools.assistant.summarizer import (
    HighLevelAction,
    LowLevelAction,
    ObservationType,
    group_actions_into_high_level_steps,
    interesting_agent_observations,
    summarize_agent_actions,
)
from docent_core._ai_tools.search import SearchResultWithCitations
from docent_core._db_service.schemas.auth_models import (
    Permission,
    ResourceType,
    SubjectType,
    User,
)
from docent_core._db_service.schemas.collab_models import CollectionCollaborator
from docent_core._db_service.schemas.tables import (
    JobStatus,
    SQLAAccessControlEntry,
    SQLAChatSession,
    SQLAJob,
)
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server._auth.session import (
    COOKIE_KEY,
    create_user_session,
    invalidate_user_session,
)
from docent_core._server.util import sse_event_stream
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.filters import (
    ComplexFilter,
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


async def _process_inspect_file(file: UploadFile) -> tuple[list[AgentRun], dict[str, Any]]:
    """
    Helper function to process an Inspect log file and extract agent runs.

    Args:
        file: Uploaded file containing Inspect evaluation log

    Returns:
        tuple: (agent_runs, file_info) where file_info contains metadata about the file

    Raises:
        HTTPException: If file processing fails
    """
    # Validate file extension
    if not file.filename or not (
        file.filename.endswith(".eval") or file.filename.endswith(".json")
    ):
        raise HTTPException(status_code=400, detail="File must be an .eval or .json file")

    temp_file_path = None
    try:
        # Read file content
        file_content = await file.read()

        # Preserve the original file extension for the temporary file
        file_suffix = ".json" if file.filename.endswith(".json") else ".eval"

        # Create temporary file to write the content
        with tempfile.NamedTemporaryFile(mode="wb", suffix=file_suffix, delete=False) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name

        # Load the inspect log using the async interface to avoid uvloop conflicts
        eval_log = await read_eval_log_async(temp_file_path)

        # Convert to agent runs using the existing load_inspect_log function
        agent_runs = load_inspect_log(eval_log)

        # Extract file metadata
        file_info = {
            "filename": file.filename,
            "task": eval_log.eval.task if eval_log.eval else None,
            "model": eval_log.eval.model if eval_log.eval else None,
            "total_samples": len(eval_log.samples) if eval_log.samples else 0,
        }

        return agent_runs, file_info

    except ValidationError as e:
        errors = e.errors()
        if not errors:
            message = "Unknown error"
        else:
            message = ""
            for error in errors:
                message += f"{error['msg']} at {error['loc']}\n"
                print(message)
        raise HTTPException(status_code=400, detail=message)
    except Exception as e:
        logger.error(f"Failed to process file {file.filename}: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Failed to process file: {str(e)}")
    finally:
        # Clean up temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


@user_router.post("/{collection_id}/preview_import_runs_from_file")
async def preview_import_runs_from_file(
    collection_id: str,
    file: UploadFile = File(...),
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
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
    agent_runs, file_info = await _process_inspect_file(file)

    # Gather statistics about what would be imported
    scores_keys: set[str] = set()
    models: set[str] = set()
    task_ids: set[str] = set()

    for run in agent_runs:
        # Use getattr with defaults to safely access attributes
        model = getattr(run.metadata, "model", None)
        if model is not None:
            models.add(str(model))

        task_id = getattr(run.metadata, "task_id", None)
        if task_id is not None:
            task_ids.add(str(task_id))

        if "scores" in run.metadata:
            scores_keys.update(run.metadata["scores"].keys())

    return {
        "status": "preview",
        "would_import": {
            "num_agent_runs": len(agent_runs),
            "models": sorted(list(models)),
            "task_ids": sorted(list(task_ids)),
            "score_types": sorted(list(scores_keys)),
        },
        "file_info": file_info,
        "sample_preview": [
            {
                "metadata": fake_model_dump(run.metadata),
                "num_messages": sum(
                    len(transcript.messages) for transcript in run.transcripts.values()
                ),
            }
            for run in agent_runs[:10]  # Show first 10 as preview
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
    Import agent runs from an Inspect AI log file.

    Args:
        collection_id: Collection ID to import runs into
        file: Uploaded file containing Inspect AI evaluation log
        db: Database service dependency
        ctx: View context dependency

    Returns:
        dict: Summary of the import operation

    Raises:
        HTTPException: If file processing or import fails
    """
    agent_runs, file_info = await _process_inspect_file(file)

    if not agent_runs:
        return {
            "status": "success",
            "message": "No agent runs found in the provided file",
            "num_runs_imported": 0,
            **file_info,
        }

    # Add agent runs to the database (similar to post_agent_runs)
    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        await mono_svc.add_agent_runs(ctx, agent_runs)

    # Track with PostHog
    analytics.track_event(
        "agent_runs_ingested",
        properties={
            "collection_id": collection_id,
            "num_runs": len(agent_runs),
            "source": "file_upload",
            "filename": file_info.get("filename"),
            "task": file_info.get("task"),
            "model": file_info.get("model"),
        },
    )

    return {
        "status": "success",
        "message": f"Successfully imported {len(agent_runs)} agent runs from {file_info['filename']}",
        "num_runs_imported": len(agent_runs),
        **file_info,
    }


@user_router.get("/{collection_id}/agent_run_metadata_fields")
async def agent_run_metadata_fields(
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    # Get any agent_run to get the metadata fields
    any_data = await mono_svc.get_any_agent_run(ctx)
    if any_data is not None:
        fields = any_data.get_filterable_fields()
    else:
        fields = []

    return {"fields": fields}


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


@user_router.get("/{collection_id}/agent_run_ids")
async def get_agent_run_ids(
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    return await mono_svc.get_agent_run_ids(ctx)


class AgentRunMetadataRequest(BaseModel):
    agent_run_ids: list[str]


@user_router.post("/{collection_id}/agent_run_metadata")
async def get_agent_run_metadata(
    request: AgentRunMetadataRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    data = await mono_svc.get_agent_runs(ctx, agent_run_ids=request.agent_run_ids)
    return {d.id: fake_model_dump(d.metadata) for d in data}


class PostAgentRunsRequest(BaseModel):
    agent_runs: list[AgentRunWithoutMetadataValidator]


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
        await mono_svc.add_agent_runs(ctx, request.agent_runs)

    # Track with PostHog
    analytics.track_event(
        "agent_runs_ingested",
        properties={
            "collection_id": collection_id,
            "num_runs": len(request.agent_runs),
        },
    )


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


from pydantic import model_validator


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


###################################
# Computing searches and clusters #
###################################


class AttributeWithCitation(TypedDict):
    attribute: str
    citations: list[Citation]


class StreamedSearchResult(TypedDict):
    data_dict: dict[str, dict[str, list[SearchResultWithCitations]]]
    num_agent_runs_done: int
    num_agent_runs_total: int
    num_search_hits: int


class ComputeSearchRequest(BaseModel):
    search_query: str


class GetSearchResultsRequest(BaseModel):
    search_query_id: str


class ListSearchClustersRequest(BaseModel):
    search_query_id: str


class GetClusterMatchesRequest(BaseModel):
    centroid: str


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
        raise ValueError(f"AgentRun {agent_run_id} not found")
    transcript = next(
        iter(agent_run.transcripts.values())
    )  # Get first transcript TODO(mengk): generalize

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
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
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
        sse_event_stream(_execute, send_stream, recv_stream), media_type="text/event-stream"
    )


# @user_router.get("/{collection_id}/solution_summary")
# async def get_solution_summary(
#     agent_run_id: str,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.READ)),
# ):
#     agent_run = await mono_svc.get_agent_run(ctx, agent_run_id)
#     if not agent_run:
#         raise ValueError(f"Agent run {agent_run_id} not found")
#     transcript = next(
#         iter(agent_run.transcripts.values())
#     )  # Get first transcript TODO(mengk): generalize

#     # AnyIO queue that we can write intermediate results to
#     send_stream, recv_stream = anyio.create_memory_object_stream[dict[str, Any]](
#         max_buffer_size=100_000
#     )

#     async def _solution_callback(summary: str, parts: list[str]):
#         await send_stream.send(
#             {
#                 "summary": summary,
#                 "parts": parts,
#                 "agent_run_id": agent_run_id,
#             }
#         )

#     async def _execute():
#         await summarize_intended_solution(
#             transcript,
#             streaming_callback=_solution_callback,  # api_keys=api_keys
#         )
#         await recv_stream.aclose()

#     return StreamingResponse(
#         sse_event_stream(_execute, send_stream, recv_stream), media_type="text/event-stream"
#     )


############
# Chatting #
############


class CreateTASessionRequest(BaseModel):
    agent_run_id: str


class TaChatMessage(TypedDict):
    role: str
    content: str
    citations: list[Citation]


class TASession(BaseModel):
    id: str
    messages: list[TaChatMessage]
    agent_run_ids: list[str]
    user_id: str


@user_router.get("/ta_session_messages/{session_id}")
async def get_ta_session_messages(
    session_id: str,
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """
    Get the message history for an existing TA session.
    """
    async with mono_svc.db.session() as session:
        result = await session.execute(
            select(SQLAChatSession).where(SQLAChatSession.id == session_id)
        )
        chat_session = result.scalar_one_or_none()

    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Ensure the current user owns this session
    if chat_session.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: You don't have permission to access this session",
        )

    # Exclude system messages from the response
    messages = [msg for msg in chat_session.messages if msg["role"] != "system"]

    return {
        "messages": messages,
        "session_id": session_id,
        "agent_run_ids": chat_session.agent_run_ids,
    }


@user_router.post("/{collection_id}/ta_session")
async def create_ta_session(
    request: CreateTASessionRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    agent_run_id = request.agent_run_id

    agent_run = await mono_svc.get_agent_run(ctx, agent_run_id)
    if not agent_run:
        raise ValueError("Agent run not found")

    # Create system prompt with all matching transcripts
    system_prompt = make_single_tasst_system_prompt(agent_run)

    # Generate session ID and store session in database
    session_id = str(uuid4())
    chat_session = SQLAChatSession(
        id=session_id,
        user_id=user.id,
        messages=[{"role": "system", "content": system_prompt, "citations": []}],
        agent_run_ids=[agent_run.id],
    )

    async with mono_svc.db.session() as session:
        session.add(chat_session)
        await session.commit()

    return {
        "session_id": session_id,
        "num_transcripts": 1,
    }


@user_router.get("/{collection_id}/ta_message")
async def get_ta_message(
    session_id: str,
    message: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    # Get session from database
    async with mono_svc.db.session() as session:
        result = await session.execute(
            select(SQLAChatSession).where(SQLAChatSession.id == session_id)
        )
        chat_session = result.scalar_one_or_none()

    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Ensure the current user owns this session
    if chat_session.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: You don't have permission to access this session",
        )

    # Add user message to session
    prompt_msgs = chat_session.messages + [{"role": "user", "content": message, "citations": []}]
    continuation_text = ""

    # AnyIO queue that we can write intermediate results to
    send_stream, recv_stream = anyio.create_memory_object_stream[dict[str, Any]](
        max_buffer_size=100_000
    )

    def _get_complete_message_list(include_system: bool = True):
        nonlocal continuation_text
        current_assistant_message: TaChatMessage = {
            "role": "assistant",
            "content": continuation_text,
            "citations": parse_citations_single_run(continuation_text),
        }
        if include_system:
            return prompt_msgs + [current_assistant_message]
        else:
            return prompt_msgs[1:] + [current_assistant_message]

    async def _send_state():
        nonlocal prompt_msgs, continuation_text
        await send_stream.send(
            {
                "text": continuation_text,
                "messages": _get_complete_message_list(include_system=False),
            }
        )

    async def _llm_callback(batch_index: int, llm_output: LLMOutput):
        nonlocal continuation_text
        text = llm_output.first_text
        if text:
            continuation_text = text
            await _send_state()

    async def _execute():
        # Immediately send back the initial message state
        await _send_state()

        # Get LLM response
        await get_llm_completions_async(
            [cast(list[dict[str, Any]], prompt_msgs)],
            PROVIDER_PREFERENCES.handle_ta_message,
            max_new_tokens=8192,
            timeout=180.0,
            streaming_callback=_llm_callback,
            use_cache=True,
        )

        # After generation completes, update the session with the new messages
        updated_messages = _get_complete_message_list()

        # Update the database with the new messages
        async with mono_svc.db.session() as db_session:
            await db_session.execute(
                update(SQLAChatSession)
                .where(SQLAChatSession.id == session_id)
                .values(
                    messages=updated_messages, updated_at=datetime.now(UTC).replace(tzinfo=None)
                )
            )
            await db_session.commit()

        # Close the stream
        await send_stream.aclose()

    return StreamingResponse(
        sse_event_stream(_execute, send_stream, recv_stream), media_type="text/event-stream"
    )


#########
# Diffs #
#########

# TODO(mengk): not authenticated properly


class ComputeDiffRequest(BaseModel):
    experiment_id_1: str
    experiment_id_2: str


class StreamedDiffs(TypedDict):
    num_pairs_done: int
    num_pairs_total: int
    transcript_diff: dict[str, Any] | None  # a TranscriptDiff as json


class StreamedDiffSearchResult(TypedDict):
    claim: str | None
    alignment: int
    query: str
    num_results_done: int
    num_results_total: int


# @user_router.get("/{collection_id}/diffs_reports/{diffs_report_id}")
# async def get_diffs_report(
#     diffs_report_id: str,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.READ)),
# ):
#     report = await mono_svc.get_diffs_report(diffs_report_id)

#     return report.to_pydantic().model_dump()


# @user_router.post("/{collection_id}/start_compute_diffs")
# async def start_compute_diffs(
#     collection_id: str,
#     request: ComputeDiffRequest,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
# ):
#     from docent_core._ai_tools.diffs.models import SQLADiffsReport

#     # Check if a report already exists for these experiment IDs
#     # FIXME(mengk): SQL should not be in the router
#     async with mono_svc.mono_svc.session() as session:
#         existing_report = (
#             await session.execute(
#                 select(SQLADiffsReport).where(
#                     SQLADiffsReport.experiment_id_1 == request.experiment_id_1,
#                     SQLADiffsReport.experiment_id_2 == request.experiment_id_2,
#                     SQLADiffsReport.collection_id == collection_id,
#                 )
#             )
#         ).scalar_one_or_none()

#     existing_report = None  # FIXME(kevin): remove this

#     if existing_report:
#         return {
#             "job_id": None,
#             "diffs_report_id": existing_report.id,
#         }

#     report = SQLADiffsReport(
#         id=str(uuid4()),
#         collection_id=collection_id,
#         name=f"{request.experiment_id_1} vs {request.experiment_id_2}",
#         experiment_id_1=request.experiment_id_1,
#         experiment_id_2=request.experiment_id_2,
#     )
#     async with mono_svc.mono_svc.session() as session:
#         session.add(report)
#     job_id = await mono_svc.add_job(
#         "compute_diffs",
#         {
#             "collection_id": collection_id,
#             "diffs_report_id": report.id,
#         },
#     )

#     return {
#         "job_id": job_id,
#         "diffs_report_id": report.id,
#     }


# @user_router.get("/{collection_id}/listen_compute_diffs")
# async def listen_compute_diffs(
#     collection_id: str,
#     job_id: str,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
# ):
#     from sqlalchemy import select

#     from docent_core._ai_tools.diffs.models import SQLADiffsReport

#     # Retrieve job arguments
#     job = await mono_svc.get_job(job_id)
#     if job is None:
#         raise ValueError(f"Job {job_id} not found")
#     diffs_report_id = job.job_json["diffs_report_id"]

#     async with mono_svc.mono_svc.session() as session:
#         diffs_report = (
#             await session.execute(
#                 select(SQLADiffsReport).where(SQLADiffsReport.id == diffs_report_id)
#             )
#         ).scalar_one()

#     experiment_id_1, experiment_id_2 = diffs_report.experiment_id_1, diffs_report.experiment_id_2

#     # Create AnyIO queue that we can write intermediate results to
#     send_stream, recv_stream = anyio.create_memory_object_stream[StreamedDiffs](
#         max_buffer_size=100_000
#     )

#     # Track intermediate progress
#     progress_lock = anyio.Lock()
#     num_done, num_total = 0, 0  # Will be set after getting datapoints

#     from docent_core._ai_tools.diffs.models import TranscriptDiff

#     async def _ws_diff_streaming_callback(
#         transcript_diff: TranscriptDiff | None,
#     ) -> None:
#         nonlocal num_done

#         async with progress_lock:
#             num_done += 1
#             payload: StreamedDiffs = {
#                 "num_pairs_done": num_done,
#                 "num_pairs_total": num_total,
#                 "transcript_diff": transcript_diff.model_dump() if transcript_diff else None,
#             }

#         # Send to event_stream so it can be sent back to the client
#         await send_stream.send(payload)

#         if num_done == num_total:
#             # Terminate the stream so the event_stream stops waiting
#             await send_stream.aclose()

#     async def _execute():
#         async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
#             # Get total number of pairs to compute
#             datapoints = await mono_svc.get_agent_runs(ctx)

#             # group by sample_id, task_id, epoch_id
#             datapoints_by_sample_task_epoch: dict[tuple[str, str, str], list[AgentRun]] = {}
#             for dp in datapoints:
#                 key = (
#                     str(dp.metadata.get("sample_id")),
#                     str(dp.metadata.get("task_id")),
#                     str(dp.metadata.get("epoch_id")),
#                 )
#                 if key not in datapoints_by_sample_task_epoch:
#                     datapoints_by_sample_task_epoch[key] = []
#                 datapoints_by_sample_task_epoch[key].append(dp)

#             # Count total pairs to compute
#             nonlocal num_total
#             for datapoint_lists in datapoints_by_sample_task_epoch.values():
#                 first_pair_candidates = [
#                     dp
#                     for dp in datapoint_lists
#                     if dp.metadata.get("experiment_id") == experiment_id_1
#                 ]
#                 second_pair_candidates = [
#                     dp
#                     for dp in datapoint_lists
#                     if dp.metadata.get("experiment_id") == experiment_id_2
#                 ]
#                 if len(first_pair_candidates) > 0 and len(second_pair_candidates) > 0:
#                     num_total += 1

#             # Send initial 0% state message
#             init_data = StreamedDiffs(
#                 num_pairs_done=0,
#                 num_pairs_total=num_total,
#                 transcript_diff=None,
#             )
#             await send_stream.send(init_data)

#             # Compute diffs
#             await mono_svc.compute_diffs(ctx, diffs_report.id, _ws_diff_streaming_callback)

#             # Final refresh of state
#             await publish_homepage_state(mono_svc, ctx)

#     return StreamingResponse(
#         sse_event_stream(_execute, send_stream, recv_stream), media_type="text/event-stream"
#     )


########################
# Clustering diffs
########################


# class ComputeClusteringDiffsRequest(BaseModel):
#     diffs_report_id: str


# @user_router.post("/{collection_id}/compute_diff_clusters")
# async def compute_diff_clusters(
#     collection_id: str,
#     request: ComputeClusteringDiffsRequest,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_collection_permission(Permission.WRITE)),
# ):
#     diffs_report = await mono_svc.get_diffs_report(request.diffs_report_id)
#     claims = [c.to_pydantic() for diff in diffs_report.diffs for c in diff.claims]
#     clusters = await mono_svc.compute_diff_clusters(
#         ctx,
#         claims,
#     )

#     return clusters


class ComputeDiffSearchRequest(BaseModel):
    experiment_id_1: str
    experiment_id_2: str
    search_query: str


# @user_router.post("/{collection_id}/start_compute_diff_search")
# async def start_compute_diff_search(
#     collection_id: str,
#     request: ComputeDiffSearchRequest,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
# ):
#     job_id = await mono_svc.add_job(
#         "diff",
#         {
#             "type": "compute_diff_search",
#             "collection_id": collection_id,
#             "experiment_id_1": request.experiment_id_1,
#             "experiment_id_2": request.experiment_id_2,
#             "search_query": request.search_query,
#         },
#     )
#     return job_id


# @user_router.get("/{collection_id}/listen_compute_diff_search")
# async def listen_compute_diff_search(
#     collection_id: str,
#     job_id: str,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_collection_permission(Permission.WRITE)),
# ):
#     # Retrieve job arguments
#     job = await mono_svc.get_job(job_id)
#     if job is None:
#         raise ValueError(f"Job {job_id} not found")
#     experiment_id_1, experiment_id_2, search_query = (
#         job.job_json["experiment_id_1"],
#         job.job_json["experiment_id_2"],
#         job.job_json["search_query"],
#     )

#     datapoints = await mono_svc.get_agent_runs(ctx)
#     expid_by_datapoint = {d.id: d.metadata.get("experiment_id") for d in datapoints}
#     async with mono_svc.session() as session:
#         result = await session.execute(
#             select(SQLADiffAttribute)
#             .where(
#                 SQLADiffAttribute.collection_id == ctx.collection_id,
#             )
#             .order_by(SQLADiffAttribute.id)
#         )
#         existing_diffs = result.scalars().all()
#         num_total = sum(
#             1
#             for d in existing_diffs
#             if expid_by_datapoint.get(d.data_id_1) == experiment_id_1
#             and expid_by_datapoint.get(d.data_id_2) == experiment_id_2
#         )

#     # Create AnyIO queue that we can write intermediate results to
#     send_stream, recv_stream = anyio.create_memory_object_stream[StreamedDiffSearchResult](
#         max_buffer_size=100_000
#     )

#     # Track intermediate progress
#     progress_lock = anyio.Lock()
#     num_done = 0

#     async def _diff_search_callback(search_result: tuple[str, int]) -> None:
#         nonlocal num_done

#         async with progress_lock:
#             num_done += 1
#             payload = StreamedDiffSearchResult(
#                 claim=search_result[0],
#                 alignment=search_result[1],
#                 query=search_query,
#                 num_results_done=num_done,
#                 num_results_total=num_total,
#             )

#         # Send to event_stream so it can be sent back to the client
#         await send_stream.send(payload)

#         if num_done == num_total:
#             # Terminate the stream so the event_stream stops waiting
#             await asyncio.sleep(1)
#             await send_stream.aclose()

#     async def _execute():
#         nonlocal num_total
#         async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
#             # Send initial 0% state message
#             init_data = StreamedDiffSearchResult(
#                 claim=None,
#                 alignment=0,
#                 query=search_query,
#                 num_results_done=0,
#                 num_results_total=num_total,
#             )
#             await send_stream.send(init_data)

#             # Get all diff search results
#             await mono_svc.compute_diff_search(
#                 ctx,
#                 experiment_id_1,
#                 experiment_id_2,
#                 search_query,
#                 _diff_search_callback,
#             )

#     return StreamingResponse(
#         sse_event_stream(_execute, send_stream, recv_stream), media_type="text/event-stream"
#     )


# @user_router.get("/{collection_id}/transcript_diff")
# async def get_transcript_diff(
#     agent_run_1_id: str,
#     agent_run_2_id: str,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.READ)),
# ):
#     """Get a transcript diff between two agent runs."""
#     from sqlalchemy import or_, select

#     from docent_core._ai_tools.diffs.models import SQLATranscriptDiff

#     # Query for transcript diff in either direction
#     async with mono_svc.mono_svc.session() as session:
#         result = await session.execute(
#             select(SQLATranscriptDiff).where(
#                 or_(
#                     and_(
#                         SQLATranscriptDiff.agent_run_1_id == agent_run_1_id,
#                         SQLATranscriptDiff.agent_run_2_id == agent_run_2_id,
#                     ),
#                     and_(
#                         SQLATranscriptDiff.agent_run_1_id == agent_run_2_id,
#                         SQLATranscriptDiff.agent_run_2_id == agent_run_1_id,
#                     ),
#                 )
#             )
#         )
#         transcript_diff = result.scalar_one_or_none()

#     if not transcript_diff:
#         return None


#     return transcript_diff.to_pydantic().model_dump()
