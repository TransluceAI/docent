"""
Telemetry processing worker.

This worker processes agent runs that need processing, handling race conditions
and ensuring data consistency.
"""

from docent._log_util import get_logger
from docent_core._worker.constants import JOB_TIMEOUT_SECONDS
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.telemetry import TelemetryService

logger = get_logger(__name__)


async def telemetry_processing_job(ctx: ViewContext, job: SQLAJob) -> None:
    """
    Process agent runs that need processing.

    This job processes agent runs once and queues a new job if there's more work.
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

        # Process agent runs once with a buffer to avoid hitting the worker timeout
        async with mono_svc.db.session() as session:
            telemetry_svc = TelemetryService(session, mono_svc)
            processed_agent_run_ids = await telemetry_svc.process_agent_runs_for_collection(
                collection_id,
                user,
                limit=5,
                time_budget_seconds=max(1, int(JOB_TIMEOUT_SECONDS / 2)),
            )

        if processed_agent_run_ids:
            logger.info(
                f"Processed {len(processed_agent_run_ids)} agent runs for collection {collection_id}"
            )
        else:
            logger.info(f"No agent runs to process for collection {collection_id}")

        # Check if there's more work and queue a new job if needed
        async with mono_svc.db.session() as session:
            telemetry_svc = TelemetryService(session, mono_svc)
            new_job_id = await telemetry_svc.ensure_telemetry_processing_for_collection(
                collection_id, user
            )

        if new_job_id:
            logger.info(
                f"More work found for collection {collection_id}, queued new job {new_job_id}"
            )
        else:
            logger.info(f"No more work for collection {collection_id}")

    except Exception as e:
        logger.error(f"Error in telemetry processing job: {str(e)}", exc_info=True)
        raise
