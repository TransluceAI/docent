from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from docent._log_util import get_logger
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server.util import generator_to_sse_stream
from docent_core.docent.ai_tools.rubric.refine import RUBRIC_UPDATE_TEMPLATE
from docent_core.docent.ai_tools.rubric.rubric import Rubric
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.refinement import SQLARefinementAgentSession
from docent_core.docent.db.schemas.rubric import SQLARubric
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.database import AsyncSession, get_session
from docent_core.docent.server.dependencies.services import (
    get_job_service,
    get_mono_svc,
    get_refinement_service,
    get_rubric_service,
)
from docent_core.docent.server.dependencies.user import get_default_view_ctx, get_user_anonymous_ok
from docent_core.docent.server.rest.rubric import get_rubric
from docent_core.docent.services.job import JobService
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.refinement import RefinementService
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


class CreateRefinementSessionRequest(BaseModel):
    session_type: Literal["guided", "direct"]


class PostRefinementMessageRequest(BaseModel):
    message: str
    show_labels_in_context: bool


@refinement_router.post("/{collection_id}/refinement-session/create/{rubric_id}")
async def create_refinement_session(
    collection_id: str,
    rubric_id: str,
    request: CreateRefinementSessionRequest,
    sq_rubric: SQLARubric = Depends(get_rubric),
    refinement_svc: RefinementService = Depends(get_refinement_service),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    sq_rsession = await refinement_svc.get_or_create_session(sq_rubric, request.session_type)

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
    # Decide whether to start a job or just return the existing session
    rsession = sq_rsession.to_pydantic()
    messages = rsession.messages

    job_id: str | None = None

    # Start a job only if the session is brand new (system-only message)
    if len(messages) == 1 and messages[0].role == "system":
        job_id = await refinement_svc.start_or_get_agent_job(ctx, sq_rsession)
    else:
        # Do not start a job; if one is already active, return its id
        active_job = await refinement_svc.get_active_job_for_session(sq_rsession.id)
        job_id = active_job.id if active_job else None

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


@refinement_router.get("/{collection_id}/refinement-session/{session_id}/job")
async def get_refinement_job(
    collection_id: str,
    session_id: str,
    refinement_svc: RefinementService = Depends(get_refinement_service),
    sq_rsession: SQLARefinementAgentSession = Depends(get_refinement_session),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Return the active refinement job for a session if one exists.
    Does NOT start a new job.
    """
    active_job = await refinement_svc.get_active_job_for_session(session_id)

    analytics.track_event(
        "refinement_session_get_job",
        properties={
            "collection_id": collection_id,
            "rubric_id": sq_rsession.rubric_id,
            "refinement_session_id": sq_rsession.id,
            "has_active_job": active_job is not None,
        },
    )

    return {
        "session_id": sq_rsession.id,
        "rubric_id": sq_rsession.rubric_id,
        "job_id": active_job.id if active_job else None,
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
    request: PostRefinementMessageRequest,
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
    await refinement_svc.add_user_message(sq_rsession, request.message)
    await session.commit()

    # Track analytics for message post
    analytics.track_event(
        "refinement_post_message",
        properties={
            "collection_id": ctx.collection_id,
            "session_id": session_id,
            "rubric_id": sq_rsession.rubric_id,
            "message": request.message,
        },
    )

    # Trigger a new turn of the agent
    job_id = await refinement_svc.start_or_get_agent_job(
        ctx, sq_rsession, show_labels_in_context=request.show_labels_in_context
    )
    return {"job_id": job_id, "rsession": sq_rsession.to_pydantic().prepare_for_client()}


@refinement_router.post("/{collection_id}/refinement-session/{session_id}/retry-last-message")
async def retry_last_message(
    collection_id: str,
    session_id: str,
    refinement_svc: RefinementService = Depends(get_refinement_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    sq_rsession: SQLARefinementAgentSession = Depends(get_refinement_session),
):
    # Return the active job id if one exists
    active_job = await refinement_svc.get_active_job_for_session(session_id)
    if active_job is not None:
        return {"job_id": active_job.id, "rsession": sq_rsession.to_pydantic().prepare_for_client()}

    # Prepare session state for retry inside the service
    job_id = await refinement_svc.start_or_get_agent_job(ctx, sq_rsession)
    return {"job_id": job_id, "rsession": sq_rsession.to_pydantic().prepare_for_client()}


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

    message = RUBRIC_UPDATE_TEMPLATE.format(
        previous_version=rubric.version - 1,
        new_version=rubric.version,
        rubric=rubric.rubric_text,
        output_schema=rubric.output_schema,
    )
    await refinement_svc.add_user_message(
        sq_rsession,
        message,
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
    return {"job_id": job_id, "rsession": sq_rsession.to_pydantic().prepare_for_client()}


@refinement_router.post("/{collection_id}/refinement-session/{session_id}/cancel")
async def cancel_active_refinement_message(
    collection_id: str,
    session_id: str,
    refinement_svc: RefinementService = Depends(get_refinement_service),
    job_svc: JobService = Depends(get_job_service),
):
    """Cancel a pending or active refinement job for a session (if any)"""
    # Try to cancel any running job for this session
    active_job = await refinement_svc.get_active_job_for_session(session_id)
    if active_job is not None:
        await job_svc.cancel_job(active_job.id)

    return {"message": "Job cancelled successfully"}


@refinement_router.get("/{collection_id}/refinement-session/{session_id}/state")
async def get_current_state_endpoint(
    sq_rsession: SQLARefinementAgentSession = Depends(get_refinement_session),
    refinement_svc: RefinementService = Depends(get_refinement_service),
):
    state = await refinement_svc.get_current_state(sq_rsession)
    return state.prepare_for_client()
