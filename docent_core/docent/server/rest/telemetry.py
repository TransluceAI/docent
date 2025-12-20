import base64
import time
from typing import Any, Dict, Optional, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from docent._log_util import get_logger
from docent_core.docent.db.schemas.auth_models import Permission, User
from docent_core.docent.server.dependencies.database import require_collection_exists
from docent_core.docent.server.dependencies.permissions import require_collection_permission
from docent_core.docent.server.dependencies.services import (
    get_mono_svc,
    get_telemetry_accumulation_service,
    get_telemetry_service,
)
from docent_core.docent.server.dependencies.user import (
    get_authenticated_user,
    get_user_anonymous_ok,
)
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.telemetry import TelemetryService
from docent_core.docent.services.telemetry_accumulation import TelemetryAccumulationService

logger = get_logger(__name__)


telemetry_router = APIRouter()


def _get_request_id(request: Request) -> str:
    for header in ("x-docent-request-id", "x-request-id"):
        value = request.headers.get(header)
        if value:
            return value
    return str(uuid4())


def _success_response(
    content: Dict[str, Any], request_id: str, *, status_code: int = status.HTTP_200_OK
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"x-docent-request-id": request_id},
    )


def _telemetry_http_exception(
    *,
    request_id: str,
    status_code: int,
    message: str,
    error_code: str,
    hint: Optional[str] = None,
) -> HTTPException:
    detail: Dict[str, Any] = {
        "message": message,
        "error_code": error_code,
        "request_id": request_id,
    }
    if hint:
        detail["hint"] = hint
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"x-docent-request-id": request_id},
    )


def _http_exception_with_request_id(exc: HTTPException, request_id: str) -> HTTPException:
    headers = dict(exc.headers or {})
    headers.setdefault("x-docent-request-id", request_id)
    detail_value = exc.detail
    if isinstance(detail_value, dict):
        detail_dict: Dict[str, Any] = detail_value
        if "request_id" not in detail_dict:
            detail_dict = {**detail_dict, "request_id": request_id}
        detail_value = detail_dict
    return HTTPException(status_code=exc.status_code, detail=detail_value, headers=headers)


async def _parse_json_body(request: Request, request_id: str) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise _telemetry_http_exception(
            request_id=request_id,
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Request body must be valid JSON.",
            hint=str(exc),
            error_code="TELEMETRY_INVALID_JSON",
        ) from exc

    if not isinstance(payload, dict):
        raise _telemetry_http_exception(
            request_id=request_id,
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Request body must be a JSON object.",
            hint="Send a JSON object that includes the documented telemetry fields.",
            error_code="TELEMETRY_INVALID_JSON",
        )

    return cast(Dict[str, Any], payload)


def _find_null_character_path(value: Any, path: str = "") -> Optional[str]:
    if isinstance(value, str):
        if "\x00" in value or "\\u0000" in value or "\\x00" in value:
            return path or "<root>"
        return None

    if isinstance(value, dict):
        value_dict = cast(dict[str, Any], value)
        for key, nested in value_dict.items():
            nested_path = f"{path}.{key}" if path else str(key)
            result = _find_null_character_path(nested, nested_path)
            if result:
                return result
        return None

    if isinstance(value, list):
        value_list = cast(list[Any], value)
        for index, nested in enumerate(value_list):
            nested_path = f"{path}[{index}]" if path else f"[{index}]"
            result = _find_null_character_path(nested, nested_path)
            if result:
                return result
        return None

    return None


def _ensure_no_null_bytes(payload: Any, *, context: str, request_id: str) -> None:
    offending_path = _find_null_character_path(payload)
    if offending_path is not None:
        raise _telemetry_http_exception(
            request_id=request_id,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=f"{context} contains unsupported null characters at {offending_path}.",
            hint="Remove '\\u0000' or '\\x00' before sending telemetry to Docent.",
            error_code="TELEMETRY_NULL_CHARACTER",
        )


def _handle_unexpected_error(request_id: str, exc: Exception, context: str) -> None:
    logger.error("%s failed (request_id=%s): %s", context, request_id, exc, exc_info=True)
    raise _telemetry_http_exception(
        request_id=request_id,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message=f"{context} failed: {exc}",
        hint="Inspect Docent backend logs using the provided request ID.",
        error_code="TELEMETRY_INTERNAL_ERROR",
    ) from exc


@telemetry_router.post("/v1/traces")
async def trace_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    accumulation_service: TelemetryAccumulationService = Depends(
        get_telemetry_accumulation_service
    ),
    telemetry_svc: TelemetryService = Depends(get_telemetry_service),
):
    """
    Direct trace endpoint for OpenTelemetry collector HTTP exporter.

    This endpoint accepts OTLP HTTP format telemetry data and logs it.
    Requires authentication via bearer token (API key) in the Authorization header.
    """

    request_id = _get_request_id(request)
    start_time = time.time()
    telemetry_id: str | None = None

    try:
        content_type = request.headers.get("content-type", "")
        body = await request.body()
        content_encoding = request.headers.get("content-encoding")

        if "application/x-protobuf" not in content_type:
            raise _telemetry_http_exception(
                request_id=request_id,
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                message=f"Unsupported content type: {content_type or 'missing'}",
                hint="Use application/x-protobuf payloads produced by the OTLP HTTP exporter.",
                error_code="TELEMETRY_UNSUPPORTED_MEDIA_TYPE",
            )

        telemetry_payload = {
            "content_type": content_type,
            "content_encoding": content_encoding,
            "body_b64": base64.b64encode(body).decode("ascii"),
            "request_id": request_id,
        }

        telemetry_id = await telemetry_svc.store_telemetry_log(
            user.id,
            type="traces-ingest",
            version="v1",
            json_data=telemetry_payload,
        )
        await accumulation_service.add_ingestion_status(
            telemetry_id,
            "received",
            {
                "content_type": content_type,
                "content_encoding": content_encoding,
                "body_bytes": len(body),
                "request_id": request_id,
            },
            user.id,
        )

        job_id = await telemetry_svc.mono_svc.add_and_enqueue_telemetry_ingest_job(
            telemetry_id,
            user,
            request_id=request_id,
            content_type=content_type,
            content_encoding=content_encoding,
        )

        if job_id:
            await accumulation_service.add_ingestion_status(
                telemetry_id,
                "queued",
                {"job_id": job_id, "request_id": request_id},
                user.id,
            )

        return _success_response(
            {"status": "success", "telemetry_log_id": telemetry_id, "job_id": job_id},
            request_id,
        )
    except HTTPException as exc:
        raise _http_exception_with_request_id(exc, request_id)
    except Exception as exc:
        if telemetry_id:
            try:
                await accumulation_service.add_ingestion_status(
                    telemetry_id,
                    "failed",
                    {"error": str(exc), "request_id": request_id},
                    user.id,
                )
            except Exception as status_exc:
                logger.error(
                    "Failed to record ingestion failure for telemetry %s: %s",
                    telemetry_id,
                    status_exc,
                )
        processing_time = time.time() - start_time
        _handle_unexpected_error(
            request_id,
            exc,
            f"Queuing OTLP traces after {processing_time:.3f}s",
        )


@telemetry_router.post("/v1/trace-done")
async def trace_done_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    telemetry_svc: TelemetryService = Depends(get_telemetry_service),
):
    """
    Endpoint to signal that a trace is complete.

    When called, we wait a bit to see if new spans come in, then process the trace.
    """
    request_id = _get_request_id(request)

    try:
        body = await _parse_json_body(request, request_id)
        _ensure_no_null_bytes(body, context="Trace completion payload", request_id=request_id)

        collection_id = body.get("collection_id")

        if not isinstance(collection_id, str) or not collection_id:
            raise _telemetry_http_exception(
                request_id=request_id,
                status_code=status.HTTP_400_BAD_REQUEST,
                message="collection_id is required.",
                hint="Include collection_id in the JSON body when invoking /v1/trace-done.",
                error_code="TELEMETRY_MISSING_FIELDS",
            )

        await telemetry_svc.ensure_collection_exists(collection_id, user)
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        telemetry_data = {
            "endpoint": "/v1/trace-done",
            "collection_id": collection_id,
            "request_body": body,
        }
        await telemetry_svc.store_telemetry_log(
            user.id,
            type="trace-done",
            version="v1",
            json_data=telemetry_data,
            collection_id=collection_id,
        )

        return _success_response({"status": "success", "collection_id": collection_id}, request_id)

    except HTTPException as exc:
        raise _http_exception_with_request_id(exc, request_id)
    except Exception as exc:
        _handle_unexpected_error(request_id, exc, "Processing trace-done request")


@telemetry_router.post("/v1/scores")
async def add_score_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    accumulation_service: TelemetryAccumulationService = Depends(
        get_telemetry_accumulation_service
    ),
    telemetry_svc: TelemetryService = Depends(get_telemetry_service),
):
    """
    Endpoint to add a score to an agent run.

    The score will be stored and applied when the collection is processed.
    """
    request_id = _get_request_id(request)

    try:
        body = await _parse_json_body(request, request_id)
        _ensure_no_null_bytes(body, context="Score payload", request_id=request_id)

        collection_id = body.get("collection_id")
        agent_run_id = body.get("agent_run_id")
        score_name = body.get("score_name")
        score_value = body.get("score_value")
        timestamp = body.get("timestamp")

        missing_fields: list[str] = []
        if not isinstance(collection_id, str) or not collection_id:
            missing_fields.append("collection_id")
        if not isinstance(agent_run_id, str) or not agent_run_id:
            missing_fields.append("agent_run_id")
        if not isinstance(score_name, str) or not score_name:
            missing_fields.append("score_name")
        if score_value is None:
            missing_fields.append("score_value")
        if not isinstance(timestamp, str) or not timestamp:
            missing_fields.append("timestamp")

        if missing_fields:
            raise _telemetry_http_exception(
                request_id=request_id,
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"Missing required fields: {', '.join(missing_fields)}.",
                hint="Provide collection_id, agent_run_id, score_name, score_value, and timestamp.",
                error_code="TELEMETRY_MISSING_FIELDS",
            )

        collection_id = cast(str, collection_id)
        agent_run_id = cast(str, agent_run_id)
        score_name = cast(str, score_name)
        timestamp = cast(str, timestamp)

        await telemetry_svc.ensure_collection_exists(collection_id, user)
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        await telemetry_svc.store_telemetry_log(
            user.id,
            type="scores",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        await accumulation_service.add_score(
            collection_id, agent_run_id, score_name, score_value, timestamp, user.id
        )

        try:
            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                collection_id, user, agent_run_id=agent_run_id
            )
        except Exception as exc:
            logger.error(
                "Failed to trigger telemetry processing job for collection %s: %s",
                collection_id,
                exc,
            )

        return _success_response({"status": "success"}, request_id)

    except HTTPException as exc:
        raise _http_exception_with_request_id(exc, request_id)
    except Exception as exc:
        _handle_unexpected_error(request_id, exc, "Adding agent run score")


@telemetry_router.post("/v1/agent-run-metadata")
async def add_metadata_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    accumulation_service: TelemetryAccumulationService = Depends(
        get_telemetry_accumulation_service
    ),
    telemetry_svc: TelemetryService = Depends(get_telemetry_service),
):
    """
    Endpoint to add metadata to an agent run.

    The metadata will be stored and applied when the collection is processed.
    """
    request_id = _get_request_id(request)

    try:
        body = await _parse_json_body(request, request_id)
        _ensure_no_null_bytes(body, context="Agent run metadata payload", request_id=request_id)

        collection_id = body.get("collection_id")
        agent_run_id = body.get("agent_run_id")
        metadata = body.get("metadata")
        timestamp = body.get("timestamp")

        missing_fields: list[str] = []
        if not isinstance(collection_id, str) or not collection_id:
            missing_fields.append("collection_id")
        if not isinstance(agent_run_id, str) or not agent_run_id:
            missing_fields.append("agent_run_id")
        if not isinstance(metadata, dict):
            missing_fields.append("metadata")
        if not isinstance(timestamp, str) or not timestamp:
            missing_fields.append("timestamp")

        if missing_fields:
            raise _telemetry_http_exception(
                request_id=request_id,
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"Missing required fields: {', '.join(missing_fields)}.",
                hint="Provide collection_id, agent_run_id, metadata, and timestamp.",
                error_code="TELEMETRY_MISSING_FIELDS",
            )

        collection_id = cast(str, collection_id)
        agent_run_id = cast(str, agent_run_id)
        metadata = cast(Dict[str, Any], metadata)
        timestamp = cast(str, timestamp)

        await telemetry_svc.ensure_collection_exists(collection_id, user)
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        await telemetry_svc.store_telemetry_log(
            user.id,
            type="metadata",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        await accumulation_service.add_agent_run_metadata(
            collection_id, agent_run_id, metadata, timestamp, user.id
        )

        try:
            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                collection_id, user, agent_run_id=agent_run_id
            )
        except Exception as exc:
            logger.error(
                "Failed to trigger telemetry processing job for collection %s: %s",
                collection_id,
                exc,
            )

        return _success_response({"status": "success"}, request_id)

    except HTTPException as exc:
        raise _http_exception_with_request_id(exc, request_id)
    except Exception as exc:
        _handle_unexpected_error(request_id, exc, "Adding agent run metadata")


@telemetry_router.post("/v1/transcript-metadata")
async def add_transcript_metadata_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    accumulation_service: TelemetryAccumulationService = Depends(
        get_telemetry_accumulation_service
    ),
    telemetry_svc: TelemetryService = Depends(get_telemetry_service),
):
    """
    Endpoint to add metadata to a transcript.

    The metadata will be stored and applied when the collection is processed.
    """
    request_id = _get_request_id(request)

    try:
        body = await _parse_json_body(request, request_id)
        _ensure_no_null_bytes(body, context="Transcript metadata payload", request_id=request_id)

        collection_id = body.get("collection_id")
        transcript_id = body.get("transcript_id")
        name = body.get("name")
        description = body.get("description")
        transcript_group_id = body.get("transcript_group_id")
        metadata = body.get("metadata")
        timestamp = body.get("timestamp")

        missing_fields: list[str] = []
        if not isinstance(collection_id, str) or not collection_id:
            missing_fields.append("collection_id")
        if not isinstance(transcript_id, str) or not transcript_id:
            missing_fields.append("transcript_id")
        if not isinstance(timestamp, str) or not timestamp:
            missing_fields.append("timestamp")

        if missing_fields:
            raise _telemetry_http_exception(
                request_id=request_id,
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"Missing required fields: {', '.join(missing_fields)}.",
                hint="Provide collection_id, transcript_id, and timestamp.",
                error_code="TELEMETRY_MISSING_FIELDS",
            )

        collection_id = cast(str, collection_id)
        transcript_id = cast(str, transcript_id)
        timestamp = cast(str, timestamp)

        await telemetry_svc.ensure_collection_exists(collection_id, user)
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        await telemetry_svc.store_telemetry_log(
            user.id,
            type="transcript-metadata",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        await accumulation_service.add_transcript_metadata(
            collection_id,
            transcript_id,
            name,
            description,
            transcript_group_id,
            metadata,
            timestamp,
            user.id,
        )

        try:
            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                collection_id, user
            )
        except Exception as exc:
            logger.error(
                "Failed to trigger telemetry processing job for collection %s: %s",
                collection_id,
                exc,
            )

        return _success_response({"status": "success"}, request_id)

    except HTTPException as exc:
        raise _http_exception_with_request_id(exc, request_id)
    except Exception as exc:
        _handle_unexpected_error(request_id, exc, "Adding transcript metadata")


@telemetry_router.post("/v1/transcript-group-metadata")
async def add_transcript_group_metadata_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    accumulation_service: TelemetryAccumulationService = Depends(
        get_telemetry_accumulation_service
    ),
    telemetry_svc: TelemetryService = Depends(get_telemetry_service),
):
    """
    Endpoint to add metadata to a transcript group.

    The metadata will be stored and applied when the collection is processed.
    """
    request_id = _get_request_id(request)

    try:
        body = await _parse_json_body(request, request_id)
        _ensure_no_null_bytes(
            body, context="Transcript group metadata payload", request_id=request_id
        )

        collection_id = body.get("collection_id")
        agent_run_id = body.get("agent_run_id")
        transcript_group_id = body.get("transcript_group_id")
        name = body.get("name")
        description = body.get("description")
        parent_transcript_group_id = body.get("parent_transcript_group_id")
        metadata = body.get("metadata")
        timestamp = body.get("timestamp")

        missing_fields: list[str] = []
        if not isinstance(collection_id, str) or not collection_id:
            missing_fields.append("collection_id")
        if not isinstance(transcript_group_id, str) or not transcript_group_id:
            missing_fields.append("transcript_group_id")
        if not isinstance(agent_run_id, str) or not agent_run_id:
            missing_fields.append("agent_run_id")
        if not isinstance(timestamp, str) or not timestamp:
            missing_fields.append("timestamp")

        if missing_fields:
            raise _telemetry_http_exception(
                request_id=request_id,
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"Missing required fields: {', '.join(missing_fields)}.",
                hint="Provide collection_id, transcript_group_id, agent_run_id, and timestamp.",
                error_code="TELEMETRY_MISSING_FIELDS",
            )

        collection_id = cast(str, collection_id)
        agent_run_id = cast(str, agent_run_id)
        transcript_group_id = cast(str, transcript_group_id)
        timestamp = cast(str, timestamp)

        await telemetry_svc.ensure_collection_exists(collection_id, user)
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        await telemetry_svc.store_telemetry_log(
            user.id,
            type="transcript-group-metadata",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        await accumulation_service.add_transcript_group_metadata(
            collection_id,
            agent_run_id,
            transcript_group_id,
            name,
            description,
            parent_transcript_group_id,
            metadata,
            timestamp,
            user.id,
        )

        try:
            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                collection_id, user, agent_run_id=agent_run_id
            )
        except Exception as exc:
            logger.error(
                "Failed to trigger telemetry processing job for collection %s: %s",
                collection_id,
                exc,
            )

        return _success_response({"status": "success"}, request_id)

    except HTTPException as exc:
        raise _http_exception_with_request_id(exc, request_id)
    except Exception as exc:
        _handle_unexpected_error(request_id, exc, "Adding transcript group metadata")


@telemetry_router.post("/{collection_id}/ensure-telemetry-processing")
async def ensure_telemetry_processing(
    collection_id: str = Depends(require_collection_exists),
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """
    Ensure telemetry processing is queued for a collection if there's remaining work.
    This endpoint is called when a user accesses a collection to trigger background processing.
    """
    logger.info(
        f"ensure_telemetry_processing endpoint called for collection {collection_id} by user {user.email}"
    )
    try:
        from docent_core.docent.services.telemetry import TelemetryService

        async with mono_svc.db.session() as session:
            telemetry_svc = TelemetryService(session, mono_svc)
            job_id = await telemetry_svc.ensure_telemetry_processing_for_collection_as_owner(
                collection_id
            )

            if job_id:
                logger.info(
                    f"Triggered telemetry processing job {job_id} for collection {collection_id}"
                )
            else:
                logger.debug(f"No telemetry processing needed for collection {collection_id}")

    except Exception as e:
        logger.error(f"Failed to ensure telemetry processing for collection {collection_id}: {e}")


@telemetry_router.get("/{collection_id}/transcripts/{transcript_id}/messages/{message_id}/otel")
async def get_message_otel(
    transcript_id: str,
    message_id: str,
    collection_id: str = Depends(require_collection_exists),
    _: None = Depends(require_collection_permission(Permission.READ)),
    telemetry_svc: TelemetryService = Depends(get_telemetry_service),
) -> Dict[str, Any]:
    """
    Fetch the OpenTelemetry span payload associated with a transcript message.

    The linkage is maintained via SQLATelemetryLineage rows written during telemetry processing.
    """
    payload = await telemetry_svc.get_message_otel_payload(
        collection_id=collection_id,
        transcript_id=transcript_id,
        message_id=message_id,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Telemetry span payload not found.")
    return payload
