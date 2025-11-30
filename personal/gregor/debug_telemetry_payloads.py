#!/usr/bin/env python3
"""
Fetch telemetry logs with an arbitrary SQL statement and dump decoded OTLP payloads to disk.

The script expects the SQL to return rows that include at least `id` and `json_data`.
If json_data contains a base64-encoded OTLP protobuf body (optionally gzip-compressed),
it is decoded, decompressed, and converted to JSON using TelemetryService helpers.
Each row is written to a JSON file alongside an optional binary body dump for deeper inspection.
"""

import argparse
import asyncio
import base64
import gzip
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text

from docent._log_util import get_logger
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.telemetry import TelemetryService

logger = get_logger(__name__)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_filename(value: Any, fallback: str) -> str:
    text_value = str(value or fallback)
    sanitized = "".join(ch for ch in text_value if ch.isalnum() or ch in ("-", "_"))
    return sanitized or fallback


def _redact_body_b64(json_data: Any) -> Any:
    if not isinstance(json_data, dict):
        return json_data
    redacted = dict(json_data)
    body_b64 = redacted.get("body_b64")
    if isinstance(body_b64, str):
        redacted["body_b64"] = f"<omitted: {len(body_b64)} chars>"
    elif body_b64 is not None:
        redacted["body_b64"] = "<omitted>"
    return redacted


def _decode_body(log_data: Mapping[str, Any]) -> tuple[bytes | None, str | None]:
    body_b64 = log_data.get("body_b64")
    if not isinstance(body_b64, str) or not body_b64:
        return None, None

    try:
        raw_body = base64.b64decode(body_b64)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to base64 decode body: %s", exc)
        return None, "base64_decode_failed"

    content_encoding = log_data.get("content_encoding")
    if content_encoding == "gzip":
        try:
            raw_body = gzip.decompress(raw_body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to gunzip body: %s", exc)
            return None, "gunzip_failed"

    return raw_body, None


def _parse_trace_payload(
    telemetry_svc: TelemetryService,
    log_data: Mapping[str, Any],
    raw_body: bytes | None,
) -> tuple[Any, str | None]:
    if raw_body is not None:
        try:
            return telemetry_svc.parse_protobuf_traces(raw_body), None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse protobuf traces: %s", exc)
            return None, f"protobuf_parse_failed: {exc}"

    if isinstance(log_data, dict):
        return log_data, None

    return None, "json_data_not_dict"


async def dump_telemetry_payloads(sql: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    mono_svc = await MonoService.init()
    async with mono_svc.db.session() as session:
        telemetry_svc = TelemetryService(session, mono_svc)
        result = await session.execute(text(sql))
        rows = result.mappings().all()

        if not rows:
            logger.info("No rows returned by SQL query")
            return

        for index, row in enumerate(rows, start=1):
            row_map: Mapping[str, Any] = row
            telemetry_id = row_map.get("id") or f"row_{index}"
            log_data = row_map.get("json_data") or {}
            if not isinstance(log_data, dict):
                logger.warning("Row %s missing json_data dict, skipping", telemetry_id)
                continue

            raw_body, decode_error = _decode_body(log_data)
            parsed_trace, parse_error = _parse_trace_payload(telemetry_svc, log_data, raw_body)

            safe_id = _safe_filename(telemetry_id, f"row_{index}")
            body_path: Path | None = None
            if raw_body is not None:
                body_path = output_dir / f"{index:04d}_{safe_id}.otlp"
                body_path.write_bytes(raw_body)

            payload = {
                "id": telemetry_id,
                "type": row_map.get("type"),
                "version": row_map.get("version"),
                "collection_id": row_map.get("collection_id"),
                "created_at": row_map.get("created_at"),
                "content_type": log_data.get("content_type"),
                "content_encoding": log_data.get("content_encoding"),
                "request_id": log_data.get("request_id"),
                "body_b64_length": len(log_data.get("body_b64")) if log_data.get("body_b64") else 0,
                "raw_body_file": str(body_path) if body_path else None,
                "decode_error": decode_error,
                "parse_error": parse_error,
                "parsed_trace": parsed_trace,
                "json_data": _redact_body_b64(log_data),
            }

            payload_path = output_dir / f"{index:04d}_{safe_id}.json"
            payload_path.write_text(json.dumps(payload, indent=2, default=_json_default), "utf-8")
            logger.info("Wrote %s", payload_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Decode raw telemetry payloads returned by an arbitrary SQL query."
    )
    parser.add_argument(
        "--sql",
        required=True,
        help="SQL statement that returns telemetry rows (must include json_data).",
    )
    parser.add_argument(
        "--output-dir",
        default="telemetry_payloads",
        type=Path,
        help="Directory to write decoded payloads into (default: telemetry_payloads).",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    asyncio.run(dump_telemetry_payloads(args.sql, args.output_dir))


if __name__ == "__main__":
    main()
