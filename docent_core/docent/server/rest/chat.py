from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from docent._llm_util.providers.preference_types import (
    ModelOption,
    ModelOptionWithContext,
    merge_models_with_byok,
)
from docent._log_util import get_logger
from docent.data_models.agent_run import SelectionSpec
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server.util import generator_to_sse_stream
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.chat import ChatSession, ChatSessionSummary, SQLAChatSession
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.database import AsyncSession, get_session
from docent_core.docent.server.dependencies.permissions import (
    Permission,
    require_agent_run_in_collection,
    require_collection_permission,
)
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
from docent_core.docent.services.llms import PROVIDER_PREFERENCES
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)

chat_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


################
# Dependencies #
################


async def get_chat_session(
    session_id: str,
    user: User = Depends(get_authenticated_user),
    chat_svc: ChatService = Depends(get_chat_service),
) -> SQLAChatSession:
    sqla_session = await chat_svc.get_session_by_id(session_id)
    if sqla_session is None:
        raise HTTPException(status_code=404, detail=f"Chat session {session_id} not found")
    if sqla_session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this session")
    return sqla_session


async def require_chat_job_ownership(
    job_id: str,
    user: User = Depends(get_user_anonymous_ok),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Validate that the chat job's session belongs to the current user."""
    from sqlalchemy import select

    from docent_core.docent.db.schemas.chat import SQLAChatSession
    from docent_core.docent.db.schemas.tables import SQLAJob

    result = await session.execute(
        select(SQLAJob.id)
        .join(SQLAChatSession, SQLAChatSession.id == SQLAJob.job_json["session_id"].astext)
        .where(SQLAJob.id == job_id)
        .where(SQLAChatSession.user_id == user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


#############
# Endpoints #
#############


@chat_router.post("/{collection_id}/{agent_run_id}/session/get")
async def create_session(
    agent_run_id: str,
    result_id: str | None = None,
    user: User = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
    chat_svc: ChatService = Depends(get_chat_service),
    force_create: bool = False,
    _run: None = Depends(require_agent_run_in_collection),
) -> dict[str, str]:
    """Create a new chat session."""

    # Quick input validation to avoid DB errors for clearly invalid IDs
    if len(agent_run_id) != 36:
        raise HTTPException(status_code=404, detail=f"Invalid agent run ID {agent_run_id}")

    # Create session without rubric or judge result context
    sqla_session = await chat_svc.get_or_create_session(
        user.id, agent_run_id=agent_run_id, judge_result_id=result_id, force_create=force_create
    )

    # Flush now to surface FK violations as 404s instead of later 500s
    try:
        await session.flush()
    except IntegrityError as e:
        # Foreign key violation (Postgres SQLSTATE 23503)
        if getattr(e.orig, "pgcode", None) == "23503":
            raise HTTPException(status_code=404, detail="Agent run or judge result not found")
        raise
    return {"session_id": sqla_session.id}


@chat_router.get("/{collection_id}/{agent_run_id}/job/{job_id}/listen")
async def listen_to_chat_job(
    job_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
    _job: None = Depends(require_chat_job_ownership),
) -> StreamingResponse:
    """Listen to SSE updates for a chat job."""
    return StreamingResponse(
        generator_to_sse_stream(chat_svc.listen_for_job_state(job_id)),
        media_type="text/event-stream",
    )


class PostMessageRequest(BaseModel):
    message: str
    chat_model: ModelOption | None = None


@chat_router.post("/{collection_id}/{agent_run_id}/session/{session_id}/message")
async def post_message_to_chat_session(
    agent_run_id: str,
    session_id: str,
    request: PostMessageRequest,
    chat_svc: ChatService = Depends(get_chat_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    session: AsyncSession = Depends(get_session),
    sq_chat_session: SQLAChatSession = Depends(get_chat_session),
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
        await chat_svc.update_session_chat_model(sq_chat_session, request.chat_model)

    # Add the message to the session
    await chat_svc.add_user_message(sq_chat_session, request.message)
    await session.commit()

    # Track analytics for message post
    analytics.track_event(
        "chat_post_message",
        properties={
            "run_id": agent_run_id,
            "session_id": session_id,
            "judge_result_id": sq_chat_session.judge_result_id,
            "message": request.message,
            "chat_model": request.chat_model,
        },
    )

    # Trigger a new turn of the agent
    job_id = await chat_svc.start_or_get_chat_job(ctx, sq_chat_session)
    return {"job_id": job_id, "session": sq_chat_session.to_pydantic()}


@chat_router.get("/{collection_id}/{agent_run_id}/session/{session_id}/state")
async def get_current_state_endpoint(
    sq_chat_session: SQLAChatSession = Depends(get_chat_session),
    chat_svc: ChatService = Depends(get_chat_service),
    view_ctx: ViewContext = Depends(get_default_view_ctx),
) -> ChatSession:
    return await chat_svc.get_current_state(view_ctx, sq_chat_session)


@chat_router.get("/{collection_id}/{agent_run_id}/session/{session_id}/active-job")
async def get_active_chat_job_for_session(
    session_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
    _sq_chat_session: SQLAChatSession = Depends(get_chat_session),
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


@chat_router.get("/{collection_id}/{agent_run_id}/sessions")
async def get_chat_sessions_for_run(
    collection_id: str,
    agent_run_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
) -> list[ChatSession]:
    """Get all chat sessions for an agent run, excluding judge result sessions."""
    return await chat_svc.get_chat_sessions_for_run(collection_id, agent_run_id)


class CreateCollectionConversationRequest(BaseModel):
    context_serialized: dict[str, Any] | None = None
    chat_model: ModelOption | None = None


@chat_router.get("/{collection_id}/chats")
async def list_collection_conversations(
    collection_id: str,
    user: User = Depends(get_authenticated_user),
    chat_svc: ChatService = Depends(get_chat_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
) -> list[ChatSessionSummary]:
    """List conversation-style chat sessions for a collection owned by the current user."""
    return await chat_svc.get_conversation_summaries_for_collection(user.id, collection_id)


@chat_router.post("/{collection_id}/chats")
async def create_collection_conversation(
    collection_id: str,
    request: CreateCollectionConversationRequest,
    user: User = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
    chat_svc: ChatService = Depends(get_chat_service),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
) -> dict[str, str]:
    context_serialized = request.context_serialized or {}
    sqla_session = await chat_svc.create_conversation_session(
        user.id,
        context_serialized=context_serialized,
        chat_model=request.chat_model,
        collection_id=collection_id,
    )
    await session.commit()

    analytics.track_event(
        "conversation_created",
        properties={
            "session_id": sqla_session.id,
            "collection_id": collection_id,
            "num_items": (len(context_serialized.get("root_items", []))),
            "chat_model": request.chat_model.model_dump() if request.chat_model else None,
        },
    )

    return {"session_id": sqla_session.id}


class CreateConversationRequest(BaseModel):
    context_serialized: dict[str, Any]
    model_string: str | None = None
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None


@chat_router.post("/start")
async def create_conversation(
    request: CreateConversationRequest,
    user: User = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
) -> dict[str, str]:
    """Create a new chat session with multiple objects via LLMContext.

    This endpoint creates a multi-object chat session for the "chat with anything" feature.
    Unlike the single-run chat endpoint, this accepts a serialized LLMContext containing
    multiple agent runs, transcripts, or other objects.
    """

    chat_model: ModelOption | None = None
    if request.model_string is not None:
        provider, model_name = request.model_string.split("/", 1)
        chat_model = ModelOption(
            provider=provider,
            model_name=model_name,
            reasoning_effort=request.reasoning_effort,
        )

    sqla_session = SQLAChatSession(
        id=str(uuid4()),
        user_id=user.id,
        agent_run_id=None,
        judge_result_id=None,
        context_serialized=request.context_serialized,
        messages=[],
        chat_model=chat_model.model_dump() if chat_model else None,
    )
    session.add(sqla_session)
    await session.commit()

    # Track analytics
    analytics.track_event(
        "conversation_created",
        properties={
            "session_id": sqla_session.id,
            "num_items": len(request.context_serialized.get("root_items", [])),
            "chat_model": chat_model.model_dump() if chat_model else None,
        },
    )

    return {"session_id": sqla_session.id}


@chat_router.get("/conversation/{session_id}/state")
async def get_conversation_state(
    sq_chat_session: SQLAChatSession = Depends(get_chat_session),
    chat_svc: ChatService = Depends(get_chat_service),
) -> ChatSession:
    """Get the current state of a conversation chat session."""
    return await chat_svc.get_current_state(None, sq_chat_session)


class ContextLookupResponse(BaseModel):
    item_id: str
    item_type: str
    collection_id: str


@chat_router.get("/conversation/lookup/{item_id}")
async def lookup_conversation_item(
    item_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
    mono_svc: MonoService = Depends(get_mono_svc),
    user: User = Depends(get_authenticated_user),
) -> ContextLookupResponse:
    lookup = await chat_svc.lookup_context_item(item_id)
    if lookup is None:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
    await require_collection_permission(Permission.READ)(lookup.collection_id, user, mono_svc)
    return ContextLookupResponse(
        item_id=item_id, item_type=lookup.type, collection_id=lookup.collection_id
    )


class AddContextItemRequest(BaseModel):
    item_id: str


@chat_router.post("/conversation/{session_id}/context")
async def add_conversation_context_item(
    session_id: str,
    request: AddContextItemRequest,
    chat_svc: ChatService = Depends(get_chat_service),
    session: AsyncSession = Depends(get_session),
    sq_chat_session: SQLAChatSession = Depends(get_chat_session),
) -> ChatSession:
    if sq_chat_session.context_serialized is None:
        raise HTTPException(status_code=400, detail="Session has no context to modify")

    try:
        updated = await chat_svc.add_context_item(sq_chat_session, request.item_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await session.commit()
    return updated


@chat_router.delete("/conversation/{session_id}/context/{item_id}")
async def remove_conversation_context_item(
    session_id: str,
    item_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
    session: AsyncSession = Depends(get_session),
    sq_chat_session: SQLAChatSession = Depends(get_chat_session),
) -> ChatSession:
    if sq_chat_session.context_serialized is None:
        raise HTTPException(status_code=400, detail="Session has no context to modify")

    try:
        updated = await chat_svc.remove_context_item(sq_chat_session, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await session.commit()
    return updated


class UpdateContextSelectionRequest(BaseModel):
    selection_spec: dict[str, Any] | None = None
    visible: bool | None = None


@chat_router.patch("/conversation/{session_id}/context/{item_id}")
async def update_conversation_context_selection(
    item_id: str,
    request: UpdateContextSelectionRequest,
    chat_svc: ChatService = Depends(get_chat_service),
    session: AsyncSession = Depends(get_session),
    sq_chat_session: SQLAChatSession = Depends(get_chat_session),
) -> ChatSession:
    if sq_chat_session.context_serialized is None:
        raise HTTPException(status_code=400, detail="Session has no context to modify")

    if request.selection_spec is None and request.visible is None:
        raise HTTPException(status_code=400, detail="No updates provided")

    selection_spec = None
    if request.selection_spec is not None:
        selection_spec = SelectionSpec.model_validate(request.selection_spec)

    try:
        updated = await chat_svc.update_context_item(
            sq_chat_session, item_id, selection_spec, request.visible
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await session.commit()
    return updated


@chat_router.get("/conversation/{session_id}/active-job")
async def get_active_conversation_job(
    session_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
    _sq_chat_session: SQLAChatSession = Depends(get_chat_session),
):
    """Return the active job id for this conversation chat session if one exists, else null."""
    active_job = await chat_svc.get_active_job_for_session(session_id)
    return {"job_id": active_job.id if active_job is not None else None}


@chat_router.get("/conversation/job/{job_id}/listen")
async def listen_to_conversation_job(
    job_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
    _job: None = Depends(require_chat_job_ownership),
) -> StreamingResponse:
    """Listen to SSE updates for a conversation chat job."""
    return StreamingResponse(
        generator_to_sse_stream(chat_svc.listen_for_job_state(job_id)),
        media_type="text/event-stream",
    )


@chat_router.post("/conversation/{session_id}/message")
async def post_message_to_conversation(
    session_id: str,
    request: PostMessageRequest,
    chat_svc: ChatService = Depends(get_chat_service),
    session: AsyncSession = Depends(get_session),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
    sq_chat_session: SQLAChatSession = Depends(get_chat_session),
) -> dict[str, str | ChatSession]:
    """Post a message to a conversation chat session."""
    # Check whether there's an active job for this session
    active_job = await chat_svc.get_active_job_for_session(session_id)
    if active_job is not None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot post message to session {session_id} because there's a job already running",
        )

    # Update the chat model if provided
    if request.chat_model is not None:
        await chat_svc.update_session_chat_model(sq_chat_session, request.chat_model)

    # Add the message to the session
    await chat_svc.add_user_message(sq_chat_session, request.message)
    await session.commit()

    # Track analytics for message post
    analytics.track_event(
        "conversation_post_message",
        properties={
            "session_id": session_id,
            "message": request.message,
            "chat_model": request.chat_model,
        },
    )

    # Trigger a new turn of the agent (no ViewContext needed for multi-object conversations)
    job_id = await chat_svc.start_or_get_chat_job(None, sq_chat_session)
    return {"job_id": job_id, "session": sq_chat_session.to_pydantic()}


@chat_router.delete("/conversation/{session_id}")
async def delete_conversation(
    session_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
    session: AsyncSession = Depends(get_session),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
    sq_chat_session: SQLAChatSession = Depends(get_chat_session),
) -> dict[str, str]:
    """Delete a conversation chat session."""
    await chat_svc.delete_session(sq_chat_session)
    await session.commit()

    analytics.track_event(
        "conversation_deleted",
        properties={
            "session_id": session_id,
            "collection_id": sq_chat_session.collection_id,
        },
    )

    return {"status": "ok"}
