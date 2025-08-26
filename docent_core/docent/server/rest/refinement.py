from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from docent._log_util import get_logger
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server.util import generator_to_sse_stream
from docent_core.docent.ai_tools.rubric.rubric import Rubric
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.refinement import SQLARefinementAgentSession
from docent_core.docent.db.schemas.rubric import SQLARubric
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.database import AsyncSession, get_session
from docent_core.docent.server.dependencies.services import (
    get_mono_svc,
    get_refinement_service,
    get_rubric_service,
)
from docent_core.docent.server.dependencies.user import get_default_view_ctx, get_user_anonymous_ok
from docent_core.docent.server.rest.rubric import get_rubric
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.refinement import RefinementService, trim_messages_from_state
from docent_core.docent.services.rubric import RubricService

logger = get_logger(__name__)

refinement_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


################
# Dependencies #
################


async def get_refinement_session(
    session_id: str,
    refinement_svc: RefinementService = Depends(get_refinement_service),
):
    sqla_rsession = await refinement_svc.get_session_by_id(session_id)
    if sqla_rsession is None:
        raise HTTPException(status_code=404, detail=f"Refinement session {session_id} not found")
    return sqla_rsession


#############
# Endpoints #
#############


@refinement_router.post("/{collection_id}/refinement-session/create/{rubric_id}")
async def create_refinement_session(
    sq_rubric: SQLARubric = Depends(get_rubric),
    refinement_svc: RefinementService = Depends(get_refinement_service),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    sq_rsession = await refinement_svc.get_or_create_session(sq_rubric)

    analytics.track_event(
        "refinement_session_created",
        properties={
            "collection_id": sq_rubric.collection_id,
            "rubric_id": sq_rubric.id,
            "rubric_text": sq_rubric.to_pydantic().rubric_text,
        },
    )

    return sq_rsession


@refinement_router.post("/{collection_id}/refinement-session/start/{session_id}")
async def start_refinement_session(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    refinement_svc: RefinementService = Depends(get_refinement_service),
    sq_rsession: SQLARefinementAgentSession = Depends(get_refinement_session),
    ctx: ViewContext = Depends(get_default_view_ctx),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    # Attempt to start a refinement job
    job_id = await refinement_svc.start_or_get_agent_job(ctx, sq_rsession)

    analytics.track_event(
        "refinement_session_started",
        properties={
            "collection_id": collection_id,
            "rubric_id": sq_rsession.rubric_id,
            "refinement_session_id": sq_rsession.id,
        },
    )

    return {
        "session_id": sq_rsession.id,
        "rubric_id": sq_rsession.rubric_id,
        "job_id": job_id,
    }


@refinement_router.get("/{collection_id}/refinement-job/{job_id}/listen")
async def listen_to_refinement_job(
    job_id: str,
    refinement_svc: RefinementService = Depends(get_refinement_service),
):
    return StreamingResponse(
        generator_to_sse_stream(refinement_svc.listen_for_job_state(job_id)),
        media_type="text/event-stream",
    )


@refinement_router.post("/{collection_id}/refinement-session/{session_id}/message")
async def post_message_to_refinement_session(
    session_id: str,
    message: str = Body(..., embed=True),
    refinement_svc: RefinementService = Depends(get_refinement_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    session: AsyncSession = Depends(get_session),
    sq_rsession: SQLARefinementAgentSession = Depends(get_refinement_session),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    # Check whether there's an active job for this session
    active_job = await refinement_svc.get_active_job_for_session(session_id)
    if active_job is not None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot post message to session {session_id} because there's a job already running",
        )

    # Add the message to the session
    await refinement_svc.add_user_message(sq_rsession, message)
    await session.commit()

    # Track analytics for message post
    analytics.track_event(
        "refinement_post_message",
        properties={
            "collection_id": ctx.collection_id,
            "session_id": session_id,
            "rubric_id": sq_rsession.rubric_id,
            "message": message,
        },
    )

    # Trigger a new turn of the agent
    job_id = await refinement_svc.start_or_get_agent_job(ctx, sq_rsession)
    return {"job_id": job_id, "rsession": trim_messages_from_state(sq_rsession.to_pydantic())}


@refinement_router.post("/{collection_id}/refinement-session/{session_id}/rubric-update")
async def post_rubric_update_to_refinement_session(
    session_id: str,
    rubric: Rubric,
    rubric_svc: RubricService = Depends(get_rubric_service),
    refinement_svc: RefinementService = Depends(get_refinement_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    session: AsyncSession = Depends(get_session),
    sq_rsession: SQLARefinementAgentSession = Depends(get_refinement_session),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    # Check whether there's an active job for this session
    active_job = await refinement_svc.get_active_job_for_session(session_id)
    if active_job is not None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot post message to session {session_id} because there's a job already running",
        )

    # Add the rubric version
    await rubric_svc.add_rubric_version(rubric.id, rubric)
    # Update the session's rubric version pointer
    sq_rsession.rubric_version = rubric.version
    # Inform the refinement agent about the change
    await refinement_svc.add_user_message(
        sq_rsession,
        (
            f"The user updated the rubric (now v{rubric.version}) content to:\n\n"
            f"{rubric.rubric_text}"
        ),
    )

    # Commit so the job will see these changes
    await session.commit()

    # Track analytics for rubric update
    analytics.track_event(
        "refinement_rubric_update",
        properties={
            "collection_id": ctx.collection_id,
            "session_id": session_id,
            "rubric_id": rubric.id,
            "text": rubric.rubric_text,
        },
    )

    # Trigger a new turn of the agent
    job_id = await refinement_svc.start_or_get_agent_job(ctx, sq_rsession)
    return {"job_id": job_id, "rsession": trim_messages_from_state(sq_rsession.to_pydantic())}


@refinement_router.get("/{collection_id}/refinement-session/{session_id}/state")
async def get_current_state_endpoint(
    sq_rsession: SQLARefinementAgentSession = Depends(get_refinement_session),
    refinement_svc: RefinementService = Depends(get_refinement_service),
):
    state = await refinement_svc.get_current_state(sq_rsession)
    return state
