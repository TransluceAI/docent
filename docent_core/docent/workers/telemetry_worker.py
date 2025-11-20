"""
Telemetry processing worker.

This worker processes agent runs that need processing, handling race conditions
and ensuring data consistency.
"""

import time

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

        job_start = time.monotonic()
        logger.info(
            "telemetry_processing_job phase=start collection_id=%s job_id=%s", collection_id, job.id
        )

        # Initialize MonoService and get user by email
        context_start = time.monotonic()
        mono_svc = await MonoService.init()
        user = await mono_svc.get_user_by_email(user_email)
        context_duration = time.monotonic() - context_start
        if user is None:
            logger.error(f"User with email {user_email} not found")
            return
        logger.info(
            "telemetry_processing_job phase=resolve_user collection_id=%s user_email=%s duration=%.3fs",
            collection_id,
            user_email,
            context_duration,
        )

        # Process agent runs once with a buffer to avoid hitting the worker timeout
        processing_duration = 0.0
        async with mono_svc.db.session() as session:
            telemetry_svc = TelemetryService(session, mono_svc)
            processing_phase_start = time.monotonic()
            processed_agent_run_ids = await telemetry_svc.process_agent_runs_for_collection(
                collection_id,
                user,
                limit=10,
                time_budget_seconds=max(1, int(JOB_TIMEOUT_SECONDS / 2)),
            )
            processing_duration = time.monotonic() - processing_phase_start

        if processed_agent_run_ids:
            logger.info(
                f"Processed {len(processed_agent_run_ids)} agent runs for collection {collection_id}"
            )
        else:
            logger.info(f"No agent runs to process for collection {collection_id}")
        logger.info(
            "telemetry_processing_job phase=processing collection_id=%s duration=%.3fs processed=%s",
            collection_id,
            processing_duration,
            len(processed_agent_run_ids or []),
        )

        # Check if there's more work and queue a new job if needed
        ensure_duration = 0.0
        async with mono_svc.db.session() as session:
            telemetry_svc = TelemetryService(session, mono_svc)
            ensure_start = time.monotonic()
            new_job_id = await telemetry_svc.ensure_telemetry_processing_for_collection(
                collection_id,
                user,
                force=True,
            )
            ensure_duration = time.monotonic() - ensure_start

        if new_job_id:
            logger.info(
                f"More work found for collection {collection_id}, queued new job {new_job_id}"
            )
        else:
            logger.info(f"No more work for collection {collection_id}")
        logger.info(
            "telemetry_processing_job phase=ensure_remaining_work collection_id=%s duration=%.3fs enqueued=%s",
            collection_id,
            ensure_duration,
            bool(new_job_id),
        )

        total_duration = time.monotonic() - job_start
        logger.info(
            "telemetry_processing_job phase=complete collection_id=%s duration=%.3fs",
            collection_id,
            total_duration,
        )

    except Exception as e:
        logger.error(f"Error in telemetry processing job: {str(e)}", exc_info=True)
        raise
