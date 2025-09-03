"""
Telemetry processing worker.

This worker processes agent runs that need processing, handling race conditions
and ensuring data consistency.
"""

from redis.exceptions import LockError

from docent._log_util import get_logger
from docent_core._server._broker.redis_client import get_redis_client
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.telemetry import TelemetryService

logger = get_logger(__name__)


async def telemetry_processing_job(ctx: ViewContext, job: SQLAJob) -> None:
    """
    Process agent runs that need processing.

    This job processes all agent runs that need processing for a collection,
    handling race conditions and ensuring data consistency.
    """
    try:
        # Get job parameters
        job_params = job.job_json or {}
        collection_id = job_params.get("collection_id")
        user_email = job_params.get("user_email")

        if not collection_id:
            logger.error("Telemetry processing job missing collection_id parameter")
            return

        if not user_email:
            logger.error("Telemetry processing job missing user email")
            return

        logger.info(f"Starting telemetry processing job for collection {collection_id}")

        # Initialize MonoService and get user by email
        mono_svc = await MonoService.init()
        user = await mono_svc.get_user_by_email(user_email)
        if user is None:
            logger.error(f"User with email {user_email} not found")
            return

        # Use Redis lock to prevent concurrent processing of the same collection
        redis_client = await get_redis_client()
        lock = redis_client.lock(f"telemetry_collection_lock_{collection_id}", timeout=0)
        try:
            async with lock:
                # Continue processing agent runs as long as there are new ones to process
                total_processed = 0
                iteration = 0

                while True:
                    iteration += 1
                    logger.info(
                        f"Telemetry processing iteration {iteration} for collection {collection_id}"
                    )

                    async with mono_svc.db.session() as session:
                        telemetry_svc = TelemetryService(session, mono_svc)
                        processed_agent_run_ids = (
                            await telemetry_svc.process_agent_runs_for_collection(
                                collection_id, user
                            )
                        )

                    if not processed_agent_run_ids:
                        logger.info(
                            f"No more agent runs to process for collection {collection_id} after {iteration} iterations"
                        )
                        break

                    total_processed += len(processed_agent_run_ids)
                    logger.info(
                        f"Processed {len(processed_agent_run_ids)} agent runs in iteration {iteration}, total: {total_processed}"
                    )

                    # Small delay to prevent tight loops and allow for any new data to arrive
                    import asyncio

                    await asyncio.sleep(1)

                logger.info(
                    f"Completed telemetry processing for collection {collection_id}: {total_processed} agent runs processed in {iteration} iterations"
                )
        except LockError:
            logger.info(f"Collection {collection_id} is already being processed, skipping")
            return

    except Exception as e:
        logger.error(f"Error in telemetry processing job: {str(e)}", exc_info=True)
        raise
