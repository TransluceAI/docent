import hashlib
import json
from datetime import UTC, datetime
from functools import partial
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, or_, select, update
from sqlalchemy.inspection import inspect as sqla_inspect

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import AgentRun, AgentRunWithoutMetadataValidator
from docent.data_models.citation import (
    Citation,
    parse_citations_single_run,
)
from docent_core._ai_tools.search import SearchResult, SearchResultWithCitations
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.filters import (
    ComplexFilter,
)
from docent_core._db_service.schemas.auth_models import (
    Permission,
    ResourceType,
    SubjectType,
    User,
)
from docent_core._db_service.schemas.collab_models import CollectionCollaborator
from docent_core._db_service.schemas.tables import (
    EndpointType,
    JobStatus,
    SQLAAccessControlEntry,
    SQLAChatSession,
    SQLAJob,
    SQLASearchCluster,
    SQLASearchResult,
    SQLASearchResultCluster,
)
from docent_core._db_service.service import DBService
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent_core._server._analytics.tracker import track_endpoint_with_user
from docent_core._server._assistant.chat import make_single_tasst_system_prompt
from docent_core._server._assistant.summarizer import (
    HighLevelAction,
    LowLevelAction,
    ObservationType,
    group_actions_into_high_level_steps,
    interesting_agent_observations,
    summarize_agent_actions,
)
from docent_core._server._auth.session import create_user_session, invalidate_user_session
from docent_core._server._broker.redis_client import (
    REDIS,
    enqueue_search_job,
    publish_to_broker,
)
from docent_core._server._dependencies.database import get_db, require_collection_exists
from docent_core._server._dependencies.permissions import (
    require_collection_permission,
    require_view_permission,
)
from docent_core._server._dependencies.user import (
    get_authenticated_user,
    get_default_view_ctx,
    get_user_anonymous_ok,
)
from docent_core._server._rest.send_state import (
    publish_collections,
    publish_homepage_state,
    publish_searches,
)
from docent_core._server.util import sse_event_stream

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
async def signup(request: UserCreateRequest, response: Response, db: DBService = Depends(get_db)):
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
    existing_user = await db.get_user_by_email(request.email)
    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="A user with this email address already exists. Please use the login page.",
        )

    user = await db.create_user(request.email, request.password)

    # Create a session for the new user
    await create_user_session(user.id, response)

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.SIGNUP, user)

    return user


class LoginRequest(BaseModel):
    email: str
    password: str


@public_router.post("/login")
async def login(request: LoginRequest, response: Response, db: DBService = Depends(get_db)):
    """
    User login endpoint. Authenticates a user and creates a session.

    Args:
        request: LoginRequest containing email and password
        response: FastAPI Response object to set cookies
        db: Database service dependency

    Returns:
        UserResponse with user_id and email
    """
    user = await db.verify_user_password(request.email, request.password)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Create a new session
    await create_user_session(user.id, response)

    return user


@public_router.post("/anonymous_session")
async def create_anonymous_session(response: Response, db: DBService = Depends(get_db)):
    """
    Create anonymous user endpoint. Creates a temporary anonymous user and session.

    Args:
        response: FastAPI Response object to set cookies
        db: Database service dependency

    Returns:
        User object with anonymous properties
    """
    # Create and persist anonymous user
    anonymous_user = await db.create_anonymous_user()

    # Create a session for the anonymous user
    await create_user_session(anonymous_user.id, response)

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.CREATE_ANONYMOUS_SESSION, anonymous_user)

    return anonymous_user


###########################
# Authenticated endpoints #
###########################


@user_router.get("/me")
async def get_current_user(request: Request, db: DBService = Depends(get_db)):
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
    session_id = request.cookies.get("docent_session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="No session found")

    # Get user by session ID
    user = await db.get_user_by_session_id(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return user


@user_router.post("/logout")
async def logout(request: Request, response: Response):
    """
    User logout endpoint. Invalidates the current session.

    Args:
        request: FastAPI Request object to access cookies
        response: FastAPI Response object to clear cookies

    Returns:
        Success message
    """
    # Get session ID from cookie
    session_id = request.cookies.get("docent_session_id")
    if session_id:
        # Invalidate the session using the auth helper
        await invalidate_user_session(session_id, response)

    return {"message": "Logged out successfully"}


##############
# Raw access #
##############


# class RawQueryRequest(BaseModel):
#     query: str


# # @user_router.post("/raw_query")
# # async def raw_query(request: RawQueryRequest, db: DBService = Depends(get_db)):
# #     return await db.run_raw_query(request.query)


#############
# Collection #
#############


@user_router.get("/collections")
async def get_collections(
    user: User = Depends(get_user_anonymous_ok), db: DBService = Depends(get_db)
):
    sqla_collections = await db.get_collections(user)  # Filter to only the user's collections
    return [
        # Get all columns from the SQLAlchemy object
        {c.key: getattr(obj, c.key) for c in sqla_inspect(obj).mapper.column_attrs}
        for obj in sqla_collections
        if await db.has_permission(
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
    db: DBService = Depends(get_db),
):
    collection_id = await db.create_collection(
        user=user,
        collection_id=request.collection_id,
        name=request.name,
        description=request.description,
    )
    # Publish updated collections list to all clients
    await publish_collections(db)

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.CREATE_FG, user, collection_id)

    return {"collection_id": collection_id}


class UpdateCollectionRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@user_router.put("/{collection_id}/collection")
async def update_collection(
    collection_id: str,
    request: UpdateCollectionRequest,
    db: DBService = Depends(get_db),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    await db.update_collection(collection_id, name=request.name, description=request.description)

    # Publish updated collections list to all clients
    await publish_collections(db)

    return {"collection_id": collection_id}


@user_router.delete("/{collection_id}/collection")
async def delete_collection(
    collection_id: str,
    db: DBService = Depends(get_db),
    _: None = Depends(require_collection_permission(Permission.ADMIN)),
):
    await db.delete_collection(collection_id)
    # Notify about the specific deleted collection
    await publish_to_broker(
        None,  # Broadcast to all connections
        {
            "action": "collection_deleted",
            "payload": {"collection_id": collection_id},
        },
    )
    # Also publish the updated list of collections
    await publish_collections(db)
    return {"status": "success", "collection_id": collection_id}


##############
# Agent runs #
##############


@user_router.get("/{collection_id}/agent_run_metadata_fields")
async def agent_run_metadata_fields(
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    # Get any agent_run to get the metadata fields
    any_data = await db.get_any_agent_run(ctx)
    if any_data is not None:
        fields = any_data.get_filterable_fields()
    else:
        fields = []

    return {"fields": fields}


@user_router.get("/{collection_id}/agent_run")
async def get_agent_run(
    agent_run_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    # Track analytics
    await track_endpoint_with_user(db, EndpointType.GET_AGENT_RUN, ctx.user, ctx.collection_id)

    return await db.get_agent_run(ctx, agent_run_id)


class AgentRunMetadataRequest(BaseModel):
    agent_run_ids: list[str]


@user_router.post("/{collection_id}/agent_run_metadata")
async def get_agent_run_metadata(
    request: AgentRunMetadataRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    data = await db.get_agent_runs(ctx, agent_run_ids=request.agent_run_ids)
    return {d.id: d.metadata.model_dump(strip_internal_fields=True) for d in data}


class PostAgentRunsRequest(BaseModel):
    agent_runs: list[AgentRunWithoutMetadataValidator]


@user_router.post("/{collection_id}/agent_runs")
async def post_agent_runs(
    collection_id: str,
    request: PostAgentRunsRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    async with db.advisory_lock(collection_id, action_id="mutation"):
        await db.add_agent_runs(ctx, request.agent_runs)

        # Publish state of ALL views
        for ctx in await db.get_all_view_ctxs(collection_id):
            await publish_homepage_state(db, ctx)

    # Track analytics - we need to get the user from the context
    await track_endpoint_with_user(db, EndpointType.POST_AGENT_RUNS, ctx.user, collection_id)


########
# View #
########


@user_router.post("/{collection_id}/join")
async def join(
    collection_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    if not await db.fg_exists(collection_id):
        raise HTTPException(status_code=404, detail=f"Collection with ID {collection_id} not found")

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.JOIN, ctx.user, collection_id)

    return {"collection_id": collection_id, "view_id": ctx.view_id}


class SetIODimsRequest(BaseModel):
    inner_bin_key: str | None = None
    outer_bin_key: str | None = None


@user_router.post("/{collection_id}/set_io_bin_keys")
async def set_io_bin_keys(
    collection_id: str,
    request: SetIODimsRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with db.advisory_lock(collection_id, action_id="mutation"):
        await db.set_io_bin_keys(ctx, request.inner_bin_key, request.outer_bin_key)
        await publish_homepage_state(db, ctx)

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.SET_IO_BIN_KEYS, ctx.user, collection_id)


class SetIODimWithMetadataKeyRequest(BaseModel):
    metadata_key: str
    type: Literal["inner", "outer"]


@user_router.post("/{collection_id}/io_bin_key_with_metadata_key")
async def set_io_bin_key_with_metadata_key_endpoint(
    collection_id: str,
    request: SetIODimWithMetadataKeyRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with db.advisory_lock(collection_id, action_id="mutation"):
        await db.set_io_bin_key_with_metadata_key(ctx, request.metadata_key, request.type)
        await publish_homepage_state(db, ctx)

    # Track analytics
    await track_endpoint_with_user(
        db, EndpointType.SET_IO_BIN_KEY_WITH_METADATA_KEY, ctx.user, collection_id
    )


class PostBaseFilterRequest(BaseModel):
    filter: ComplexFilter | None


@user_router.post("/{collection_id}/base_filter")
async def post_base_filter(
    collection_id: str,
    request: PostBaseFilterRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with db.advisory_lock(collection_id, action_id="mutation"):
        if request.filter is None:
            new_ctx = await db.clear_view_base_filter(ctx)
        else:
            new_ctx = await db.set_view_base_filter(ctx, request.filter)

        # Publish the updated state
        await publish_homepage_state(db, new_ctx)

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.POST_BASE_FILTER, ctx.user, collection_id)

    return {"status": "ok"}


@user_router.post("/{collection_id}/clone_own_view")
async def clone_own_view(
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    new_view_id = await db.clone_view_for_sharing(ctx)

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.CLONE_OWN_VIEW, ctx.user, ctx.collection_id)

    return {"view_id": new_view_id}


class ApplyExistingFilterRequest(BaseModel):
    search_query: str
    view_id: str


@user_router.post("/{collection_id}/apply_existing_view")
async def apply_existing_view(
    request: ApplyExistingFilterRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    existing_view = await db.get_view(request.view_id)
    ctx = await db.set_view_base_filter(ctx, existing_view.base_filter)
    await db.set_io_bin_keys(ctx, existing_view.inner_bin_key, existing_view.outer_bin_key)
    await publish_homepage_state(db, ctx)

    # Track analytics
    await track_endpoint_with_user(
        db, EndpointType.APPLY_EXISTING_VIEW, ctx.user, ctx.collection_id
    )

    # Get the existing search query; tells frontend whether to load clusters
    existing_search_query = await db.get_search_query_by_query(
        ctx.collection_id, request.search_query
    )
    return existing_search_query is not None


@user_router.get("/{collection_id}/get_existing_search_results")
async def get_existing_search_results(
    search_query: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    results = await db.get_search_results(ctx, search_query)

    # Construct a map from agent_run_id -> search query -> list of SearchResultWithCitations
    data_dict: dict[str, dict[str, list[SearchResultWithCitations]]] = {}
    for result in results:
        data_dict.setdefault(result.agent_run_id, {}).setdefault(result.search_query, []).append(
            SearchResultWithCitations.from_search_result(result)
        )

    # Track analytics
    await track_endpoint_with_user(
        db, EndpointType.GET_EXISTING_SEARCH_RESULTS, ctx.user, ctx.collection_id
    )

    num_search_hits = len([result for result in results if result.value is not None])

    return StreamedSearchResult(
        data_dict=data_dict,
        num_agent_runs_done=len(data_dict.keys()),
        num_agent_runs_total=len(data_dict.keys()),
        num_search_hits=num_search_hits,
    )


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
#     filter = await db.get_filter(filter_id)
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

#     agent_runs = await db.get_agent_runs(ctx, agent_run_ids=request.agent_run_ids)

#     # Track analytics
#     await track_endpoint_with_user(db, EndpointType.GET_REGEX_SNIPPETS_ENDPOINT, ctx.user, ctx.collection_id)

#     return {
#         d.id: [item for p in patterns for item in get_regex_snippets(d.text, p)] for d in agent_runs
#     }


@user_router.get("/{collection_id}/state")
async def get_state(
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    await publish_homepage_state(db, ctx)


@user_router.get("/{collection_id}/searches")
async def get_searches(
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    # The service method returns a list of dicts, which is fine for JSON response
    return await db.get_searches_with_result_counts(ctx)


@user_router.delete("/{collection_id}/search")
async def delete_search(
    collection_id: str,
    search_query_id: str,
    db: DBService = Depends(get_db),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    await db.delete_search_query(collection_id, search_query_id)

    # Publish updated searches state to all views in this collection
    for ctx in await db.get_all_view_ctxs(collection_id):
        await publish_searches(db, ctx)

    return {"status": "success", "search_query_id": search_query_id}


@user_router.get("/users/by-email/{email}")
async def get_user_by_email(email: str, db: DBService = Depends(get_db)):
    """
    Get a user by their email address.
    Args:
        email: The email address to search for
        db: Database service dependency
    Returns:
        User object if found, None otherwise
    """
    return await db.get_user_by_email(email)


class UserPermissionsResponse(BaseModel):
    collection_permissions: dict[str, str | None]
    view_permissions: dict[str, str | None]


@user_router.get("/{collection_id}/permissions")
async def get_user_permissions(
    collection_id: str = Depends(require_collection_exists),
    user: User = Depends(get_user_anonymous_ok),
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    fg_permission = await db.get_permission_level(
        user=user,
        resource_type=ResourceType.COLLECTION,
        resource_id=collection_id,
    )

    view_permission = await db.get_permission_level(
        user=user,
        resource_type=ResourceType.VIEW,
        resource_id=ctx.view_id,
    )

    return UserPermissionsResponse(
        collection_permissions={collection_id: fg_permission.value if fg_permission else None},
        view_permissions={ctx.view_id: view_permission.value if view_permission else None},
    )


@user_router.get("/organizations/{org_id}/users")
async def get_org_users(org_id: str, db: DBService = Depends(get_db)):
    return [u for u in await db.get_users() if not u.is_anonymous]


@user_router.get("/collections/{collection_id}/collaborators")
async def get_collection_collaborators(
    collection_id: str,
    db: DBService = Depends(get_db),
    # You need READ permissions to see other people's permissions
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    return [
        CollectionCollaborator.from_sqla_acl(acl)
        for acl in await db.get_acl_entries(
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
    db: DBService = Depends(get_db),
    _: None = Depends(require_collection_permission(Permission.ADMIN)),
):
    collaborator = await db.set_acl_permission(
        subject_type=request.subject_type,
        subject_id=request.subject_id,
        resource_type=ResourceType.COLLECTION,
        resource_id=collection_id,
        permission=request.permission_level,
    )

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.UPSERT_COLLABORATOR, user, collection_id)

    return collaborator


class RemoveCollaboratorRequest(BaseModel):
    subject_id: str
    subject_type: SubjectType
    collection_id: str


@user_router.delete("/collections/{collection_id}/collaborators/delete")
async def remove_collaborator(
    collection_id: str,
    request: RemoveCollaboratorRequest,
    db: DBService = Depends(get_db),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_collection_permission(Permission.ADMIN)),
):
    async with db.session() as session:
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

    await db.clear_acl_permission(
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


# @user_router.post("/{collection_id}/share_view")
# async def share_view(
#     collection_id: str,
#     request: ShareViewRequest,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_collection_permission(Permission.READ)),
# ):
#     await db.set_acl_permission(
#         subject_type=SubjectType(request.subject_type),
#         subject_id=request.subject_id,
#         resource_type=ResourceType.VIEW,
#         resource_id=ctx.view_id,
#         permission=Permission(request.level),
#     )
#     return {"status": "success"}


##################################
# (View-specific) dims + filters #
##################################


# class PostDimensionRequest(BaseModel):
#     dim: str


# @user_router.post("/{collection_id}/dimension")
# async def post_dimension(
#     collection_id: str,
#     request: PostDimensionRequest,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.WRITE)),
# ):
#     await publish_binnable_keys(db, ctx)
#     await publish_searches(db, ctx)

#     # Track analytics
#     await track_endpoint_with_user(db, EndpointType.POST_DIMENSION, ctx.user, ctx.collection_id)

#     return request.dim


# class GetDimensionsRequest(BaseModel):
#     dim_ids: list[str] | None = None


# @user_router.post("/{collection_id}/get_dimensions")
# async def get_dimensions(
#     request: GetDimensionsRequest,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.READ)),
# ):
#     if request.dim_ids is None:
#         return await db.get_binnable_keys(ctx)
#     else:
#         raise ValueError("dim_ids are not supported")


# @user_router.delete("/{collection_id}/dimension")
# async def delete_dimension(
#     collection_id: str,
#     dim_id: str,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.WRITE)),
# ):
#     async with db.advisory_lock(collection_id, action_id="mutation"):
#         await db.delete_dimension(dim_id)
#         await publish_binnable_keys(db, ctx)

#         # TODO: This is a collection-wide operation that affects all views.
#         # We should either:
#         # 1. Make publish_attribute_searches collection-wide (not view-specific), OR
#         # 2. Publish to all views in this collection
#         # For now, using the authenticated user's ViewProvider.
#         await publish_searches(db, ctx)


# @user_router.delete("/{collection_id}/filter")
# async def delete_filter(
#     collection_id: str,
#     dim_id: str,
#     filter_id: str,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.WRITE)),
# ):
#     async with db.advisory_lock(collection_id, action_id="mutation"):
#         await db.delete_filter(filter_id)

#     # Track analytics
#     await track_endpoint_with_user(db, EndpointType.DELETE_FILTER, ctx.user, collection_id)


# class PostFilterRequest(BaseModel):
#     dim_id: str | None = None
#     filter_id: str
#     new_predicate: str


# @user_router.post("/{collection_id}/filter")
# async def post_filter(
#     collection_id: str,
#     request: PostFilterRequest,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.WRITE)),
# ):
#     async with db.advisory_lock(collection_id, action_id="mutation"):
#         old_filter = await db.get_filter(request.filter_id)
#         if old_filter is None:
#             raise ValueError(f"Filter {request.filter_id} not found")

#         # Push filter (takes care of clearing related judgments)
#         new_filter = old_filter.model_copy(
#             update={"name": request.new_predicate, "predicate": request.new_predicate}
#         )

#         if request.dim_id:
#             raise ValueError("dim_ids are not supported")

#     # Track analytics
#     await track_endpoint_with_user(db, EndpointType.POST_FILTER, ctx.user, collection_id)

#     return new_filter.id


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


@user_router.post("/{collection_id}/start_compute_search")
async def start_compute_search(
    collection_id: str,
    request: ComputeSearchRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    query_id = await db.add_search_query(ctx, request.search_query)
    new, job_id = await db.add_search_job(query_id)
    if new:
        # When we enqueue the job, check if the user has write perms
        write_allowed = await db.has_permission(
            user=user,
            resource_type=ResourceType.COLLECTION,
            resource_id=collection_id,
            permission=Permission.WRITE,
        )
        await enqueue_search_job(ctx, job_id, read_only=not write_allowed)

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.START_COMPUTE_SEARCH, ctx.user, collection_id)

    return job_id


@user_router.get("/{collection_id}/listen_compute_search")
async def listen_compute_search(
    collection_id: str,
    job_id: str,
    max_results: int | None = None,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    # Retrieve job arguments
    job = await db.get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")

    # Create AnyIO queue that we can write intermediate results to
    # At the max size of the queue, the producer will block
    send_stream, recv_stream = anyio.create_memory_object_stream[StreamedSearchResult](
        max_buffer_size=100_000
    )

    # Track intermediate progress
    num_errors = 0
    num_results = 0
    num_done, num_total = 0, await db.count_base_agent_runs(ctx)

    async def _execute():
        # Send initial 0% state message
        init_data = StreamedSearchResult(
            data_dict={},
            num_agent_runs_done=0,
            num_agent_runs_total=num_total,
            num_search_hits=0,
        )
        await send_stream.send(init_data)
        nonlocal num_done, num_errors, num_results

        try:
            last_id = 0
            while True:
                results_batch = await REDIS.xread({f"results_{job_id}": last_id}, block=0)

                # xread can handle multiple streams and returns a list of (stream, results) pairs; we
                # only have one, so just index by 0 and then 1 to go directly to the results we want.
                results_batch = results_batch[0][1]

                last_id = results_batch[-1][0]

                for _, sub_batch in results_batch:
                    results = json.loads(sub_batch["results"])
                    if results is None:
                        num_errors += 1
                        if num_done + num_errors == num_total:
                            return
                        continue

                    results = [SearchResult.model_validate(r) for r in results]
                    # Only count results that have a hit
                    num_results += len([result for result in results if result.value is not None])

                    # Construct a map from agent_run_id -> search query -> list of SearchResultWithCitations
                    data_dict: dict[str, dict[str, list[SearchResultWithCitations]]] = {}
                    for result in results:
                        data_dict.setdefault(result.agent_run_id, {}).setdefault(
                            result.search_query, []
                        ).append(SearchResultWithCitations.from_search_result(result))

                    # Each agent_run is only included in one callback
                    num_done += len(data_dict.keys())

                    payload = StreamedSearchResult(
                        data_dict=data_dict,
                        num_agent_runs_done=num_done,
                        num_agent_runs_total=num_total,
                        num_search_hits=num_results,
                    )

                    # Send to event_stream so it can be sent back to the client
                    await send_stream.send(payload)

                    # Check if we've reached max_results
                    if max_results is not None and num_results >= max_results:
                        q = f"commands_{job_id}"
                        await REDIS.rpush(q, "cancel")  # type: ignore

                    if num_done + num_errors == num_total:
                        return
        finally:
            # Terminate the stream so the event_stream stops waiting
            await send_stream.aclose()

    return StreamingResponse(
        sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
    )


@user_router.post("/{job_id}/cancel_compute_search")
async def cancel_compute_search(job_id: str):
    q = f"commands_{job_id}"
    await REDIS.rpush(q, "cancel")  # type: ignore


@user_router.post("/{query_id}/resume_compute_search")
async def resume_compute_search(
    query_id: str,
    db: DBService = Depends(get_db),
    user: User = Depends(get_user_anonymous_ok),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    new, job_id = await db.add_search_job(query_id)
    query = await db.get_search_query(query_id)
    if new:
        # When we enqueue the job, check if the user has write perms
        write_allowed = await db.has_permission(
            user=user,
            resource_type=ResourceType.COLLECTION,
            resource_id=query.collection_id,
            permission=Permission.WRITE,
        )
        await enqueue_search_job(ctx, job_id, read_only=not write_allowed)

    # Track analytics
    await track_endpoint_with_user(
        db, EndpointType.RESUME_COMPUTE_SEARCH, ctx.user, query.collection_id
    )

    return job_id


@user_router.post("/{collection_id}/has_embedding_job")
async def has_embedding_job(
    collection_id: str,
    db: DBService = Depends(get_db),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    where_clause = or_(SQLAJob.status == JobStatus.PENDING, SQLAJob.status == JobStatus.RUNNING)
    count = await db.get_embedding_job_count(collection_id, where_clause)
    return count > 0


@user_router.post("/{collection_id}/fg_has_embeddings")
async def fg_has_embeddings(
    collection_id: str,
    db: DBService = Depends(get_db),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    return await db.fg_has_embeddings(collection_id)


@user_router.post("/{collection_id}/compute_embeddings")
async def compute_embeddings(
    collection_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    await db.add_and_enqueue_embedding_job(ctx)


@user_router.get("/search_jobs")
async def search_jobs(
    db: DBService = Depends(get_db),
):
    jobs = await db.list_search_jobs_and_queries()
    for job in jobs:
        logger.info(f"- {job}")
    return [[job.dict(), query.dict()] for job, query in jobs]


class ClusterSearchResultsRequest(BaseModel):
    search_query: str
    feedback: str | None
    read_only: bool = False


@user_router.post("/{collection_id}/start_cluster_search_results")
async def start_cluster_search_results(
    collection_id: str,
    request: ClusterSearchResultsRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Start clustering search results directly."""

    # If not read_only, check if the user has write permission
    if not request.read_only:
        write_allowed = await db.has_permission(
            user=user,
            resource_type=ResourceType.COLLECTION,
            resource_id=collection_id,
            permission=Permission.WRITE,
        )
        if not write_allowed:
            raise HTTPException(status_code=403, detail="User does not have write permission")

    job_id = await db.add_job(
        "cluster_search_results",
        {
            "collection_id": collection_id,
            "search_query": request.search_query,
            "feedback": request.feedback,
            "read_only": request.read_only,
        },
    )

    # Track analytics - we need to get the user from the context
    await track_endpoint_with_user(
        db, EndpointType.START_CLUSTER_SEARCH_RESULTS, ctx.user, collection_id
    )

    return job_id


@user_router.get("/{collection_id}/listen_cluster_search_results")
async def listen_cluster_search_results(
    collection_id: str,
    job_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    """Start clustering search results in the background.

    Send cluster assignments to the client as they are computed.
    """
    # Retrieve job arguments
    job = await db.get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    job = job.job_json
    collection_id, search_query, feedback, read_only = (
        job["collection_id"],
        job["search_query"],
        job.get("feedback"),
        job["read_only"],
    )

    send_stream, recv_stream = anyio.create_memory_object_stream[list[dict[str, Any]]](
        max_buffer_size=100_000
    )

    async def execute():
        async with db.advisory_lock(
            collection_id + "__cluster_search__" + search_query, action_id="mutation"
        ):
            async with anyio.create_task_group() as tg:
                done = False
                existing_clusters: list[dict[str, Any]] | None = None

                if feedback is not None and feedback != "":
                    # record existing clusters for re-clustering
                    existing_clusters = await db.get_existing_search_clusters(ctx, search_query)
                    # delete existing clusters, so we don't send the old ones
                    await db.clear_search_result_clusters(ctx, search_query)

                async def _f():
                    nonlocal done

                    await db.cluster_search_results(ctx, search_query, feedback, existing_clusters)
                    # Wait for the last assignments to be sent
                    await anyio.sleep(1)

                    done = True

                # Only compute new clusters if not read_only
                logger.critical(f"read_only: {read_only}")
                if not read_only:
                    tg.start_soon(_f)
                else:
                    done = True

                already_sent_search_result_assignments: set[str] = set()
                while True:
                    # Read search results from the DB that have not been sent yet
                    async with db.session() as session:
                        result = await session.execute(
                            select(SQLASearchResultCluster, SQLASearchResult, SQLASearchCluster)
                            .join(
                                SQLASearchResult,
                                SQLASearchResultCluster.search_result_id == SQLASearchResult.id,
                            )
                            .join(
                                SQLASearchCluster,
                                SQLASearchResultCluster.cluster_id == SQLASearchCluster.id,
                            )
                            .where(
                                SQLASearchCluster.collection_id == ctx.collection_id,
                                SQLASearchCluster.search_query == search_query,
                                SQLASearchResultCluster.id.notin_(
                                    already_sent_search_result_assignments
                                ),
                            )
                        )
                        search_results_assignments = result.all()

                    if len(search_results_assignments) > 0:
                        # Form json payload with the list of assignments not already sent
                        payload: list[dict[str, Any]] = []
                        for assignment, search_result, cluster in search_results_assignments:
                            if assignment.id not in already_sent_search_result_assignments:
                                payload.append(
                                    {
                                        "search_result_cluster_id": assignment.id,
                                        "search_result_id": assignment.search_result_id,
                                        "cluster_id": assignment.cluster_id,
                                        "centroid": cluster.centroid,
                                        "value": search_result.value,
                                        "decision": assignment.decision,
                                    }
                                )
                                already_sent_search_result_assignments.add(assignment.id)

                        await send_stream.send(payload)

                    # Check done here to help avoid final payload being dropped
                    if done:
                        break

                    await anyio.sleep(1)

                await send_stream.aclose()

    return StreamingResponse(sse_event_stream(execute, recv_stream), media_type="text/event-stream")


#######################
# Agent run summaries #
#######################


@user_router.get("/{collection_id}/actions_summary")
async def get_actions_summary(
    agent_run_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    agent_run = await db.get_agent_run(ctx, agent_run_id)
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
        sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
    )


# @user_router.get("/{collection_id}/solution_summary")
# async def get_solution_summary(
#     agent_run_id: str,
#     db: DBService = Depends(get_db),
#     ctx: ViewContext = Depends(get_default_view_ctx),
#     _: None = Depends(require_view_permission(Permission.READ)),
# ):
#     agent_run = await db.get_agent_run(ctx, agent_run_id)
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
#         sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
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
    db: DBService = Depends(get_db),
):
    """
    Get the message history for an existing TA session.
    """
    async with db.session() as session:
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
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    agent_run_id = request.agent_run_id

    agent_run = await db.get_agent_run(ctx, agent_run_id)
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

    async with db.session() as session:
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
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    # Get session from database
    async with db.session() as session:
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
        async with db.session() as db_session:
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

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.GET_TA_MESSAGE, ctx.user, ctx.collection_id)

    return StreamingResponse(
        sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
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


@user_router.get("/{collection_id}/diffs_reports/{diffs_report_id}")
async def get_diffs_report(
    diffs_report_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    report = await db.get_diffs_report(diffs_report_id)

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.GET_DIFFS_REPORT, ctx.user, ctx.collection_id)

    return report.to_pydantic().model_dump()


@user_router.post("/{collection_id}/start_compute_diffs")
async def start_compute_diffs(
    collection_id: str,
    request: ComputeDiffRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
):
    from docent_core._ai_tools.diffs.models import SQLADiffsReport

    # Check if a report already exists for these experiment IDs
    # FIXME(mengk): SQL should not be in the router
    async with db.session() as session:
        existing_report = (
            await session.execute(
                select(SQLADiffsReport).where(
                    SQLADiffsReport.experiment_id_1 == request.experiment_id_1,
                    SQLADiffsReport.experiment_id_2 == request.experiment_id_2,
                    SQLADiffsReport.collection_id == collection_id,
                )
            )
        ).scalar_one_or_none()

    existing_report = None  # FIXME(kevin): remove this

    if existing_report:
        return {
            "job_id": None,
            "diffs_report_id": existing_report.id,
        }

    report = SQLADiffsReport(
        id=str(uuid4()),
        collection_id=collection_id,
        name=f"{request.experiment_id_1} vs {request.experiment_id_2}",
        experiment_id_1=request.experiment_id_1,
        experiment_id_2=request.experiment_id_2,
    )
    async with db.session() as session:
        session.add(report)
    job_id = await db.add_job(
        "compute_diffs",
        {
            "collection_id": collection_id,
            "diffs_report_id": report.id,
        },
    )

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.START_COMPUTE_DIFFS, ctx.user, collection_id)

    return {
        "job_id": job_id,
        "diffs_report_id": report.id,
    }


@user_router.get("/{collection_id}/listen_compute_diffs")
async def listen_compute_diffs(
    collection_id: str,
    job_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
):
    from sqlalchemy import select

    from docent_core._ai_tools.diffs.models import SQLADiffsReport

    # Retrieve job arguments
    job = await db.get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    diffs_report_id = job.job_json["diffs_report_id"]

    async with db.session() as session:
        diffs_report = (
            await session.execute(
                select(SQLADiffsReport).where(SQLADiffsReport.id == diffs_report_id)
            )
        ).scalar_one()

    experiment_id_1, experiment_id_2 = diffs_report.experiment_id_1, diffs_report.experiment_id_2

    # Create AnyIO queue that we can write intermediate results to
    send_stream, recv_stream = anyio.create_memory_object_stream[StreamedDiffs](
        max_buffer_size=100_000
    )

    # Track intermediate progress
    progress_lock = anyio.Lock()
    num_done, num_total = 0, 0  # Will be set after getting datapoints

    from docent_core._ai_tools.diffs.models import TranscriptDiff

    async def _ws_diff_streaming_callback(
        transcript_diff: TranscriptDiff | None,
    ) -> None:
        nonlocal num_done

        async with progress_lock:
            num_done += 1
            payload: StreamedDiffs = {
                "num_pairs_done": num_done,
                "num_pairs_total": num_total,
                "transcript_diff": transcript_diff.model_dump() if transcript_diff else None,
            }

        # Send to event_stream so it can be sent back to the client
        await send_stream.send(payload)

        if num_done == num_total:
            # Terminate the stream so the event_stream stops waiting
            await send_stream.aclose()

    async def _execute():
        async with db.advisory_lock(collection_id, action_id="mutation"):
            # Get total number of pairs to compute
            datapoints = await db.get_agent_runs(ctx)

            # group by sample_id, task_id, epoch_id
            datapoints_by_sample_task_epoch: dict[tuple[str, str, str], list[AgentRun]] = {}
            for dp in datapoints:
                key = (
                    str(dp.metadata.get("sample_id")),
                    str(dp.metadata.get("task_id")),
                    str(dp.metadata.get("epoch_id")),
                )
                if key not in datapoints_by_sample_task_epoch:
                    datapoints_by_sample_task_epoch[key] = []
                datapoints_by_sample_task_epoch[key].append(dp)

            # Count total pairs to compute
            nonlocal num_total
            for datapoint_lists in datapoints_by_sample_task_epoch.values():
                first_pair_candidates = [
                    dp
                    for dp in datapoint_lists
                    if dp.metadata.get("experiment_id") == experiment_id_1
                ]
                second_pair_candidates = [
                    dp
                    for dp in datapoint_lists
                    if dp.metadata.get("experiment_id") == experiment_id_2
                ]
                if len(first_pair_candidates) > 0 and len(second_pair_candidates) > 0:
                    num_total += 1

            # Send initial 0% state message
            init_data = StreamedDiffs(
                num_pairs_done=0,
                num_pairs_total=num_total,
                transcript_diff=None,
            )
            await send_stream.send(init_data)

            # Compute diffs
            await db.compute_diffs(ctx, diffs_report.id, _ws_diff_streaming_callback)

            # Final refresh of state
            await publish_homepage_state(db, ctx)

    return StreamingResponse(
        sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
    )


########################
# Clustering diffs
########################


class ComputeClusteringDiffsRequest(BaseModel):
    diffs_report_id: str


@user_router.post("/{collection_id}/compute_diff_clusters")
async def compute_diff_clusters(
    collection_id: str,
    request: ComputeClusteringDiffsRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    diffs_report = await db.get_diffs_report(request.diffs_report_id)
    claims = [c.to_pydantic() for diff in diffs_report.diffs for c in diff.claims]
    clusters = await db.compute_diff_clusters(
        ctx,
        claims,
    )

    # Track analytics
    await track_endpoint_with_user(db, EndpointType.COMPUTE_DIFF_CLUSTERS, ctx.user, collection_id)

    return clusters


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
#     job_id = await db.add_job(
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
#     job = await db.get_job(job_id)
#     if job is None:
#         raise ValueError(f"Job {job_id} not found")
#     experiment_id_1, experiment_id_2, search_query = (
#         job.job_json["experiment_id_1"],
#         job.job_json["experiment_id_2"],
#         job.job_json["search_query"],
#     )

#     datapoints = await db.get_agent_runs(ctx)
#     expid_by_datapoint = {d.id: d.metadata.get("experiment_id") for d in datapoints}
#     async with db.session() as session:
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
#         async with db.advisory_lock(collection_id, action_id="mutation"):
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
#             await db.compute_diff_search(
#                 ctx,
#                 experiment_id_1,
#                 experiment_id_2,
#                 search_query,
#                 _diff_search_callback,
#             )

#     return StreamingResponse(
#         sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
#     )


@user_router.get("/{collection_id}/transcript_diff")
async def get_transcript_diff(
    agent_run_1_id: str,
    agent_run_2_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    """Get a transcript diff between two agent runs."""
    from sqlalchemy import or_, select

    from docent_core._ai_tools.diffs.models import SQLATranscriptDiff

    # Query for transcript diff in either direction
    async with db.session() as session:
        result = await session.execute(
            select(SQLATranscriptDiff).where(
                or_(
                    and_(
                        SQLATranscriptDiff.agent_run_1_id == agent_run_1_id,
                        SQLATranscriptDiff.agent_run_2_id == agent_run_2_id,
                    ),
                    and_(
                        SQLATranscriptDiff.agent_run_1_id == agent_run_2_id,
                        SQLATranscriptDiff.agent_run_2_id == agent_run_1_id,
                    ),
                )
            )
        )
        transcript_diff = result.scalar_one_or_none()

    if not transcript_diff:
        return None

    # Track analytics
    await track_endpoint_with_user(
        db, EndpointType.GET_TRANSCRIPT_DIFF, ctx.user, ctx.collection_id
    )

    return transcript_diff.to_pydantic().model_dump()
