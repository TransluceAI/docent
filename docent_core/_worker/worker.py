import asyncio
import json
from typing import Any

import anyio
import redis.asyncio as redis
from anyio.abc import TaskGroup
from arq import ArqRedis
from arq.connections import RedisSettings
from arq.worker import run_worker
from pydantic_core import to_jsonable_python

from docent._log_util import get_logger
from docent_core._ai_tools.search import SearchResult
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.tables import JobStatus, SQLAJob
from docent_core._db_service.service import DBService
from docent_core._env_util import ENV
from docent_core._server._broker.redis_client import publish_framegrid_update
from docent_core._server._rest.send_state import publish_searches

logger = get_logger(__name__)


# Initialize Redis connection
REDIS_HOST = ENV.get("DOCENT_REDIS_HOST")
REDIS_PORT = ENV.get("DOCENT_REDIS_PORT")
if REDIS_HOST is None or REDIS_PORT is None:
    raise ValueError("DOCENT_REDIS_HOST and DOCENT_REDIS_PORT must be set")
REDIS = ArqRedis(
    connection_pool=redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
)


async def compute_search(_: dict[Any, Any], view_ctx: ViewContext, job_id: str, read_only: bool):
    db = await DBService.init()
    result = await db.get_search_job_and_query(job_id)
    if result is None:
        logger.error(f"Search job {job_id} not found")
        return
    _job, query = result

    await db.set_job_status(job_id, JobStatus.RUNNING)

    async def _search_result_callback(
        search_results: list[SearchResult] | None,
    ) -> None:
        if search_results or search_results is None:
            await REDIS.xadd(
                f"results_{job_id}",
                {"results": json.dumps(to_jsonable_python(search_results))},
            )
            with anyio.CancelScope(shield=True):
                await publish_searches(db, view_ctx)

    canceled = False

    async def run(tg: TaskGroup):
        nonlocal canceled
        try:
            async with db.advisory_lock(
                view_ctx.fg_id + "__search__" + query.search_query,
                action_id="mutation",
            ):
                await db.compute_search(
                    view_ctx,
                    query.search_query,
                    _search_result_callback,
                    read_only,
                )
                tg.cancel_scope.cancel()
        except:
            canceled = True
            raise
        finally:
            with anyio.CancelScope(shield=True):
                if canceled:
                    logger.highlight(f"Job {job_id} canceled", color="red")
                    await db.set_job_status(job_id, JobStatus.CANCELED)
                else:
                    logger.highlight(f"Job {job_id} finished", color="green")
                    await db.set_job_status(job_id, JobStatus.COMPLETED)

                await publish_searches(db, view_ctx)
                await REDIS.delete(f"results_{job_id}")

    async def await_commands(tg: TaskGroup):
        nonlocal canceled
        q = f"commands_{job_id}"

        while True:
            _queue, command = await REDIS.blpop(q)  # type: ignore
            logger.info(f"{job_id} received {command}")

            match command:  # type: ignore
                case "cancel":
                    # The search task may internally prevent cancellation requests from bubbling all
                    # the way up, so explicitly note down the cancellation if we do it ourselves.
                    canceled = True

                    tg.cancel_scope.cancel()

    async with anyio.create_task_group() as tg:
        tg.start_soon(run, tg)
        tg.start_soon(await_commands, tg)


async def compute_embeddings(ctx: dict[Any, Any], view_ctx: ViewContext, job_id: str):
    """
    Worker function to compute embeddings for agent runs.

    Args:
        ctx: Worker context (unused but required by arq)
        view_ctx: The view context containing frame grid information
        job_id: The ID of the embedding job
    """
    logger.info(f"Starting compute_embeddings: view_ctx={view_ctx}, job_id={job_id}")

    db = await DBService.init()
    job = await db.get_job(job_id)

    if job is None:
        logger.error(f"Embedding job {job_id} not found")
        return

    if job.type != "compute_embeddings":
        logger.error(f"Job {job_id} is not an embedding job (type: {job.type})")
        return

    # Wait for any running embedding jobs
    while (
        await db.get_embedding_job_count(
            view_ctx.fg_id,
            _where_clause=SQLAJob.status == JobStatus.RUNNING,
        )
        >= 1
    ):
        logger.info(
            f"Job {job_id} waiting for existing embedding job to complete for fg_id {view_ctx.fg_id}"
        )
        await asyncio.sleep(5)

    should_index = job.job_json["should_index"]

    await db.set_job_status(job_id, JobStatus.RUNNING)

    # Track completion states
    errored = False
    embedding_completed = False
    indexing_completed = False

    async def _progress_callback(progress: int):
        """Callback for embedding computation progress"""
        progress_data = {
            "indexing_phase": "pending" if should_index else "not_required",
            "embedding_progress": progress,
            "indexing_progress": 0,
        }

        # Send via websocket instead of Redis stream
        await publish_framegrid_update(
            view_ctx.fg_id,
            {"action": "embedding_progress", "payload": progress_data},
        )

    async def _poll_indexing_status():
        nonlocal embedding_completed, indexing_completed

        """Poll and report indexing progress after embeddings complete"""
        # Wait for embeddings to complete before starting to poll
        while not embedding_completed:
            await asyncio.sleep(1)

        # Now start polling for indexing progress
        while not indexing_completed:
            await asyncio.sleep(1)

            phase, percent = await db.get_indexing_progress(view_ctx.fg_id)
            if phase is None:
                continue

            progress_data = {
                "indexing_phase": phase,
                "embedding_progress": 100,
                "indexing_progress": percent or 0,
            }

            # Send via websocket instead of Redis stream
            await publish_framegrid_update(
                view_ctx.fg_id,
                {"action": "embedding_progress", "payload": progress_data},
            )

            # If indexing is complete (100%), we can stop polling
            if percent is not None and percent >= 100:
                indexing_completed = True
                break

    async def run():
        """Main embedding computation logic"""
        nonlocal embedding_completed, indexing_completed, errored

        try:
            async with db.advisory_lock(view_ctx.fg_id, action_id="compute_embeddings"):
                # Compute embeddings
                embedding_status = await db.compute_embeddings(view_ctx, _progress_callback)

                if not embedding_status:
                    errored = True
                    return

                embedding_completed = True
                logger.info(f"Embeddings computation completed for job {job_id}")

                if not should_index:
                    indexing_completed = True
                    return

                # Report that we're starting indexing
                progress_data = {
                    "indexing_phase": "starting",
                    "embedding_progress": 100,
                    "indexing_progress": 0,
                }
                # Send via websocket instead of Redis stream
                await publish_framegrid_update(
                    view_ctx.fg_id,
                    {"action": "embedding_progress", "payload": progress_data},
                )

                # Compute index
                await db.compute_ivfflat_index(view_ctx)
                indexing_completed = True
                logger.info(f"Indexing completed for job {job_id}")

        except Exception as e:
            logger.error(f"Error computing embeddings for job {job_id}: {e}")
            errored = True
            raise

        finally:
            with anyio.CancelScope(shield=True):
                if errored:
                    logger.highlight(f"Job {job_id} canceled", color="red")
                    await db.set_job_status(job_id, JobStatus.CANCELED)
                else:
                    logger.highlight(f"Job {job_id} finished", color="green")
                    await db.set_job_status(job_id, JobStatus.COMPLETED)
                    # Send completion message via websocket
                    await publish_framegrid_update(
                        view_ctx.fg_id,
                        {"action": "embedding_complete", "payload": {}},
                    )

    async with anyio.create_task_group() as tg:
        tg.start_soon(run)
        if should_index:
            tg.start_soon(_poll_indexing_status)


def run():
    """Run a single worker that processes both search and embedding jobs."""

    assert REDIS_HOST is not None and REDIS_PORT is not None

    run_worker(
        {
            "functions": [compute_search, compute_embeddings],
            "redis_settings": RedisSettings(host=REDIS_HOST, port=int(REDIS_PORT)),
            "queue_name": "embedding_and_search_queue",
            "max_jobs": 5,  # Allow up to 5 concurrent jobs per worker
        }
    )
