import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from docent._log_util import get_logger
from docent.data_models.chat.message import parse_chat_message
from docent_core._ai_tools.refinement.refinement import (
    format_conversation,
    format_conversation_for_client,
)
from docent_core._server._dependencies.database import get_db, get_mono_svc
from docent_core._server._dependencies.services import get_refinement_service
from docent_core._server._dependencies.user import get_user_anonymous_ok
from docent_core.docent.services.monoservice import DocentDB, MonoService
from docent_core.docent.services.rubric import RubricService
from docent_core.services.refinement import RefinementService

logger = get_logger(__name__)

refinement_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


@refinement_router.get("/{collection_id}/get_or_create_refinement_session")
async def get_or_create_refinement_session(
    collection_id: str,
    rubric_id: str,
    refinement_svc: RefinementService = Depends(get_refinement_service),
):
    # Check if session exists before getting/creating
    existing_session = await refinement_svc.get_refinement_session(rubric_id)
    exists = existing_session is not None

    messages = []

    if exists:
        messages = [parse_chat_message(msg) for msg in existing_session.messages[1:]]
    else:
        await refinement_svc.create_refinement_session(collection_id, rubric_id)

    return {"new_session": not exists, "messages": format_conversation_for_client(messages)}


@refinement_router.get("/{collection_id}/refinement_session_messages")
async def get_refinement_session_messages(
    collection_id: str,
    rubric_id: str,
    refinement_svc: RefinementService = Depends(get_refinement_service),
):
    session = await refinement_svc.get_refinement_session(rubric_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Refinement session not found")

    messages = [parse_chat_message(msg) for msg in session.messages[1:]]
    return {"messages": format_conversation_for_client(messages)}


@refinement_router.get("/{collection_id}/clear_refinement_session")
async def clear_refinement_session(
    collection_id: str,
    rubric_id: str,
    refinement_svc: RefinementService = Depends(get_refinement_service),
):
    await refinement_svc.clear_refinement_session(rubric_id)
    return {"rubric_id": rubric_id, "new_session": True}


@refinement_router.get("/{collection_id}/refinement_assistant_response")
async def get_refinement_assistant_response(
    collection_id: str,
    rubric_id: str,
    message: str,
    version: int,
    db: DocentDB = Depends(get_db),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """Stream refinement messages using Server-Sent Events."""

    async def generate():
        async with db.session() as session:
            refinement_svc = RefinementService(session, db.session, mono_svc)
            rubric_svc = RubricService(session, db.session, mono_svc)

            # Get or create session if it doesn't exist
            refinement_session = await refinement_svc.get_refinement_session(rubric_id)
            if refinement_session is None:
                raise HTTPException(status_code=404, detail="Refinement session not found")
            messages = [parse_chat_message(msg) for msg in refinement_session.messages]

            # Get judgements for context
            judgements = await rubric_svc.get_rubric_results(rubric_id, version)

            # get cluster centroids for context
            sqla_centroids = await rubric_svc.get_centroids(rubric_id, version)

            sqla_assignments = await rubric_svc.get_centroid_assignments(rubric_id, version)

            # Get the current rubric
            sqla_rubric = await rubric_svc.get_rubric(rubric_id, version=version)
            if sqla_rubric is None:
                raise HTTPException(status_code=404, detail="Rubric not found")
            rubric = sqla_rubric.to_pydantic()

            # Format the conversation with the new message
            formatted_messages = format_conversation(
                message, messages, rubric, list(sqla_centroids), judgements, sqla_assignments
            )

            # Stream the assistant response
            async for response_data in refinement_svc.get_assistant_response(
                rubric_id,
                formatted_messages,
                rubric,
            ):
                yield f"data: {json.dumps(response_data)}\n\n"

            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
