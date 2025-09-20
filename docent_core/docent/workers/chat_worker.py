import json
import traceback

from fastapi.encoders import jsonable_encoder

from docent._log_util import get_logger
from docent_core._db_service.db import DocentDB
from docent_core._server._broker.redis_client import (
    STATE_KEY_FORMAT,
    STREAM_KEY_FORMAT,
    get_redis_client,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.services.chat import (
    ChatService,
    ChatSession,
)
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService

logger = get_logger(__name__)


async def chat_job(ctx: ViewContext, job: SQLAJob):
    db = await DocentDB.init()
    mono_svc = await MonoService.init()

    async with db.session() as session:
        rubric_svc = RubricService(session, db.session, mono_svc)
        chat_svc = ChatService(session, db.session, mono_svc, rubric_svc)

        sqla_chat_session = await chat_svc.get_session_by_id(job.job_json["session_id"])
        if sqla_chat_session is None:
            raise ValueError(f"Chat session {job.job_json['session_id']} not found")

        # Notify updates via a Redis stream and keep authoritative state in a separate key
        REDIS = await get_redis_client()
        stream_key = STREAM_KEY_FORMAT.format(job_id=job.id)
        state_key = STATE_KEY_FORMAT.format(job_id=job.id)

        async def _event_callback(session: ChatSession) -> None:
            try:
                payload = json.dumps(jsonable_encoder(session))
                # Update authoritative state with sliding 1800s TTL
                await REDIS.set(state_key, payload, ex=1800)  # type: ignore
                # Send a lightweight notifier event; trim to avoid growth
                await REDIS.xadd(stream_key, {"event": "state_updated"}, maxlen=200)  # type: ignore
            except Exception:
                logger.error(
                    f"Failed to append event to Redis stream {stream_key} for job {job.id}: {traceback.format_exc()}"
                )

        # Publish the initial state with parsed citations
        initial_state = await chat_svc.get_current_state(ctx, sqla_chat_session)
        await _event_callback(initial_state)

        # Run the chat turn
        _ = await chat_svc.one_turn(ctx, sqla_chat_session, sse_callback=_event_callback)

        # Job is finished (final state already published by one_turn)
        await REDIS.xadd(stream_key, {"event": "finished"}, maxlen=200)  # type: ignore

        # Cleanup
        await REDIS.expire(stream_key, 600)  # type: ignore
        await REDIS.expire(state_key, 600)  # type: ignore
