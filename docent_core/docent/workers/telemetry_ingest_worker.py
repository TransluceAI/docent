"""
Telemetry ingest worker.

Moves CPU-heavy OTLP parsing and span accumulation off the request path.
"""

import base64
import gzip
import time
from typing import Any, Dict, Optional

from docent._log_util import get_logger
from docent_core.docent.db.contexts import TelemetryContext
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.telemetry import TelemetryService
from docent_core.docent.services.telemetry_accumulation import TelemetryAccumulationService

logger = get_logger(__name__)


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

    if not telemetry_log_id:
        logger.error("Telemetry ingest job missing telemetry_log_id")
        return

    if not user_email:
        logger.error("Telemetry ingest job missing user_email")
        return

    start_wall = time.time()
    start_monotonic = time.monotonic()
    mono_svc = await MonoService.init()
    user = await mono_svc.get_user_by_email(user_email)
    if user is None:
        logger.error("Telemetry ingest job %s: user %s not found", telemetry_log_id, user_email)
        return

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

        telemetry_log = await telemetry_svc.get_telemetry_log(telemetry_log_id)
        if telemetry_log is None:
            logger.error("Telemetry ingest job %s: telemetry log not found", telemetry_log_id)
            return

        log_data: Dict[str, Any] = telemetry_log.json_data or {}
        try:
            await accumulation_service.add_ingestion_status(
                telemetry_log_id,
                "processing",
                {"request_id": request_id},
                user.id,
            )

            raw_body = _decode_body(log_data)
            logger.info(
                "Telemetry ingest job %s decoded body (request_id=%s) in %.3fs",
                telemetry_log_id,
                request_id,
                time.monotonic() - start_monotonic,
            )
            if raw_body is not None:
                trace_data = telemetry_svc.parse_protobuf_traces(raw_body)
                compat_mode = False
            else:
                # Legacy telemetry logs stored parsed trace JSON directly
                trace_data = log_data
                compat_mode = True

            spans = await telemetry_svc.extract_spans(trace_data)
            collection_ids, collection_names = telemetry_svc.extract_collection_info_from_spans(
                spans
            )
            logger.info(
                "Telemetry ingest job %s parsed %s spans across %s collections (request_id=%s) in %.3fs",
                telemetry_log_id,
                len(spans),
                len(collection_ids),
                request_id,
                time.monotonic() - start_monotonic,
            )

            await telemetry_svc.ensure_write_permission_for_collections(collection_ids, user)
            await telemetry_svc.ensure_collections_exist(collection_ids, collection_names, user)

            if collection_ids:
                primary_collection_id = next(iter(collection_ids))
                await telemetry_svc.update_telemetry_log_collection_id(
                    telemetry_log_id, primary_collection_id
                )
                await telemetry_svc.session.commit()

            logger.info(
                "Telemetry ingest job %s beginning accumulation (request_id=%s) at %.3fs elapsed",
                telemetry_log_id,
                request_id,
                time.monotonic() - start_monotonic,
            )
            await telemetry_svc.accumulate_spans(
                spans,
                user.id,
                accumulation_service,
                telemetry_log_id=telemetry_log_id,
                replace_existing_for_log=True,
            )

            for collection_id in collection_ids:
                try:
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
                "Telemetry ingest job %s processed %s spans across %s collections in %.3fs",
                telemetry_log_id,
                len(spans),
                len(collection_ids),
                time.time() - start_wall,
            )
        except TimeoutError as exc:
            elapsed = time.monotonic() - start_monotonic
            await accumulation_service.add_ingestion_status(
                telemetry_log_id,
                "failed",
                {"error": f"timeout after {elapsed:.3f}s", "request_id": request_id},
                user.id,
            )
            logger.error(
                "Telemetry ingest job %s timed out after %.3fs (request_id=%s): %s",
                telemetry_log_id,
                elapsed,
                request_id,
                exc,
                exc_info=True,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start_monotonic
            await accumulation_service.add_ingestion_status(
                telemetry_log_id,
                "failed",
                {"error": str(exc), "request_id": request_id, "elapsed_seconds": elapsed},
                user.id,
            )
            logger.error(
                "Telemetry ingest job %s failed after %.3fs (request_id=%s): %s",
                telemetry_log_id,
                elapsed,
                request_id,
                exc,
                exc_info=True,
            )
            raise
