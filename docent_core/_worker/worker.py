"""
Make sure to clean up any Redis streams and state keys after the job is finished!
"""

import asyncio
import traceback
from contextlib import suppress
from functools import partial
from typing import Any

import anyio
from anyio.abc import TaskGroup
from arq.connections import RedisSettings
from arq.worker import run_worker

from docent._log_util import get_logger
from docent_core._env_util import ENV, get_deployment_id, init_sentry_or_raise
from docent_core._server._broker.redis_client import get_redis_client
from docent_core._worker.constants import (
    WORKER_QUEUE_NAME,
    get_arq_job_timeout_seconds,
    get_job_timeout_seconds,
    validate_worker_queue_name,
)
from docent_core._worker.job_worker_map import JOB_DISPATCHER_MAP
from docent_core._worker.queue_metrics import queue_depth_metrics_loop
from docent_core.docent.db.contexts import TelemetryContext, ViewContext
from docent_core.docent.db.schemas.tables import JobStatus
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)

JOB_COMPLETION_WAIT_ENV_VAR = "DOCENT_WORKER_SHUTDOWN_WAIT_SECONDS"
DEFAULT_JOB_COMPLETION_WAIT_SECONDS = 3600
QUEUE_NAME_ENV_VAR = "DOCENT_WORKER_QUEUE_NAME"
QUEUE_METRICS_TASK_KEY = "queue_metrics_task"


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


def _resolve_worker_queue_name() -> str:
    override = ENV.get(QUEUE_NAME_ENV_VAR)
    if override:
        return validate_worker_queue_name(override)
    return validate_worker_queue_name(WORKER_QUEUE_NAME)


async def _worker_on_startup(queue_name: str, deployment_id: str | None, ctx: dict[str, Any]):
    """Start background tasks for the worker process."""
    try:
        ctx[QUEUE_METRICS_TASK_KEY] = asyncio.create_task(
            queue_depth_metrics_loop(queue_name, deployment_id)
        )
    except Exception as exc:
        logger.warning("Unable to start queue metrics for %s: %s", queue_name, exc)


async def _worker_on_shutdown(ctx: dict[str, Any]):
    """Shut down background tasks started in _worker_on_startup."""
    task = ctx.get(QUEUE_METRICS_TASK_KEY)
    if task is None:
        return

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def run_job(_: Any, ctx: ViewContext | TelemetryContext | None, job_id: str):
    mono_svc = await MonoService.init()
    canceled = False

    REDIS = await get_redis_client()
    commands_queue = f"commands_{job_id}"

    async def _run(tg: TaskGroup):
        nonlocal canceled
        skip_status_update = False

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
                logger.info("Job %s already canceled, skipping", job_id)
                skip_status_update = True
                return
            elif job.status == JobStatus.COMPLETED:
                logger.info("Job %s already completed, skipping", job_id)
                skip_status_update = True
                return
            elif job.status == JobStatus.CANCELLING:
                logger.info("Job %s is currently being canceled, skipping", job_id)
                skip_status_update = True
                return

            # Mark it as running
            await mono_svc.set_job_status(job_id, JobStatus.RUNNING)

            ##################
            # Core execution #
            ##################

            logger.info(f"Starting job {job_id}")

            if job.type not in JOB_DISPATCHER_MAP:
                raise ValueError(f"Unknown job type: {job.type}")

            job_timeout_seconds = get_job_timeout_seconds(job.type)
            logger.info(
                "Running job %s type=%s with timeout=%s seconds",
                job_id,
                job.type,
                job_timeout_seconds,
            )
            try:
                with anyio.fail_after(job_timeout_seconds):
                    await JOB_DISPATCHER_MAP[job.type](ctx, job)  # type: ignore
            except TimeoutError:
                logger.error(
                    "Job %s type=%s exceeded timeout of %s seconds",
                    job_id,
                    job.type,
                    job_timeout_seconds,
                )
                raise

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
                if skip_status_update:
                    return
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
    queue_name = _resolve_worker_queue_name()
    logger.info("Worker will consume queue %s", queue_name)

    run_worker(
        {
            "functions": [run_job],
            "redis_settings": redis_settings,
            "queue_name": queue_name,
            "max_jobs": 1,  # per worker
            "job_timeout": get_arq_job_timeout_seconds(),
            "job_completion_wait": job_completion_wait_seconds,
            "on_startup": partial(_worker_on_startup, queue_name, deployment_id),
            "on_shutdown": _worker_on_shutdown,
        }
    )
