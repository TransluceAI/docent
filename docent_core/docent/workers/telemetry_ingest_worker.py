"""
Telemetry ingest worker.

Moves CPU-heavy OTLP parsing and span accumulation off the request path.
"""

import base64
import gzip
import time
from collections import defaultdict
from typing import Any, Dict, Optional

from docent._log_util import get_logger
from docent_core._server._broker.redis_client import get_redis_client
from docent_core._worker.constants import WorkerFunction, get_job_timeout_seconds
from docent_core.docent.db.contexts import TelemetryContext
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.telemetry import TelemetryService
from docent_core.docent.services.telemetry_accumulation import TelemetryAccumulationService

logger = get_logger(__name__)
INGEST_LOCK_WAIT_LOG_THRESHOLD_SECONDS = 0.05
TELEMETRY_INGEST_TIMEOUT_SECONDS = get_job_timeout_seconds(WorkerFunction.TELEMETRY_INGEST_JOB)


def _decode_body(job_data: Dict[str, Any]) -> Optional[bytes]:
    body_b64 = job_data.get("body_b64")
    if not isinstance(body_b64, str) or not body_b64:
        return None

    raw_body = base64.b64decode(body_b64)
    content_encoding = job_data.get("content_encoding")
    if content_encoding == "gzip":
        raw_body = gzip.decompress(raw_body)

    return raw_body


async def telemetry_ingest_job(ctx: TelemetryContext, job: SQLAJob) -> None:
    job_params = job.job_json or {}
    telemetry_log_id = job_params.get("telemetry_log_id")
    user_email = job_params.get("user_email")
    request_id = job_params.get("request_id")
    agent_runs_by_collection: dict[str, set[str]] = defaultdict(set)

    if not telemetry_log_id:
        logger.error("Telemetry ingest job missing telemetry_log_id")
        return

    if not user_email:
        logger.error("Telemetry ingest job missing user_email")
        return

    start_wall = time.time()
    start_monotonic = time.monotonic()
    user_lookup_start = time.monotonic()
    mono_svc = await MonoService.init()
    user = await mono_svc.get_user_by_email(user_email)
    user_lookup_duration = time.monotonic() - user_lookup_start
    if user is None:
        logger.error("Telemetry ingest job %s: user %s not found", telemetry_log_id, user_email)
        return
    logger.info(
        "telemetry_ingest phase=resolve_user telemetry_log_id=%s request_id=%s duration=%.3fs user_email=%s",
        telemetry_log_id,
        request_id,
        user_lookup_duration,
        user_email,
    )

    redis_client = await get_redis_client()
    lock = redis_client.lock(
        f"telemetry_ingest_lock:{telemetry_log_id}",
        timeout=TELEMETRY_INGEST_TIMEOUT_SECONDS,
        blocking_timeout=10,
    )
    lock_wait_start = time.monotonic()
    acquired = await lock.acquire(blocking=True)
    lock_wait_seconds = time.monotonic() - lock_wait_start
    if not acquired:
        logger.error(
            "telemetry_ingest phase=acquire_lock telemetry_log_id=%s request_id=%s duration=%.3fs status=failed reason=contention",
            telemetry_log_id,
            request_id,
            lock_wait_seconds,
        )
        return
    if lock_wait_seconds >= INGEST_LOCK_WAIT_LOG_THRESHOLD_SECONDS:
        logger.warning(
            "telemetry_ingest phase=acquire_lock telemetry_log_id=%s request_id=%s duration=%.3fs status=delayed",
            telemetry_log_id,
            request_id,
            lock_wait_seconds,
        )

    try:
        async with mono_svc.db.session() as session:
            telemetry_svc = TelemetryService(session, mono_svc)
            accumulation_service = TelemetryAccumulationService(session)

        latest_status = await accumulation_service.get_latest_ingestion_status(telemetry_log_id)
        if latest_status and latest_status[0] == "processed":
            logger.info(
                "Telemetry ingest job %s already processed (request_id=%s)",
                telemetry_log_id,
                latest_status[1].get("request_id"),
            )
            return

        log_fetch_start = time.monotonic()
        telemetry_log = await telemetry_svc.get_telemetry_log(telemetry_log_id)
        log_fetch_duration = time.monotonic() - log_fetch_start
        if telemetry_log is None:
            logger.error("Telemetry ingest job %s: telemetry log not found", telemetry_log_id)
            return
        logger.info(
            "telemetry_ingest phase=fetch_log telemetry_log_id=%s request_id=%s duration=%.3fs",
            telemetry_log_id,
            request_id,
            log_fetch_duration,
        )

        log_data: Dict[str, Any] = telemetry_log.json_data or {}
        try:
            await accumulation_service.add_ingestion_status(
                telemetry_log_id,
                "processing",
                {"request_id": request_id},
                user.id,
            )

            decode_start = time.monotonic()
            raw_body = _decode_body(log_data)
            decode_duration = time.monotonic() - decode_start
            total_elapsed = time.monotonic() - start_monotonic
            logger.info(
                "telemetry_ingest phase=decode_body telemetry_log_id=%s request_id=%s duration=%.3fs total_elapsed=%.3fs",
                telemetry_log_id,
                request_id,
                decode_duration,
                total_elapsed,
            )
            if raw_body is not None:
                trace_data = telemetry_svc.parse_protobuf_traces(raw_body)
                compat_mode = False
            else:
                # Legacy telemetry logs stored parsed trace JSON directly
                trace_data = log_data
                compat_mode = True

            parse_start = time.monotonic()
            spans = await telemetry_svc.extract_spans(trace_data)
            parse_duration = time.monotonic() - parse_start
            collection_ids, collection_names = telemetry_svc.extract_collection_info_from_spans(
                spans
            )
            for span in spans:
                attrs = span.get("attributes", {})
                collection_attr = attrs.get("collection_id")
                agent_run_attr = attrs.get("agent_run_id")
                if isinstance(collection_attr, str) and isinstance(agent_run_attr, str):
                    agent_runs_by_collection[collection_attr].add(agent_run_attr)
            logger.info(
                "telemetry_ingest phase=parse_spans telemetry_log_id=%s request_id=%s duration=%.3fs spans=%s collections=%s",
                telemetry_log_id,
                request_id,
                parse_duration,
                len(spans),
                len(collection_ids),
            )

            perm_start = time.monotonic()
            await telemetry_svc.ensure_write_permission_for_collections(collection_ids, user)
            perm_duration = time.monotonic() - perm_start
            logger.info(
                "telemetry_ingest phase=validate_permissions telemetry_log_id=%s request_id=%s duration=%.3fs collections=%s",
                telemetry_log_id,
                request_id,
                perm_duration,
                len(collection_ids),
            )

            ensure_collections_start = time.monotonic()
            await telemetry_svc.ensure_collections_exist(collection_ids, collection_names, user)
            ensure_collections_duration = time.monotonic() - ensure_collections_start
            logger.info(
                "telemetry_ingest phase=ensure_collections telemetry_log_id=%s request_id=%s duration=%.3fs collections=%s",
                telemetry_log_id,
                request_id,
                ensure_collections_duration,
                len(collection_ids),
            )

            if collection_ids:
                primary_collection_id = next(iter(collection_ids))
                await telemetry_svc.update_telemetry_log_collection_id(
                    telemetry_log_id, primary_collection_id
                )
                await telemetry_svc.session.commit()

            logger.info(
                "telemetry_ingest phase=accumulation_start telemetry_log_id=%s request_id=%s total_elapsed=%.3fs",
                telemetry_log_id,
                request_id,
                time.monotonic() - start_monotonic,
            )
            accumulation_start = time.monotonic()
            await telemetry_svc.accumulate_spans(
                spans,
                user.id,
                accumulation_service,
                telemetry_log_id=telemetry_log_id,
                replace_existing_for_log=True,
            )
            accumulation_elapsed = time.monotonic() - accumulation_start
            total_elapsed = time.monotonic() - start_monotonic
            logger.info(
                "telemetry_ingest phase=accumulate_spans telemetry_log_id=%s request_id=%s duration=%.3fs total_elapsed=%.3fs spans=%s",
                telemetry_log_id,
                request_id,
                accumulation_elapsed,
                total_elapsed,
                len(spans),
            )

            for collection_id in collection_ids:
                try:
                    run_ids = agent_runs_by_collection.get(collection_id) or set()
                    if run_ids:
                        for agent_run_id in sorted(run_ids):
                            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                                collection_id, user, agent_run_id=agent_run_id
                            )
                    else:
                        await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                            collection_id, user
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Failed to trigger telemetry processing job for collection %s: %s",
                        collection_id,
                        exc,
                    )

            await accumulation_service.add_ingestion_status(
                telemetry_log_id,
                "processed",
                {
                    "spans": len(spans),
                    "collections": list(collection_ids),
                    "request_id": request_id,
                    "processing_seconds": round(time.time() - start_wall, 3),
                    "compat_mode": compat_mode,
                },
                user.id,
            )
            logger.info(
                "telemetry_ingest phase=completed telemetry_log_id=%s request_id=%s spans=%s collections=%s duration=%.3fs compat_mode=%s",
                telemetry_log_id,
                request_id,
                len(spans),
                len(collection_ids),
                time.time() - start_wall,
                compat_mode,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start_monotonic
            await accumulation_service.add_ingestion_status(
                telemetry_log_id,
                "failed",
                {"error": str(exc), "request_id": request_id, "elapsed_seconds": elapsed},
                user.id,
            )
            logger.error(
                "telemetry_ingest phase=failed telemetry_log_id=%s request_id=%s duration=%.3fs error=%s",
                telemetry_log_id,
                request_id,
                elapsed,
                exc,
                exc_info=True,
            )
            raise
    finally:
        try:
            await lock.release()
        except Exception as lock_exc:  # noqa: BLE001
            logger.warning(
                "Telemetry ingest job %s failed to release ingest lock: %s",
                telemetry_log_id,
                lock_exc,
            )
