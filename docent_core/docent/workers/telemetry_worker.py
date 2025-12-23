"""
Telemetry processing worker.

This worker processes agent runs that need processing, handling race conditions
and ensuring data consistency.
"""

import time

from docent._log_util import get_logger
from docent_core._worker.constants import WorkerFunction, get_job_timeout_seconds
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.telemetry import TelemetryService

logger = get_logger(__name__)
TELEMETRY_PROCESSING_TIMEOUT_SECONDS = get_job_timeout_seconds(
    WorkerFunction.TELEMETRY_PROCESSING_JOB
)


async def telemetry_processing_job(ctx: ViewContext, job: SQLAJob) -> None:
    """
    Process agent runs that need processing.

    This job processes agent runs once and queues a new job if there's more work.
    """
    try:
        # Get job parameters
        job_params = job.job_json or {}
        collection_id = job_params.get("collection_id")
        agent_run_id = job_params.get("agent_run_id")
        user_email = job_params.get("user_email")

        if not collection_id:
            logger.error("Telemetry processing job missing collection_id parameter")
            return

        if not user_email:
            logger.error("Telemetry processing job missing user email")
            return

        job_start = time.monotonic()
        logger.info(
            "telemetry_processing_job phase=start collection_id=%s agent_run_id=%s job_id=%s",
            collection_id,
            agent_run_id,
            job.id,
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

        if agent_run_id:
            await _process_single_agent_run_job(collection_id, agent_run_id, user, mono_svc)
        else:
            await _process_collection_batch_job(collection_id, user, mono_svc)

        total_duration = time.monotonic() - job_start
        logger.info(
            "telemetry_processing_job phase=complete collection_id=%s agent_run_id=%s duration=%.3fs",
            collection_id,
            agent_run_id,
            total_duration,
        )

    except Exception as e:
        logger.error(f"Error in telemetry processing job: {str(e)}", exc_info=True)
        raise


async def _process_single_agent_run_job(
    collection_id: str, agent_run_id: str, user: User, mono_svc: MonoService
) -> None:
    job_start = time.monotonic()
    async with mono_svc.db.session() as session:
        telemetry_svc = TelemetryService(session, mono_svc)
        processed = await telemetry_svc.process_single_agent_run_job(
            collection_id, agent_run_id, user
        )

    total_duration = time.monotonic() - job_start
    logger.info(
        "telemetry_processing agent_run phase=complete collection_id=%s agent_run_id=%s duration=%.3fs processed=%s",
        collection_id,
        agent_run_id,
        total_duration,
        processed,
    )


async def _process_collection_batch_job(collection_id: str, user: User, mono_svc: MonoService):
    # Backward-compatible collection-level processing path
    processing_duration = 0.0
    async with mono_svc.db.session() as session:
        telemetry_svc = TelemetryService(session, mono_svc)
        processing_phase_start = time.monotonic()
        processed_agent_run_ids = await telemetry_svc.process_agent_runs_for_collection(
            collection_id,
            user,
            limit=10,
            time_budget_seconds=max(1, int(TELEMETRY_PROCESSING_TIMEOUT_SECONDS / 2)),
        )
        processing_duration = time.monotonic() - processing_phase_start

    if processed_agent_run_ids:
        logger.info(
            "Processed %s agent runs for collection %s", len(processed_agent_run_ids), collection_id
        )
    else:
        logger.info("No agent runs to process for collection %s", collection_id)
    logger.info(
        "telemetry_processing_job phase=processing collection_id=%s duration=%.3fs processed=%s",
        collection_id,
        processing_duration,
        len(processed_agent_run_ids or []),
    )

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
        logger.info(f"More work found for collection {collection_id}, queued new job {new_job_id}")
    else:
        logger.info(f"No more work for collection {collection_id}")
    logger.info(
        "telemetry_processing_job phase=ensure_remaining_work collection_id=%s duration=%.3fs enqueued=%s",
        collection_id,
        ensure_duration,
        bool(new_job_id),
    )
