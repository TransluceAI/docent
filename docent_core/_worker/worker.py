"""
Make sure to clean up any Redis streams and state keys after the job is finished!
"""

import traceback
from typing import Any

import anyio
from anyio.abc import TaskGroup
from arq.connections import RedisSettings
from arq.worker import run_worker

from docent._log_util import get_logger
from docent_core._env_util import ENV, get_deployment_id, init_sentry_or_raise
from docent_core._server._broker.redis_client import get_redis_client
from docent_core._worker.constants import JOB_TIMEOUT_SECONDS, WORKER_QUEUE_NAME
from docent_core._worker.job_worker_map import JOB_DISPATCHER_MAP
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import JobStatus
from docent_core.docent.services.monoservice import MonoService
from docent_core.investigator.db.contexts import WorkspaceContext

logger = get_logger(__name__)

JOB_COMPLETION_WAIT_ENV_VAR = "DOCENT_WORKER_SHUTDOWN_WAIT_SECONDS"
DEFAULT_JOB_COMPLETION_WAIT_SECONDS = 3600


def _resolve_job_completion_wait_seconds() -> int:
    raw_value = ENV.get(JOB_COMPLETION_WAIT_ENV_VAR)
    if not raw_value:
        return DEFAULT_JOB_COMPLETION_WAIT_SECONDS

    try:
        value = int(raw_value)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; defaulting to %s seconds",
            JOB_COMPLETION_WAIT_ENV_VAR,
            raw_value,
            DEFAULT_JOB_COMPLETION_WAIT_SECONDS,
        )
        return DEFAULT_JOB_COMPLETION_WAIT_SECONDS

    if value < 0:
        logger.warning(
            "Negative %s=%s; defaulting to %s seconds",
            JOB_COMPLETION_WAIT_ENV_VAR,
            value,
            DEFAULT_JOB_COMPLETION_WAIT_SECONDS,
        )
        return DEFAULT_JOB_COMPLETION_WAIT_SECONDS

    return value


async def run_job(_: Any, ctx: ViewContext | WorkspaceContext, job_id: str):
    mono_svc = await MonoService.init()
    canceled = False

    REDIS = await get_redis_client()
    commands_queue = f"commands_{job_id}"

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
            elif job.status == JobStatus.CANCELLING:
                raise RuntimeError(f"Job {job_id} is currently being canceled")

            # Mark it as running
            await mono_svc.set_job_status(job_id, JobStatus.RUNNING)

            ##################
            # Core execution #
            ##################

            logger.info(f"Starting job {job_id}")

            if job.type not in JOB_DISPATCHER_MAP:
                raise ValueError(f"Unknown job type: {job.type}")

            await JOB_DISPATCHER_MAP[job.type](ctx, job)  # type: ignore

        except anyio.get_cancelled_exc_class():
            canceled = True
            raise
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}. Traceback: {traceback.format_exc()}")
            canceled = True
            raise
        finally:
            # If the job finishes normally, we need to cancel the `await_commands` loop
            tg.cancel_scope.cancel()

            with anyio.CancelScope(shield=True):
                # Update the job status
                if canceled:
                    logger.highlight(f"Job {job_id} canceled", color="red")
                    await mono_svc.set_job_status(job_id, JobStatus.CANCELED)
                else:
                    logger.highlight(f"Job {job_id} finished", color="green")
                    await mono_svc.set_job_status(job_id, JobStatus.COMPLETED)

                # Cleanup
                await REDIS.delete(commands_queue)  # type: ignore

    async def await_commands(tg: TaskGroup):
        nonlocal canceled

        while True:
            _queue, command = await REDIS.blpop(commands_queue)  # type: ignore
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
    # Initialize Sentry for production/staging environments
    deployment_id = get_deployment_id()
    if deployment_id:
        dsn = ENV.get("SENTRY_DSN")
        init_sentry_or_raise(deployment_id, dsn)
        logger.info(f"Initialized Sentry for worker in {deployment_id}")

    REDIS_HOST = ENV.get("DOCENT_REDIS_HOST")
    REDIS_PORT = ENV.get("DOCENT_REDIS_PORT")
    REDIS_USER = ENV.get("DOCENT_REDIS_USER")
    REDIS_PASSWORD = ENV.get("DOCENT_REDIS_PASSWORD")
    REDIS_TLS = ENV.get("DOCENT_REDIS_TLS", "false").strip().lower() == "true"

    if REDIS_HOST is None or REDIS_PORT is None:
        raise ValueError("DOCENT_REDIS_HOST and DOCENT_REDIS_PORT must be set")

    # Build Redis settings with optional authentication and TLS
    if REDIS_USER is not None and REDIS_PASSWORD is not None:
        redis_settings = RedisSettings(
            host=REDIS_HOST,
            port=int(REDIS_PORT),
            username=REDIS_USER,
            password=REDIS_PASSWORD,
            ssl=REDIS_TLS,
        )
    else:
        redis_settings = RedisSettings(
            host=REDIS_HOST,
            port=int(REDIS_PORT),
            ssl=REDIS_TLS,
        )

    job_completion_wait_seconds = _resolve_job_completion_wait_seconds()
    logger.info(
        "Worker shutdown waits up to %s seconds for in-flight jobs",
        job_completion_wait_seconds,
    )

    run_worker(
        {
            "functions": [run_job],
            "redis_settings": redis_settings,
            "queue_name": WORKER_QUEUE_NAME,
            "max_jobs": 1,  # per worker
            "job_timeout": JOB_TIMEOUT_SECONDS,
            "job_completion_wait": job_completion_wait_seconds,
        }
    )
