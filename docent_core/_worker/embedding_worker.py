import asyncio

import anyio

from docent._log_util import get_logger
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.tables import JobStatus, SQLAJob
from docent_core._db_service.service import MonoService
from docent_core._server._broker.redis_client import publish_collection_update

logger = get_logger(__name__)


async def compute_embeddings(view_ctx: ViewContext, job_id: str):
    logger.info(f"Starting compute_embeddings: view_ctx={view_ctx}, job_id={job_id}")

    mono_svc = await MonoService.init()
    job = await mono_svc.get_job(job_id)

    if job is None:
        logger.error(f"Embedding job {job_id} not found")
        return

    if job.type != "compute_embeddings":
        logger.error(f"Job {job_id} is not an embedding job (type: {job.type})")
        return

    # Wait for any running embedding jobs
    while (
        await mono_svc.get_embedding_job_count(
            view_ctx.collection_id,
            _where_clause=SQLAJob.status == JobStatus.RUNNING,
        )
        >= 1
    ):
        logger.info(
            f"Job {job_id} waiting for existing embedding job to complete for collection_id {view_ctx.collection_id}"
        )
        await asyncio.sleep(5)

    should_index = job.job_json["should_index"]

    await mono_svc.set_job_status(job_id, JobStatus.RUNNING)

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
        await publish_collection_update(
            view_ctx.collection_id,
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

            phase, percent = await mono_svc.get_indexing_progress(view_ctx.collection_id)
            if phase is None:
                continue

            progress_data = {
                "indexing_phase": phase,
                "embedding_progress": 100,
                "indexing_progress": percent or 0,
            }

            # Send via websocket instead of Redis stream
            await publish_collection_update(
                view_ctx.collection_id,
                {"action": "embedding_progress", "payload": progress_data},
            )

            # If indexing is complete (100%), we can stop polling
            if percent is not None and percent >= 100:
                indexing_completed = True
                break

    async def _run():
        """Main embedding computation logic"""
        nonlocal embedding_completed, indexing_completed, errored

        try:
            async with mono_svc.advisory_lock(
                view_ctx.collection_id, action_id="compute_embeddings"
            ):
                # Compute embeddings
                embedding_status = await mono_svc.compute_embeddings(view_ctx, _progress_callback)

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
                await publish_collection_update(
                    view_ctx.collection_id,
                    {"action": "embedding_progress", "payload": progress_data},
                )

                # Compute index
                await mono_svc.compute_ivfflat_index(view_ctx)
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
                    await mono_svc.set_job_status(job_id, JobStatus.CANCELED)
                else:
                    logger.highlight(f"Job {job_id} finished", color="green")
                    await mono_svc.set_job_status(job_id, JobStatus.COMPLETED)
                    # Send completion message via websocket
                    await publish_collection_update(
                        view_ctx.collection_id,
                        {"action": "embedding_complete", "payload": {}},
                    )

    async with anyio.create_task_group() as tg:
        tg.start_soon(_run)
        if should_index:
            tg.start_soon(_poll_indexing_status)
