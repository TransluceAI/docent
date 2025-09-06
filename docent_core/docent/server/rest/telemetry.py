from fastapi import APIRouter, Depends, HTTPException, Request
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
    try:
        # Check content type
        content_type = request.headers.get("content-type", "")

        # Read the request body
        body = await request.body()

        # Handle compressed data if needed
        if request.headers.get("content-encoding") == "gzip":
            import gzip

            body = gzip.decompress(body)

        if "application/x-protobuf" in content_type:
            trace_data = telemetry_svc.parse_protobuf_traces(body)
        else:
            raise HTTPException(status_code=415, detail=f"Unsupported content type: {content_type}")

        # Store the raw telemetry data for request
        await telemetry_svc.store_telemetry_log(
            user.id,
            type="traces",
            version="v1",
            json_data=trace_data,
        )

        # Extract spans and accumulate them
        spans = await telemetry_svc.extract_spans(trace_data)

        # Extract unique collection IDs from spans
        collection_ids, collection_names = telemetry_svc.extract_collection_info_from_spans(spans)

        # Check permissions for all collections mentioned in spans
        await telemetry_svc.ensure_write_permission_for_collections(collection_ids, user)

        # Ensure collections exist
        await telemetry_svc.ensure_collections_exist(collection_ids, collection_names, user)

        # Accumulate spans into database
        await telemetry_svc.accumulate_spans(spans, user.id, accumulation_service)

        # Trigger background processing jobs for each collection
        for collection_id in collection_ids:
            try:
                await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                    collection_id, user
                )
            except Exception as e:
                logger.error(
                    f"Failed to trigger telemetry processing job for collection {collection_id}: {str(e)}"
                )
                # Continue with other collections even if job creation fails

        # Return success response
        return JSONResponse(
            status_code=200, content={"status": "success", "spans_accumulated": len(spans)}
        )
    except Exception as e:
        logger.error(f"Error processing traces: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
    try:
        # Parse request body
        body = await request.json()
        collection_id = body.get("collection_id")

        if not collection_id:
            raise HTTPException(status_code=400, detail="collection_id is required")

        # Create collection with default name if it doesn't exist
        await telemetry_svc.ensure_collection_exists(collection_id, user)

        # Check if collection exists and user has permissions
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        # Store telemetry log for this request
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

        # Trigger background processing job
        try:
            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                collection_id, user
            )
        except Exception as e:
            logger.error(
                f"Failed to trigger telemetry processing job for collection {collection_id}: {str(e)}"
            )

        return JSONResponse(
            status_code=200, content={"status": "success", "collection_id": collection_id}
        )

    except Exception as e:
        logger.error(f"Error processing trace-done: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
    try:
        # Parse request body
        body = await request.json()
        collection_id = body.get("collection_id")
        agent_run_id = body.get("agent_run_id")
        score_name = body.get("score_name")
        score_value = body.get("score_value")
        timestamp = body.get("timestamp")

        if not all([collection_id, agent_run_id, score_name, score_value is not None, timestamp]):
            raise HTTPException(
                status_code=400,
                detail="collection_id, agent_run_id, score_name, score_value, and timestamp are required",
            )

        # Create collection with default name if it doesn't exist
        await telemetry_svc.ensure_collection_exists(collection_id, user)

        # Check if collection exists and user has permissions
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        # Store telemetry log for this request
        await telemetry_svc.store_telemetry_log(
            user.id,
            type="scores",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        # Store score in database
        await accumulation_service.add_score(
            collection_id, agent_run_id, score_name, score_value, timestamp, user.id
        )

        # Trigger background processing job
        try:
            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                collection_id, user
            )
        except Exception as e:
            logger.error(
                f"Failed to trigger telemetry processing job for collection {collection_id}: {str(e)}"
            )

        return JSONResponse(status_code=200, content={"status": "success"})

    except Exception as e:
        logger.error(f"Error adding score: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
    try:
        # Parse request body
        body = await request.json()
        collection_id = body.get("collection_id")
        agent_run_id = body.get("agent_run_id")
        metadata = body.get("metadata")
        timestamp = body.get("timestamp")

        if not all([collection_id, agent_run_id, metadata, timestamp]):
            raise HTTPException(
                status_code=400,
                detail="collection_id, agent_run_id, metadata, and timestamp are required",
            )

        # Create collection with default name if it doesn't exist
        await telemetry_svc.ensure_collection_exists(collection_id, user)

        # Check if collection exists and user has permissions
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        # Store telemetry log for this request
        await telemetry_svc.store_telemetry_log(
            user.id,
            type="metadata",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        # Store metadata in database
        await accumulation_service.add_agent_run_metadata(
            collection_id, agent_run_id, metadata, timestamp, user.id
        )

        # Trigger background processing job
        try:
            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                collection_id, user
            )
        except Exception as e:
            logger.error(
                f"Failed to trigger telemetry processing job for collection {collection_id}: {str(e)}"
            )

        return JSONResponse(status_code=200, content={"status": "success"})

    except Exception as e:
        logger.error(f"Error adding metadata: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
    try:
        # Parse request body
        body = await request.json()
        collection_id = body.get("collection_id")
        transcript_id = body.get("transcript_id")
        name = body.get("name")
        description = body.get("description")
        transcript_group_id = body.get("transcript_group_id")
        metadata = body.get("metadata")
        timestamp = body.get("timestamp")

        if not all([collection_id, transcript_id, timestamp]):
            raise HTTPException(
                status_code=400, detail="collection_id, transcript_id, and timestamp are required"
            )

        # Create collection with default name if it doesn't exist
        await telemetry_svc.ensure_collection_exists(collection_id, user)

        # Check if collection exists and user has permissions
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        # Store telemetry log for this request
        await telemetry_svc.store_telemetry_log(
            user.id,
            type="transcript-metadata",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        # Store transcript metadata in database
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

        # Trigger background processing job
        try:
            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                collection_id, user
            )
        except Exception as e:
            logger.error(
                f"Failed to trigger telemetry processing job for collection {collection_id}: {str(e)}"
            )

        return JSONResponse(status_code=200, content={"status": "success"})

    except Exception as e:
        logger.error(f"Error adding transcript metadata: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
    try:
        # Parse request body
        body = await request.json()
        collection_id = body.get("collection_id")
        agent_run_id = body.get("agent_run_id")
        transcript_group_id = body.get("transcript_group_id")
        name = body.get("name")
        description = body.get("description")
        parent_transcript_group_id = body.get("parent_transcript_group_id")
        metadata = body.get("metadata")
        timestamp = body.get("timestamp")

        if not all([collection_id, transcript_group_id, agent_run_id, timestamp]):
            missing_fields = [
                field
                for field, value in [
                    ("collection_id", collection_id),
                    ("transcript_group_id", transcript_group_id),
                    ("agent_run_id", agent_run_id),
                    ("timestamp", timestamp),
                ]
                if not value
            ]
            if missing_fields:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required fields: {', '.join(missing_fields)}",
                )

        # Create collection with default name if it doesn't exist
        await telemetry_svc.ensure_collection_exists(collection_id, user)

        # Check if collection exists and user has permissions
        await telemetry_svc.ensure_write_permission_for_collection(collection_id, user)

        # Store telemetry log for this request
        await telemetry_svc.store_telemetry_log(
            user.id,
            type="transcript-group-metadata",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        # Store transcript group metadata in database
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

        # Trigger background processing job
        try:
            await telemetry_svc.mono_svc.add_and_enqueue_telemetry_processing_job(
                collection_id, user
            )
        except Exception as e:
            logger.error(
                f"Failed to trigger telemetry processing job for collection {collection_id}: {str(e)}"
            )

        return JSONResponse(status_code=200, content={"status": "success"})

    except Exception as e:
        logger.error(f"Error adding transcript group metadata: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@telemetry_router.post("/{collection_id}/ensure-telemetry-processing")
async def ensure_telemetry_processing(
    collection_id: str = Depends(require_collection_exists),
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
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
            job_id = await telemetry_svc.ensure_telemetry_processing_for_collection(
                collection_id, user
            )

            if job_id:
                logger.info(
                    f"Triggered telemetry processing job {job_id} for collection {collection_id}"
                )
            else:
                logger.debug(f"No telemetry processing needed for collection {collection_id}")

    except Exception as e:
        logger.error(f"Failed to ensure telemetry processing for collection {collection_id}: {e}")
