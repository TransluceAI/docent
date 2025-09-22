from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from docent._log_util import get_logger
from docent_core._llm_util.providers.preferences import (
    PROVIDER_PREFERENCES,
    ModelOption,
    ModelOptionWithContext,
    merge_models_with_byok,
)
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server.util import generator_to_sse_stream
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.chat import ChatSession, SQLAChatSession
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.database import AsyncSession, get_session
from docent_core.docent.server.dependencies.services import (
    get_chat_service,
    get_mono_svc,
)
from docent_core.docent.server.dependencies.user import (
    get_authenticated_user,
    get_default_view_ctx,
    get_user_anonymous_ok,
)
from docent_core.docent.services.chat import ChatService
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)

chat_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


################
# Dependencies #
################


async def get_chat_session(
    session_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
):
    sqla_session = await chat_svc.get_session_by_id(session_id)
    if sqla_session is None:
        raise HTTPException(status_code=404, detail=f"Chat session {session_id} not found")
    return sqla_session


#############
# Endpoints #
#############


@chat_router.post("/{collection_id}/{run_id}/session/get")
async def create_session(
    run_id: str,
    result_id: str | None = None,
    user: User = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
    chat_svc: ChatService = Depends(get_chat_service),
    force_create: bool = False,
) -> dict[str, str]:
    """Create a new chat session."""

    # Quick input validation to avoid DB errors for clearly invalid IDs
    if len(run_id) != 36:
        raise HTTPException(status_code=404, detail=f"Invalid agent run ID {run_id}")

    # Create session without rubric or judge result context
    sqla_session = await chat_svc.get_or_create_session(
        user.id, agent_run_id=run_id, judge_result_id=result_id, force_create=force_create
    )

    # Flush now to surface FK violations as 404s instead of later 500s
    try:
        await session.flush()
    except IntegrityError as e:
        # Foreign key violation (Postgres SQLSTATE 23503)
        if getattr(e.orig, "pgcode", None) == "23503":
            raise HTTPException(status_code=404, detail=f"Agent run or judge result not found")
        raise
    return {"session_id": sqla_session.id}


@chat_router.get("/{collection_id}/{run_id}/job/{job_id}/listen")
async def listen_to_chat_job(
    job_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """Listen to SSE updates for a chat job."""
    return StreamingResponse(
        generator_to_sse_stream(chat_svc.listen_for_job_state(job_id)),
        media_type="text/event-stream",
    )


class PostMessageRequest(BaseModel):
    message: str
    chat_model: ModelOption | None = None


@chat_router.post("/{collection_id}/{run_id}/session/{session_id}/message")
async def post_message_to_chat_session(
    run_id: str,
    session_id: str,
    request: PostMessageRequest,
    chat_svc: ChatService = Depends(get_chat_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    session: AsyncSession = Depends(get_session),
    sq_rsession: SQLAChatSession = Depends(get_chat_session),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
) -> dict[str, str | ChatSession]:
    # Check whether there's an active job for this session
    active_job = await chat_svc.get_active_job_for_session(session_id)
    if active_job is not None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot post message to session {session_id} because there's a job already running",
        )

    # Update the chat model if provided
    if request.chat_model is not None:
        await chat_svc.update_session_chat_model(sq_rsession, request.chat_model)

    # Add the message to the session
    await chat_svc.add_user_message(sq_rsession, request.message)
    await session.commit()

    # Track analytics for message post
    analytics.track_event(
        "chat_post_message",
        properties={
            "run_id": run_id,
            "session_id": session_id,
            "judge_result_id": sq_rsession.judge_result_id,
            "message": request.message,
            "chat_model": request.chat_model,
        },
    )

    # Trigger a new turn of the agent
    job_id = await chat_svc.start_or_get_chat_job(ctx, sq_rsession)
    return {"job_id": job_id, "session": sq_rsession.to_pydantic()}


@chat_router.get("/{collection_id}/{run_id}/session/{session_id}/state")
async def get_current_state_endpoint(
    sq_rsession: SQLAChatSession = Depends(get_chat_session),
    chat_svc: ChatService = Depends(get_chat_service),
    view_ctx: ViewContext = Depends(get_default_view_ctx),
) -> ChatSession:
    return await chat_svc.get_current_state(view_ctx, sq_rsession)


@chat_router.get("/{collection_id}/{run_id}/session/{session_id}/active-job")
async def get_active_chat_job_for_session(
    session_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
):
    """Return the active job id for this chat session if one exists, else null."""
    active_job = await chat_svc.get_active_job_for_session(session_id)
    return {"job_id": active_job.id if active_job is not None else None}


@chat_router.get("/chat-models")
async def get_chat_models(
    mono_svc: MonoService = Depends(get_mono_svc),
    user: User = Depends(get_user_anonymous_ok),
) -> list[ModelOptionWithContext]:
    return merge_models_with_byok(
        defaults=PROVIDER_PREFERENCES.default_chat_models,
        byok=PROVIDER_PREFERENCES.byok_chat_models,
        api_keys=await mono_svc.get_api_key_overrides(user),
    )
