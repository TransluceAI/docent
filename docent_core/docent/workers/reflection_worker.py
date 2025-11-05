import traceback

from docent._log_util import get_logger
from docent_core._db_service.db import DocentDB
from docent_core._server._broker.redis_client import (
    STATE_KEY_FORMAT,
    STREAM_KEY_FORMAT,
    get_redis_client,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.services.llms import LLMService
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService
from docent_core.docent.services.usage import UsageService

logger = get_logger(__name__)


async def reflection_job(ctx: ViewContext, job: SQLAJob):
    db = await DocentDB.init()
    mono_svc = await MonoService.init()

    if ctx.user is None:
        raise ValueError("User is required to run reflection job")

    # Set up Redis streaming
    REDIS = await get_redis_client()
    stream_key = STREAM_KEY_FORMAT.format(job_id=job.id)
    state_key = STATE_KEY_FORMAT.format(job_id=job.id)

    async with db.session() as session:
        usage_svc = UsageService(db.session)
        llm_svc = LLMService(db.session, ctx.user, usage_svc)
        rubric_svc = RubricService(session, db.session, mono_svc, llm_svc)

        agent_run_id = job.job_json["agent_run_id"]
        rubric_id = job.job_json["rubric_id"]
        rubric_version = job.job_json["rubric_version"]

        async def publish_state(reflection_id: str | None = None):
            """Publish current state to Redis."""
            try:
                state = {
                    "agent_run_id": agent_run_id,
                    "rubric_id": rubric_id,
                    "rubric_version": rubric_version,
                    "reflection_id": reflection_id,
                }
                await REDIS.set(state_key, str(state), ex=1800)  # type: ignore
                await REDIS.xadd(stream_key, {"event": "state_updated"}, maxlen=200)  # type: ignore
            except Exception:
                logger.error(
                    f"Failed to publish state to Redis for job {job.id}: {traceback.format_exc()}"
                )

        # Publish initial state
        await publish_state()

        # Run the reflection job
        await rubric_svc.run_reflection_job(ctx, job)

        # Commit the session to ensure reflection is in DB
        await session.commit()

        # Publish final state (reflection is now in DB)
        await publish_state("computed")

    # Job is finished - publish outside session to ensure data is committed
    await REDIS.xadd(stream_key, {"event": "finished"}, maxlen=200)  # type: ignore

    # Cleanup
    await REDIS.expire(stream_key, 600)  # type: ignore
    await REDIS.expire(state_key, 600)  # type: ignore
