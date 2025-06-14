import asyncio
import hashlib
import json
from functools import partial
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.inspection import inspect as sqla_inspect

from docent._ai_tools.search import SearchResult, SearchResultWithCitations
from docent._db_service.contexts import ViewContext
from docent._db_service.schemas.auth_models import Permission, ResourceType, User
from docent._db_service.schemas.tables import SQLADiffAttribute
from docent._db_service.service import DBService
from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.prod_llms import get_llm_completions_async
from docent._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent._log_util.logger import get_logger
from docent._server._assistant.chat import make_single_tasst_system_prompt

# from docent._server._assistant.feedback import generate_new_queries
from docent._server._assistant.summarizer import (
    HighLevelAction,
    LowLevelAction,
    ObservationType,
    group_actions_into_high_level_steps,
    interesting_agent_observations,
    summarize_agent_actions,
)
from docent._server._auth.session import create_user_session, invalidate_user_session
from docent._server._broker.redis_client import REDIS, enqueue_search_job, publish_to_broker
from docent._server._dependencies.database import get_db
from docent._server._dependencies.permissions import require_fg_permission, require_view_permission
from docent._server._dependencies.user import get_default_view_ctx, get_user_anonymous_ok
from docent._server._rest.send_state import (
    publish_dims,
    publish_framegrids,
    publish_homepage_state,
    publish_marginals,
    publish_searches,
)
from docent._server.util import sse_event_stream
from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import (
    Citation,
    parse_citations_single_run,
)
from docent.data_models.filters import ComplexFilter, FrameDimension, FrameFilter, parse_filter_dict
from docent.data_models.regex import RegexSnippet, get_regex_snippets

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

    user = await db.create_user(request.email)

    # Create a session for the new user
    await create_user_session(user.id, response)

    return user


class LoginRequest(BaseModel):
    email: str


@public_router.post("/login")
async def login(request: LoginRequest, response: Response, db: DBService = Depends(get_db)):
    """
    User login endpoint. Authenticates a user and creates a session.

    Args:
        request: LoginRequest containing email
        response: FastAPI Response object to set cookies
        db: Database service dependency

    Returns:
        UserResponse with user_id and email
    """
    user = await db.get_user_by_email(request.email)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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


#############
# Framegrid #
#############


@user_router.get("/framegrids")
async def get_framegrids(db: DBService = Depends(get_db)):
    sqla_fgs = await db.get_fgs()
    return [
        # Get all columns from the SQLAlchemy object
        {c.key: getattr(obj, c.key) for c in sqla_inspect(obj).mapper.column_attrs}
        for obj in sqla_fgs
    ]


class CreateFrameGridRequest(BaseModel):
    fg_id: str | None = None
    name: str | None = None
    description: str | None = None


@user_router.post("/create")
async def create_fg(
    request: CreateFrameGridRequest = CreateFrameGridRequest(),
    user: User = Depends(get_user_anonymous_ok),
    db: DBService = Depends(get_db),
):
    fg_id = await db.create_fg(
        user=user, fg_id=request.fg_id, name=request.name, description=request.description
    )
    # Publish updated framegrids list to all clients
    await publish_framegrids(db)
    return {"fg_id": fg_id}


class UpdateFrameGridRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@user_router.put("/{fg_id}/framegrid")
async def update_framegrid(
    fg_id: str,
    request: UpdateFrameGridRequest,
    db: DBService = Depends(get_db),
    _: None = Depends(require_fg_permission(Permission.WRITE)),
):
    await db.update_framegrid(fg_id, name=request.name, description=request.description)

    # Publish updated framegrids list to all clients
    await publish_framegrids(db)

    return {"fg_id": fg_id}


@user_router.delete("/{fg_id}/framegrid")
async def delete_framegrid(
    fg_id: str,
    db: DBService = Depends(get_db),
    _: None = Depends(require_fg_permission(Permission.ADMIN)),
):
    await db.delete_fg(fg_id)
    # Notify about the specific deleted framegrid
    await publish_to_broker(
        None,  # Broadcast to all connections
        {
            "action": "framegrid_deleted",
            "payload": {"fg_id": fg_id},
        },
    )
    # Also publish the updated list of framegrids
    await publish_framegrids(db)
    return {"status": "success", "fg_id": fg_id}


##############
# Agent runs #
##############


@user_router.get("/{fg_id}/agent_run_metadata_fields")
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


@user_router.get("/{fg_id}/agent_run")
async def get_agent_run(
    agent_run_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    return await db.get_agent_run(ctx, agent_run_id)


class AgentRunMetadataRequest(BaseModel):
    agent_run_ids: list[str]


@user_router.post("/{fg_id}/agent_run_metadata")
async def get_agent_run_metadata(
    request: AgentRunMetadataRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    data = await db.get_agent_runs(ctx, agent_run_ids=request.agent_run_ids)
    return {d.id: d.metadata for d in data}


class PostAgentRunsRequest(BaseModel):
    agent_runs: list[AgentRun]


@user_router.post("/{fg_id}/agent_runs")
async def post_agent_runs(
    fg_id: str,
    request: PostAgentRunsRequest,
    db: DBService = Depends(get_db),
    _: None = Depends(require_fg_permission(Permission.WRITE)),
):
    async with db.advisory_lock(fg_id, action_id="mutation"):
        await db.add_agent_runs(fg_id, request.agent_runs)

        # Publish state of ALL views
        for ctx in await db.get_all_view_ctxs(fg_id):
            await publish_homepage_state(db, ctx)


########
# View #
########


@user_router.post("/{fg_id}/join")
async def join(
    fg_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    if not await db.exists(fg_id):
        raise HTTPException(status_code=404, detail=f"Frame grid with ID {fg_id} not found")

    return {"fg_id": fg_id, "view_id": ctx.view_id}


class SetIODimsRequest(BaseModel):
    inner_dim_id: str | None = None
    outer_dim_id: str | None = None


@user_router.post("/{fg_id}/io_dims")
async def set_io_dims_endpoint(
    fg_id: str,
    request: SetIODimsRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with db.advisory_lock(fg_id, action_id="mutation"):
        await db.set_io_dims(ctx, request.inner_dim_id, request.outer_dim_id)
        await publish_homepage_state(db, ctx)


class SetIODimWithMetadataKeyRequest(BaseModel):
    metadata_key: str
    type: Literal["inner", "outer"]


@user_router.post("/{fg_id}/io_dims_with_metadata_key")
async def set_io_dim_with_metadata_key_endpoint(
    fg_id: str,
    request: SetIODimWithMetadataKeyRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with db.advisory_lock(fg_id, action_id="mutation"):
        await db.set_io_dim_with_metadata_key(ctx, request.metadata_key, request.type)
        await publish_homepage_state(db, ctx)


class PostBaseFilterRequest(BaseModel):
    filter: ComplexFilter | None


@user_router.post("/{fg_id}/base_filter")
async def post_base_filter(
    fg_id: str,
    request: PostBaseFilterRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with db.advisory_lock(fg_id, action_id="mutation"):
        if request.filter is None:
            new_ctx = await db.clear_view_base_filter(ctx)
        else:
            new_ctx = await db.set_view_base_filter(ctx, request.filter)

        # Use the updated context
        await publish_homepage_state(db, new_ctx)

        return request.filter.id if request.filter else None


@user_router.get("/{fg_id}/base_filter")
async def get_base_filter_endpoint(
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    return ctx.base_filter


class GetRegexSnippetsRequest(BaseModel):
    filter_id: str
    agent_run_ids: list[str]


@user_router.post("/{fg_id}/get_regex_snippets")
async def get_regex_snippets_endpoint(
    request: GetRegexSnippetsRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
) -> dict[str, list[RegexSnippet]]:
    filter_id = request.filter_id

    # Get filter object
    filter = await db.get_filter(filter_id)
    if filter is None:
        raise ValueError(f"Filter {filter_id} is not found")

    # Collect all patterns from the filter
    patterns: list[str] = []
    if filter.type == "primitive" and filter.op == "~*":
        patterns.append(str(filter.value))
    elif filter.type == "complex":

        # Recursively search for all primitive filters
        def _search(f: FrameFilter):
            if f.type == "primitive" and f.op == "~*":
                patterns.append(str(f.value))
            elif f.type == "complex":
                for child in f.filters:
                    _search(child)

        _search(filter)

    if not patterns:
        return {}

    agent_runs = await db.get_agent_runs(ctx, agent_run_ids=request.agent_run_ids)
    return {
        d.id: [item for p in patterns for item in get_regex_snippets(d.text, p)] for d in agent_runs
    }


@user_router.get("/{fg_id}/state")
async def get_state(
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    await publish_homepage_state(db, ctx)


@user_router.get("/{fg_id}/searches")
async def get_searches(
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    # The service method returns a list of dicts, which is fine for JSON response
    return await db.get_searches_with_result_counts(ctx)


@user_router.delete("/{fg_id}/search")
async def delete_search(
    fg_id: str,
    search_query_id: str,
    db: DBService = Depends(get_db),
    _: None = Depends(require_fg_permission(Permission.WRITE)),
):
    await db.delete_search_query(fg_id, search_query_id)

    # Publish updated searches state to all views in this framegrid
    for ctx in await db.get_all_view_ctxs(fg_id):
        await publish_searches(db, ctx)

    return {"status": "success", "search_query_id": search_query_id}


class UserPermissionsResponse(BaseModel):
    framegrid_permissions: dict[str, str | None]
    view_permissions: dict[str, str | None]


@user_router.get("/{fg_id}/permissions")
async def get_user_permissions(
    fg_id: str,
    user: User = Depends(get_user_anonymous_ok),
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_fg_permission(Permission.READ)),
):
    fg_permission = await db.get_permission_level(
        user=user,
        resource_type=ResourceType.FRAME_GRID,
        resource_id=fg_id,
    )

    view_permission = await db.get_permission_level(
        user=user,
        resource_type=ResourceType.VIEW,
        resource_id=ctx.view_id,
    )

    return UserPermissionsResponse(
        framegrid_permissions={fg_id: fg_permission.value if fg_permission else None},
        view_permissions={ctx.view_id: view_permission.value if view_permission else None},
    )


##################################
# (View-specific) dims + filters #
##################################


class PostDimensionRequest(BaseModel):
    dim: FrameDimension


@user_router.post("/{fg_id}/dimension")
async def post_dimension(
    request: PostDimensionRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    await db.upsert_dim(ctx, request.dim)

    await publish_dims(db, ctx)
    await publish_searches(db, ctx)

    return request.dim.id


class GetDimensionsRequest(BaseModel):
    dim_ids: list[str] | None = None


@user_router.post("/{fg_id}/get_dimensions")
async def get_dimensions(
    request: GetDimensionsRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    if request.dim_ids is None:
        return await db.get_view_dims(ctx)
    else:
        return await db.get_dims(request.dim_ids)


@user_router.delete("/{fg_id}/dimension")
async def delete_dimension(
    fg_id: str,
    dim_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with db.advisory_lock(fg_id, action_id="mutation"):
        await db.delete_dimension(dim_id)
        await publish_dims(db, ctx)

        # TODO: This is a framegrid-wide operation that affects all views.
        # We should either:
        # 1. Make publish_attribute_searches framegrid-wide (not view-specific), OR
        # 2. Publish to all views in this framegrid
        # For now, using the authenticated user's ViewProvider.
        await publish_searches(db, ctx)


@user_router.delete("/{fg_id}/filter")
async def delete_filter(
    fg_id: str,
    dim_id: str,
    filter_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with db.advisory_lock(fg_id, action_id="mutation"):
        await db.delete_filter(filter_id)
        await publish_dims(db, ctx)
        await publish_marginals(db, ctx, dim_ids=[dim_id], ensure_fresh=True)


class PostFilterRequest(BaseModel):
    dim_id: str | None = None
    filter_id: str
    new_predicate: str


@user_router.post("/{fg_id}/filter")
async def post_filter(
    fg_id: str,
    request: PostFilterRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    async with db.advisory_lock(fg_id, action_id="mutation"):
        old_filter = await db.get_filter(request.filter_id)
        if old_filter is None:
            raise ValueError(f"Filter {request.filter_id} not found")

        # Push filter (takes care of clearing related judgments)
        new_filter = old_filter.model_copy(
            update={"name": request.new_predicate, "predicate": request.new_predicate}
        )
        await db.set_filter(request.filter_id, new_filter)

        # If the filter is part of a dimension, we need to publish the marginals for that dimension
        if request.dim_id:
            # Publish the initial marginals (without recompute) which should be empty for the new filter
            # Otherwise the frontend will show the old filter's marginals
            await publish_marginals(
                db,
                ctx,
                dim_ids=[request.dim_id],
                ensure_fresh=False,
            )
            await publish_dims(db, ctx)
            await publish_marginals(db, ctx, dim_ids=[request.dim_id], ensure_fresh=True)

        return new_filter.id


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


class ComputeSearchRequest(BaseModel):
    search_query: str


@user_router.post("/{fg_id}/start_compute_search")
async def start_compute_search(
    fg_id: str,
    request: ComputeSearchRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_fg_permission(Permission.WRITE)),
):
    query_id = await db.add_search_query(ctx, request.search_query)
    new, job_id = await db.add_search_job(query_id)
    if new:
        await enqueue_search_job(ctx, job_id)
    return job_id


@user_router.get("/{fg_id}/listen_compute_search")
async def listen_compute_search(
    fg_id: str,
    job_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
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
    num_done, num_total = 0, await db.count_base_agent_runs(ctx)

    async def _execute():
        # Send initial 0% state message
        init_data = StreamedSearchResult(
            data_dict={},
            num_agent_runs_done=0,
            num_agent_runs_total=num_total,
        )
        await send_stream.send(init_data)
        nonlocal num_done, num_errors

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
                    )

                    # Send to event_stream so it can be sent back to the client
                    await send_stream.send(payload)

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
):
    new, job_id = await db.add_search_job(query_id)
    query = await db.get_search_query(query_id)
    ctx = await get_default_view_ctx(query.fg_id, db)
    if new:
        await enqueue_search_job(ctx, job_id)
    return job_id


@user_router.get("/search_jobs")
async def search_jobs(
    db: DBService = Depends(get_db),
):
    jobs = await db.list_search_jobs_and_queries()
    for job in jobs:
        print("-", job)
    return [[job.dict(), query.dict()] for job, query in jobs]


class ClusterDimensionRequest(BaseModel):
    dim_id: str
    feedback: str | None


@user_router.post("/{fg_id}/start_cluster_dimension")
async def start_cluster_dimension(
    fg_id: str,
    request: ClusterDimensionRequest,
    db: DBService = Depends(get_db),
    _: None = Depends(require_fg_permission(Permission.WRITE)),
):
    job_id = await db.add_job(
        "cluster_dimension",
        {
            "fg_id": fg_id,
            "dim_id": request.dim_id,
            "feedback": request.feedback,
        },
    )
    return job_id


@user_router.get("/{fg_id}/listen_cluster_dimension")
async def listen_cluster_dimension(
    fg_id: str,
    job_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.WRITE)),
):
    """[Setter] Create clusters for a dimension."""
    # Retrieve job arguments
    job = await db.get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    job = job.job_json
    fg_id, dim_id, feedback = job["fg_id"], job["dim_id"], job.get("feedback")

    dim = await db.get_dim(dim_id)
    if dim is None:
        raise ValueError(f"Dimension {dim_id} not found")

    if feedback:
        raise NotImplementedError("Feedback not implemented")

    async def event_stream():
        async with db.advisory_lock(fg_id, action_id="mutation"):
            try:
                # Send new dim state indicating that clusters are being loaded
                await db.set_dim_loading_state(dim_id, loading_clusters=True)
                await publish_dims(db, ctx)

                # TODO(mengk): assert that all agent_runs have the associated attribute
                # This should be guaranteed by the frontend, but just make sure.

                await db.cluster_search_results(ctx, dim_id)

                # Upload loading state and send updated bins
                await db.set_dim_loading_state(
                    dim_id, loading_clusters=False, loading_marginals=True
                )
                await publish_dims(db, ctx)

                # Compute marginals while sending them to the client
                async with anyio.create_task_group() as tg:
                    is_done = False

                    async def _run():
                        nonlocal is_done
                        await publish_marginals(
                            db, ctx, dim_ids=[dim_id], ensure_fresh=True
                        )  # `ensure_fresh=True` will force computation of the filters
                        is_done = True

                    # Compute state in the background
                    tg.start_soon(_run)

                    # At the same time, poll to send state
                    while not is_done:
                        await publish_marginals(db, ctx, dim_ids=[dim_id], ensure_fresh=False)
                        await anyio.sleep(1)

                yield "data: [DONE]\n\n"

            except anyio.get_cancelled_exc_class():
                logger.info("Cluster dimension task cancelled")

            finally:
                with anyio.CancelScope(shield=True):
                    # Publish latest marginals in case there was an update
                    await publish_marginals(db, ctx, dim_ids=[dim_id], ensure_fresh=False)

                    # Update loading state to show current state
                    await db.set_dim_loading_state(
                        dim_id, loading_clusters=False, loading_marginals=False
                    )
                    await publish_dims(db, ctx)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


#######################
# Agent run summaries #
#######################


@user_router.get("/{fg_id}/actions_summary")
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


# @user_router.get("/{fg_id}/solution_summary")
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
    base_filter: dict[str, Any] | None


class TaChatMessage(TypedDict):
    role: str
    content: str
    citations: list[Citation]


class TASession(BaseModel):
    id: str
    messages: list[TaChatMessage]
    agent_run_ids: list[str]


TA_SESSIONS: dict[str, TASession] = {}  # session_id -> TASession


@user_router.post("/{fg_id}/ta_session")
async def create_ta_session(
    request: CreateTASessionRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    base_filter_raw = request.base_filter
    base_filter = parse_filter_dict(base_filter_raw) if base_filter_raw else None

    agent_runs = await db.get_agent_runs(ctx)
    if not agent_runs:
        raise ValueError("No matching agent runs found")

    if base_filter:
        judgments = await base_filter.apply(agent_runs=agent_runs, return_all=False)
        if len(judgments) > 1:
            raise ValueError("Multiple agent runs found for TA session")
        elif len(judgments) == 0:
            raise ValueError("No agent runs found for TA session")
        agent_runs = [d for d in agent_runs if d.id == judgments[0].agent_run_id]

    # Create system prompt with all matching transcripts
    system_prompt = make_single_tasst_system_prompt(agent_runs[0])

    # Generate session ID and store session
    session_id = str(uuid4())
    TA_SESSIONS[session_id] = TASession(
        id=session_id,
        messages=[{"role": "system", "content": system_prompt, "citations": []}],
        agent_run_ids=[agent_run.id for agent_run in agent_runs],
    )

    return {
        "session_id": session_id,
        "num_transcripts": len(agent_runs),
    }


@user_router.get("/{fg_id}/ta_message")
async def get_ta_message(
    session_id: str,
    message: str,
    _: None = Depends(require_view_permission(Permission.READ)),
):
    session = TA_SESSIONS[session_id]
    # api_keys = cm.get_api_keys(fg_id)

    # Add user message to session
    prompt_msgs = session.messages + [{"role": "user", "content": message, "citations": []}]
    continuation_text = ""

    # AnyIO queue that we can write intermediate results to
    send_stream, recv_stream = anyio.create_memory_object_stream[dict[str, Any]](
        max_buffer_size=100_000
    )

    def _get_complete_message_list():
        nonlocal continuation_text
        current_assistant_message: TaChatMessage = {
            "role": "assistant",
            "content": continuation_text,
            "citations": parse_citations_single_run(continuation_text),
        }
        return prompt_msgs + [current_assistant_message]

    async def _send_state():
        nonlocal prompt_msgs, continuation_text
        await send_stream.send(
            {
                "text": continuation_text,
                "messages": _get_complete_message_list(),
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
        session.messages = _get_complete_message_list()

        # Close the stream
        await recv_stream.aclose()

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


@user_router.get("/{fg_id}/diffs_reports/{diffs_report_id}")
async def get_diffs_report(
    diffs_report_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    report = await db.get_diffs_report(diffs_report_id)
    print(report)
    return report.to_pydantic().model_dump()


@user_router.post("/{fg_id}/start_compute_diffs")
async def start_compute_diffs(
    fg_id: str,
    request: ComputeDiffRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
):
    from docent._ai_tools.diffs.models import SQLADiffsReport

    # Check if a report already exists for these experiment IDs
    # FIXME(mengk): SQL should not be in the router
    async with db.session() as session:
        existing_report = (
            await session.execute(
                select(SQLADiffsReport).where(
                    SQLADiffsReport.experiment_id_1 == request.experiment_id_1,
                    SQLADiffsReport.experiment_id_2 == request.experiment_id_2,
                    SQLADiffsReport.frame_grid_id == fg_id,
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
        frame_grid_id=fg_id,
        name=f"{request.experiment_id_1} vs {request.experiment_id_2}",
        experiment_id_1=request.experiment_id_1,
        experiment_id_2=request.experiment_id_2,
    )
    async with db.session() as session:
        session.add(report)
    job_id = await db.add_job(
        "compute_diffs",
        {
            "fg_id": fg_id,
            "diffs_report_id": report.id,
        },
    )

    logger.info("New Diff Report", report.id)
    return {
        "job_id": job_id,
        "diffs_report_id": report.id,
    }


@user_router.get("/{fg_id}/listen_compute_diffs")
async def listen_compute_diffs(
    fg_id: str,
    job_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
):
    from sqlalchemy import select

    from docent._ai_tools.diffs.models import SQLADiffsReport

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

    from docent._ai_tools.diffs.models import TranscriptDiff

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
        async with db.advisory_lock(fg_id, action_id="mutation"):
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
            print("COMPUTING DIFFS", experiment_id_1, experiment_id_2)
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


@user_router.post("/{fg_id}/compute_diff_clusters")
async def compute_diff_clusters(
    fg_id: str,
    request: ComputeClusteringDiffsRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_fg_permission(Permission.WRITE)),
):
    print("hello world")
    diffs_report = await db.get_diffs_report(request.diffs_report_id)
    claims = [c.to_pydantic() for diff in diffs_report.diffs for c in diff.claims]
    clusters = await db.compute_diff_clusters(
        ctx,
        claims,
    )
    return clusters


class ComputeDiffSearchRequest(BaseModel):
    experiment_id_1: str
    experiment_id_2: str
    search_query: str


@user_router.post("/{fg_id}/start_compute_diff_search")
async def start_compute_diff_search(
    fg_id: str,
    request: ComputeDiffSearchRequest,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
):
    job_id = await db.add_job(
        "diff",
        {
            "type": "compute_diff_search",
            "fg_id": fg_id,
            "experiment_id_1": request.experiment_id_1,
            "experiment_id_2": request.experiment_id_2,
            "search_query": request.search_query,
        },
    )
    return job_id


@user_router.get("/{fg_id}/listen_compute_diff_search")
async def listen_compute_diff_search(
    fg_id: str,
    job_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_fg_permission(Permission.WRITE)),
):
    # Retrieve job arguments
    job = await db.get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    experiment_id_1, experiment_id_2, search_query = (
        job.job_json["experiment_id_1"],
        job.job_json["experiment_id_2"],
        job.job_json["search_query"],
    )

    datapoints = await db.get_agent_runs(ctx)
    expid_by_datapoint = {d.id: d.metadata.get("experiment_id") for d in datapoints}
    async with db.session() as session:
        result = await session.execute(
            select(SQLADiffAttribute)
            .where(
                SQLADiffAttribute.frame_grid_id == ctx.fg_id,
            )
            .order_by(SQLADiffAttribute.id)
        )
        existing_diffs = result.scalars().all()
        num_total = sum(
            1
            for d in existing_diffs
            if expid_by_datapoint.get(d.data_id_1) == experiment_id_1
            and expid_by_datapoint.get(d.data_id_2) == experiment_id_2
        )

    # Create AnyIO queue that we can write intermediate results to
    send_stream, recv_stream = anyio.create_memory_object_stream[StreamedDiffSearchResult](
        max_buffer_size=100_000
    )

    # Track intermediate progress
    progress_lock = anyio.Lock()
    num_done = 0

    async def _diff_search_callback(search_result: tuple[str, int]) -> None:
        nonlocal num_done

        async with progress_lock:
            num_done += 1
            payload = StreamedDiffSearchResult(
                claim=search_result[0],
                alignment=search_result[1],
                query=search_query,
                num_results_done=num_done,
                num_results_total=num_total,
            )

        # Send to event_stream so it can be sent back to the client
        await send_stream.send(payload)

        if num_done == num_total:
            # Terminate the stream so the event_stream stops waiting
            await asyncio.sleep(1)
            await send_stream.aclose()

    async def _execute():
        nonlocal num_total
        async with db.advisory_lock(fg_id, action_id="mutation"):
            # Send initial 0% state message
            init_data = StreamedDiffSearchResult(
                claim=None,
                alignment=0,
                query=search_query,
                num_results_done=0,
                num_results_total=num_total,
            )
            await send_stream.send(init_data)

            # Get all diff search results
            await db.compute_diff_search(
                ctx,
                experiment_id_1,
                experiment_id_2,
                search_query,
                _diff_search_callback,
            )

    return StreamingResponse(
        sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
    )


@user_router.get("/{fg_id}/transcript_diff")
async def get_transcript_diff(
    agent_run_1_id: str,
    agent_run_2_id: str,
    db: DBService = Depends(get_db),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
):
    """Get a transcript diff between two agent runs."""
    from sqlalchemy import or_, select

    from docent._ai_tools.diffs.models import SQLATranscriptDiff

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

    return transcript_diff.to_pydantic().model_dump()
