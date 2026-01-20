"""
Agent run ingest worker.
Handles background processing of agent run ingestion, including decompression,
validation, and database insertion.
"""

import gzip
import time

from sqlalchemy import select

from docent._log_util import get_logger
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import SQLAIngestionPayload, SQLAJob
from docent_core.docent.server.rest.router import PostAgentRunsRequest
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


def _decode_body(raw_body: bytes, content_encoding: str | None) -> bytes:
    """
    Optionally decompress the request body.

    Args:
        raw_body: Raw bytes (possibly compressed)
        content_encoding: Normalized encoding ("", "identity", or "gzip")
    """
    if content_encoding == "gzip":
        return gzip.decompress(raw_body)
    elif content_encoding in ("", "identity", None):
        # No decompression needed
        return raw_body
    else:
        # This should never happen if endpoint normalized correctly
        raise ValueError(f"Unexpected content_encoding value: {content_encoding}")


async def agent_run_ingest_job(ctx: ViewContext, job: SQLAJob) -> None:
    """
    Process agent run ingestion in background worker.

    Raises exceptions on any failure to ensure the job is marked as failed,
    not completed.
    """
    job_params = job.job_json or {}
    collection_id = job_params.get("collection_id")
    payload_id = job_params.get("payload_id")

    if not collection_id:
        raise ValueError(f"Agent run ingest job {job.id} missing collection_id")

    if not payload_id:
        raise ValueError(f"Agent run ingest job {job.id} missing payload_id")

    start_time = time.monotonic()

    # Initialize MonoService to fetch payload
    mono_svc = await MonoService.init()

    # Fetch the payload from the database
    async with mono_svc.db.session() as session:
        result = await session.execute(
            select(SQLAIngestionPayload).where(SQLAIngestionPayload.id == payload_id)
        )
        payload_record = result.scalar_one_or_none()

    if payload_record is None:
        error_msg = f"Agent run ingest job {job.id} payload {payload_id} not found"
        raise ValueError(error_msg)

    # Decompress the request body if needed
    try:
        decoded_body = _decode_body(payload_record.payload, payload_record.content_encoding)
    except Exception as e:
        raise RuntimeError(f"Failed to decode/decompress request body: {e}") from e

    # Validate and parse JSON into AgentRun objects
    try:
        runs_request = PostAgentRunsRequest.model_validate_json(decoded_body)
    except Exception as e:
        raise RuntimeError(f"Failed to parse/validate request: {e}") from e

    # Check space and add runs (no lock - soft limit allows slight overages in race conditions)
    await mono_svc.check_space_for_runs(ctx, len(runs_request.agent_runs))
    await mono_svc.add_agent_runs(ctx, runs_request.agent_runs)

    total_duration = time.monotonic() - start_time
    logger.info(
        "agent_run_ingest job_id=%s collection_id=%s num_runs=%d duration=%.3fs",
        job.id,
        collection_id,
        len(runs_request.agent_runs),
        total_duration,
    )
