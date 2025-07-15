import traceback
from typing import Any

import anyio
import redis.asyncio as redis
from anyio.abc import TaskGroup
from arq import ArqRedis
from arq.connections import RedisSettings
from arq.worker import run_worker

from docent._log_util import get_logger
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.db import DocentDB
from docent_core._db_service.schemas.tables import JobStatus, SQLAJob
from docent_core._db_service.service import MonoService
from docent_core._env_util import ENV
from docent_core._worker.constants import WORKER_QUEUE_NAME, WorkerFunction
from docent_core._worker.embedding_worker import compute_embeddings
from docent_core._worker.search_worker import compute_search
from docent_core.services.rubric import RubricService

logger = get_logger(__name__)


# Initialize Redis connection
REDIS_HOST = ENV.get("DOCENT_REDIS_HOST")
REDIS_PORT = ENV.get("DOCENT_REDIS_PORT")
if REDIS_HOST is None or REDIS_PORT is None:
    raise ValueError("DOCENT_REDIS_HOST and DOCENT_REDIS_PORT must be set")
REDIS = ArqRedis(
    connection_pool=redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
)


async def rubric_job(ctx: ViewContext, job: SQLAJob):
    db = await DocentDB.init()
    mono_svc = await MonoService.init()

    # Communicate the total number of agent runs
    # TODO(mengk): slightly hacky, not sure what's better tho
    await mono_svc.set_job_json(
        job.id, job.job_json | {"total_agent_runs": await mono_svc.count_base_agent_runs(ctx)}
    )

    async with db.session() as session:
        rs = RubricService(session, db.session, mono_svc)
        await rs.run_rubric_job(ctx, job)


async def run_job(_: Any, ctx: ViewContext, job_id: str):
    mono_svc = await MonoService.init()
    canceled = False

    async def _run(tg: TaskGroup):
        nonlocal canceled

        try:
            #########
            # Setup #
            #########

            # Get the job
            job = await mono_svc.get_job(job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")

            # If it's canceled, just return
            if job.status == JobStatus.CANCELED:
                raise RuntimeError("Job was already canceled")
            elif job.status == JobStatus.COMPLETED:
                raise RuntimeError("Job was already completed")

            # Mark it as running
            await mono_svc.set_job_status(job_id, JobStatus.RUNNING)

            ##################
            # Core execution #
            ##################

            logger.info(f"Starting job {job_id}")

            # Run the job with the appropriate function
            if job.type == WorkerFunction.RUBRIC_JOB.value:
                await rubric_job(ctx, job)
            elif job.type == WorkerFunction.COMPUTE_SEARCH.value:
                await compute_search(ctx, job_id, read_only=False, REDIS=REDIS)
            elif job.type == WorkerFunction.COMPUTE_EMBEDDINGS.value:
                await compute_embeddings(ctx, job_id)
            else:
                raise ValueError(f"Unknown job type: {job.type}")
        except anyio.get_cancelled_exc_class():
            canceled = True
            raise
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}. Traceback: {traceback.format_exc()}")
            canceled = True
            raise
        finally:
            tg.cancel_scope.cancel()
            with anyio.CancelScope(shield=True):
                # Update the job status
                if canceled:
                    logger.highlight(f"Job {job_id} canceled", color="red")
                    await mono_svc.set_job_status(job_id, JobStatus.CANCELED)
                else:
                    logger.highlight(f"Job {job_id} finished", color="green")
                    await mono_svc.set_job_status(job_id, JobStatus.COMPLETED)

                # Send immediate cancellation confirmation to caller
                response_queue = f"cancel_response_{job_id}"
                await REDIS.rpush(response_queue, "cancelled")  # type: ignore
                logger.info(f"Sent cancellation confirmation for job {job_id} to {response_queue}")

    async def await_commands(tg: TaskGroup):
        nonlocal canceled
        q = f"commands_{job_id}"

        while True:
            _queue, command = await REDIS.blpop(q)  # type: ignore
            logger.info(f"{job_id} received {command}")
            assert isinstance(command, str)

            # Handle cancel command with optional response ID
            match command:
                case "cancel":
                    tg.cancel_scope.cancel()
                case _:
                    logger.error(f"Unknown command received for job {job_id}: {str(command)}")  # type: ignore

    async with anyio.create_task_group() as tg:
        tg.start_soon(_run, tg)
        tg.start_soon(await_commands, tg)


def run():
    # This was already checked and is for type checking
    assert REDIS_HOST is not None and REDIS_PORT is not None

    run_worker(
        {
            "functions": [run_job],
            "redis_settings": RedisSettings(host=REDIS_HOST, port=int(REDIS_PORT)),
            "queue_name": WORKER_QUEUE_NAME,
            "max_jobs": 5,  # per worker
        }
    )
