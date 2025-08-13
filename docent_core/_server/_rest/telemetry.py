import asyncio
import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from docent._log_util import get_logger
from docent.data_models import (
    AgentRun,
    Transcript,
    TranscriptGroup,
)
from docent.data_models.chat import ChatMessage, parse_chat_message
from docent.data_models.chat.tool import ToolCall
from docent_core._db_service.schemas.auth_models import User
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server._broker.redis_client import get_redis_client
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.database import get_mono_svc
from docent_core.docent.server.dependencies.user import get_authenticated_user
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)
# logger.setLevel(logging.DEBUG)

# Redis key patterns for collection accumulation
_COLLECTION_SPANS_KEY_PREFIX = "collection_spans:"
_COLLECTION_TIMEOUT_KEY_PREFIX = "collection_timeout:"
_COLLECTION_SCORES_KEY_PREFIX = "collection_scores:"
_COLLECTION_METADATA_KEY_PREFIX = "collection_metadata:"
_COLLECTION_TRANSCRIPT_METADATA_KEY_PREFIX = "collection_transcript_metadata:"
_COLLECTION_TRANSCRIPT_GROUP_METADATA_KEY_PREFIX = "collection_transcript_group_metadata:"
_STORE_SPANS_LOCK_PREFIX = "store_spans:"


telemetry_router = APIRouter()

raise Exception(
    "This file is deprecated. Import and apply changes to docent_core.docent.server.rest.telemetry instead."
)


@telemetry_router.post("/v1/traces")
async def trace_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
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
            trace_data = parse_protobuf_traces(body)
        else:
            raise HTTPException(status_code=415, detail=f"Unsupported content type: {content_type}")

        # Store the raw telemetry data for request
        await mono_svc.store_telemetry_log(
            user.id,
            type="traces",
            version="v1",
            json_data=trace_data,
        )

        count_spans = await handle_trace_data(trace_data, user, mono_svc, analytics)

        # Return success response
        return JSONResponse(
            status_code=200, content={"status": "success", "processed": count_spans}
        )
    except Exception as e:
        logger.error(f"Error processing traces: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def handle_trace_data(
    trace_data: Dict[str, Any], user: User, mono_svc: MonoService, analytics: AnalyticsClient
) -> int:

    # Extract spans from trace data
    spans = await extract_spans(trace_data)

    # Extract unique collection IDs and names from spans
    collection_ids, collection_names = extract_collection_info_from_spans(spans)

    # Check permissions for all collections mentioned in spans
    await _check_collection_permissions(collection_ids, user, mono_svc)

    await _ensure_collections_exists(collection_ids, collection_names, user, mono_svc)

    # Accumulate spans into Redis
    await accumulate_spans(spans)

    # Check completion for each collection
    for collection_id in collection_ids:
        accumulated_spans = await _get_accumulated_spans(collection_id)

        if not is_collection_complete(accumulated_spans):
            continue

        # Process the completed collection with all accumulated spans
        await process_completed_collection(collection_id, accumulated_spans, user, analytics)
        return len(spans)

    # Incrementally store spans for each collection
    for collection_id in collection_ids:
        # Get Redis lock for this collection
        redis_client = await get_redis_client()
        lock_key = f"{_STORE_SPANS_LOCK_PREFIX}{collection_id}"

        # Use lock as async context manager
        async with redis_client.lock(lock_key, blocking=False):
            # Lock acquired, process spans
            accumulated_spans = await _get_accumulated_spans(collection_id)

            if accumulated_spans:
                logger.info(
                    f"Processing collection {collection_id} with {len(accumulated_spans)} spans"
                )
                count_agent_runs = await store_spans(accumulated_spans, user)
                logger.info(
                    f"Successfully processed collection {collection_id} with {count_agent_runs} agent runs"
                )
            else:
                logger.info(f"No accumulated spans for collection {collection_id}")

    return len(spans)


def extract_collection_info_from_spans(
    spans: List[Dict[str, Any]],
) -> tuple[set[str], Dict[str, str]]:
    """
    Extract unique collection IDs and names from spans.

    Args:
        spans: List of processed spans

    Returns:
        Tuple of (collection_ids, collection_names)
    """
    collection_ids: set[str] = set()
    collection_names: Dict[str, str] = {}

    for span in spans:
        span_attrs = span.get("attributes", {})
        collection_id = span_attrs.get("collection_id")
        if collection_id and isinstance(collection_id, str):
            collection_ids.add(collection_id)

            # Extract collection name from service.name if not already found
            if collection_id not in collection_names:
                resource_attributes = span.get("resource_attributes", {})
                service_name = resource_attributes.get("service.name", "")
                if service_name:
                    collection_names[collection_id] = service_name

    return collection_ids, collection_names


@telemetry_router.post("/v1/trace-done")
async def trace_done_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """
    Endpoint to signal that a trace is complete.

    This is an alternative way to detect collection completion.
    When called, we wait a bit to see if new spans come in, then process the trace.
    """
    try:
        # Parse request body
        body = await request.json()
        collection_id = body.get("collection_id")

        if not collection_id:
            raise HTTPException(status_code=400, detail="collection_id is required")

        # Check if collection exists and user has permissions
        await _check_single_collection_permission(collection_id, user)

        # Store telemetry log for this request
        telemetry_data = {
            "endpoint": "/v1/trace-done",
            "collection_id": collection_id,
            "request_body": body,
        }
        await mono_svc.store_telemetry_log(
            user.id,
            type="trace-done",
            version="v1",
            json_data=telemetry_data,
            collection_id=collection_id,
        )

        # Schedule processing with a small delay to allow for late-arriving spans
        asyncio.create_task(_process_trace_done_with_delay(collection_id, user, analytics))

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
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """
    Endpoint to add a score to an agent run.

    The score will be stored in Redis and applied when the collection is processed.
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

        # Check if collection exists and user has permissions
        await _check_single_collection_permission(collection_id, user)

        # Store telemetry log for this request
        await mono_svc.store_telemetry_log(
            user.id,
            type="scores",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        # Store score in Redis
        await _store_agent_run_score(
            collection_id, agent_run_id, score_name, score_value, timestamp
        )

        return JSONResponse(status_code=200, content={"status": "success"})

    except Exception as e:
        logger.error(f"Error adding score: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@telemetry_router.post("/v1/agent-run-metadata")
async def add_metadata_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """
    Endpoint to add metadata to an agent run.

    The metadata will be stored in Redis and applied when the collection is processed.
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

        # Check if collection exists and user has permissions
        await _check_single_collection_permission(collection_id, user)

        # Store telemetry log for this request
        await mono_svc.store_telemetry_log(
            user.id,
            type="metadata",
            version="v1",
            json_data=body,
            collection_id=collection_id,
        )

        # Store metadata in Redis
        await _store_agent_run_metadata(collection_id, agent_run_id, metadata, timestamp)

        return JSONResponse(status_code=200, content={"status": "success"})

    except Exception as e:
        logger.error(f"Error adding metadata: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@telemetry_router.post("/v1/transcript-metadata")
async def add_transcript_metadata_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
):
    """
    Endpoint to add metadata to a transcript.

    The metadata will be stored in Redis and applied when the collection is processed.
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

        # Check if collection exists and user has permissions
        await _check_single_collection_permission(collection_id, user)

        # Store transcript metadata in Redis
        await _store_transcript_metadata(
            collection_id,
            transcript_id,
            name,
            description,
            transcript_group_id,
            metadata,
            timestamp,
        )

        return JSONResponse(status_code=200, content={"status": "success"})

    except Exception as e:
        logger.error(f"Error adding transcript metadata: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@telemetry_router.post("/v1/transcript-group-metadata")
async def add_transcript_group_metadata_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
):
    """
    Endpoint to add metadata to a transcript group.

    The metadata will be stored in Redis and applied when the collection is processed.
    """
    try:
        # Parse request body
        body = await request.json()
        collection_id = body.get("collection_id")
        transcript_group_id = body.get("transcript_group_id")
        name = body.get("name")
        description = body.get("description")
        parent_transcript_group_id = body.get("parent_transcript_group_id")
        metadata = body.get("metadata")
        timestamp = body.get("timestamp")

        if not all([collection_id, transcript_group_id, timestamp]):
            raise HTTPException(
                status_code=400,
                detail="collection_id, transcript_group_id, and timestamp are required",
            )

        # Check if collection exists and user has permissions
        await _check_single_collection_permission(collection_id, user)

        # Store transcript group metadata in Redis
        await _store_transcript_group_metadata(
            collection_id,
            transcript_group_id,
            name,
            description,
            parent_transcript_group_id,
            metadata,
            timestamp,
        )

        return JSONResponse(status_code=200, content={"status": "success"})

    except Exception as e:
        logger.error(f"Error adding transcript group metadata: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _ensure_collections_exists(
    collection_ids: set[str], collection_names: Dict[str, str], user: User, mono_svc: MonoService
) -> None:
    """
    Ensure all collections exist, creating them if necessary.

    Args:
        collection_ids: Set of collection IDs to ensure exist
        collection_names: Dictionary mapping collection IDs to their names
        user: The user creating the collections
        mono_svc: Database service instance
    """
    for collection_id in collection_ids:
        try:
            if not await mono_svc.collection_exists(collection_id):
                # Use the extracted collection name or fall back to default
                collection_name = collection_names.get(collection_id, f"Collection {collection_id}")
                await mono_svc.create_collection(
                    user=user,
                    collection_id=collection_id,
                    name=collection_name,
                    description="",
                )
                logger.info(f"Created collection {collection_id} with name: {collection_name}")
        except Exception as e:
            logger.error(f"Error creating/checking collection {collection_id}: {str(e)}")
            raise


async def _add_spans_to_accumulation(collection_id: str, spans: List[Dict[str, Any]]) -> None:
    """Add spans to accumulation using Redis."""
    redis_client = await get_redis_client()
    collection_key = f"{_COLLECTION_SPANS_KEY_PREFIX}{collection_id}"

    # Add spans to Redis list
    for span in spans:
        await redis_client.lpush(collection_key, json.dumps(span))  # type: ignore

    # Note: We don't expire the collection_key because we need the spans to persist
    # until we manually process and clean them up. The timeout mechanism controls
    # when to process, not Redis TTL.

    logger.info(f"Added {len(spans)} spans to Redis for collection {collection_id}")


async def _get_accumulated_spans(collection_id: str) -> List[Dict[str, Any]]:
    """Get accumulated spans for a collection from Redis."""
    redis_client = await get_redis_client()
    collection_key = f"{_COLLECTION_SPANS_KEY_PREFIX}{collection_id}"

    # Get all spans from Redis list
    span_jsons = cast(List[str], await redis_client.lrange(collection_key, 0, -1))  # type: ignore

    spans: List[Dict[str, Any]] = []
    for span_json in reversed(list(span_jsons)):
        try:
            spans.append(json.loads(span_json))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode span JSON for collection {collection_id}: {e}")
            continue

    return spans


async def _remove_collection_from_accumulation(collection_id: str) -> None:
    """Remove a collection from accumulation in Redis."""
    redis_client = await get_redis_client()
    collection_key = f"{_COLLECTION_SPANS_KEY_PREFIX}{collection_id}"
    await redis_client.delete(collection_key)  # type: ignore
    logger.info(f"Removed collection {collection_id} from accumulation")


async def _store_agent_run_score(
    collection_id: str,
    agent_run_id: str,
    score_name: str,
    score_value: Any,
    timestamp: str,
) -> None:
    """Store an agent run score in Redis using lists to support multiple scores."""
    redis_client = await get_redis_client()
    scores_key = f"{_COLLECTION_SCORES_KEY_PREFIX}{collection_id}"

    # Store score as JSON in a list with agent_run_id as field
    score_data = {
        "agent_run_id": agent_run_id,
        "score_name": score_name,
        "score_value": score_value,
        "timestamp": timestamp,
    }

    # Use LPUSH to add to a list for this agent_run_id
    list_key = f"{scores_key}:{agent_run_id}"
    await redis_client.lpush(list_key, json.dumps(score_data))  # type: ignore

    logger.info(
        f"Stored score {score_name}={score_value} for agent_run_id {agent_run_id} in collection {collection_id}"
    )


async def _store_agent_run_metadata(
    collection_id: str, agent_run_id: str, metadata: Dict[str, Any], timestamp: str
) -> None:
    """Store agent run metadata in Redis using lists to support multiple metadata calls."""
    redis_client = await get_redis_client()
    metadata_key = f"{_COLLECTION_METADATA_KEY_PREFIX}{collection_id}"

    # Store metadata as JSON in a list with agent_run_id as field
    metadata_data = {
        "agent_run_id": agent_run_id,
        "metadata": metadata,
        "timestamp": timestamp,
    }

    # Use LPUSH to add to a list for this agent_run_id
    list_key = f"{metadata_key}:{agent_run_id}"
    await redis_client.lpush(list_key, json.dumps(metadata_data))  # type: ignore

    logger.info(f"Stored metadata for agent_run_id {agent_run_id} in collection {collection_id}")


async def _store_transcript_metadata(
    collection_id: str,
    transcript_id: str,
    name: Optional[str],
    description: Optional[str],
    transcript_group_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
    timestamp: str,
) -> None:
    """Store transcript metadata in Redis using lists to support multiple metadata calls."""
    redis_client = await get_redis_client()
    metadata_key = f"{_COLLECTION_TRANSCRIPT_METADATA_KEY_PREFIX}{collection_id}"

    # Store metadata as JSON in a list with transcript_id as field
    metadata_data = {
        "transcript_id": transcript_id,
        "name": name,
        "description": description,
        "transcript_group_id": transcript_group_id,
        "metadata": metadata,
        "timestamp": timestamp,
    }

    # Use LPUSH to add to a list for this transcript_id
    list_key = f"{metadata_key}:{transcript_id}"
    await redis_client.lpush(list_key, json.dumps(metadata_data))  # type: ignore

    logger.info(
        f"Stored transcript metadata for transcript_id {transcript_id} in collection {collection_id}"
    )


async def _store_transcript_group_metadata(
    collection_id: str,
    transcript_group_id: str,
    name: Optional[str],
    description: Optional[str],
    parent_transcript_group_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
    timestamp: str,
) -> None:
    """Store transcript group metadata in Redis using lists to support multiple metadata calls."""
    redis_client = await get_redis_client()
    metadata_key = f"{_COLLECTION_TRANSCRIPT_GROUP_METADATA_KEY_PREFIX}{collection_id}"

    # Store metadata as JSON in a list with transcript_group_id as field
    metadata_data = {
        "transcript_group_id": transcript_group_id,
        "name": name,
        "description": description,
        "parent_transcript_group_id": parent_transcript_group_id,
        "metadata": metadata,
        "timestamp": timestamp,
    }

    # Use LPUSH to add to a list for this transcript_group_id
    list_key = f"{metadata_key}:{transcript_group_id}"
    await redis_client.lpush(list_key, json.dumps(metadata_data))  # type: ignore

    logger.info(
        f"Stored transcript group metadata for transcript_group_id {transcript_group_id} in collection {collection_id}"
    )


async def _get_collection_scores(collection_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Get all scores for a collection from Redis."""
    redis_client = await get_redis_client()
    scores_key = f"{_COLLECTION_SCORES_KEY_PREFIX}{collection_id}"

    # Get all keys that match the pattern for this collection
    pattern = f"{scores_key}:*"
    keys = await redis_client.keys(pattern)  # type: ignore

    scores: Dict[str, List[Dict[str, Any]]] = {}
    for key in keys:
        try:
            # Extract agent_run_id from key (format: collection_scores:collection_id:agent_run_id)
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            agent_run_id = key_str.split(":")[-1]

            # Get all scores for this agent_run_id
            score_jsons: List[bytes] = await redis_client.lrange(key, 0, -1)  # type: ignore

            agent_scores: List[Dict[str, Any]] = []
            for score_json in score_jsons:  # type: ignore
                try:
                    score_data = json.loads(
                        score_json.decode() if isinstance(score_json, bytes) else str(score_json)  # type: ignore
                    )
                    agent_scores.append(score_data)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f"Failed to decode score data: {e}")
                    continue

            if agent_scores:
                scores[agent_run_id] = agent_scores

        except Exception as e:
            logger.error(f"Failed to process scores for key {key}: {e}")
            continue

    return scores


async def _get_collection_metadata(collection_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Get all metadata for a collection from Redis."""
    redis_client = await get_redis_client()
    metadata_key = f"{_COLLECTION_METADATA_KEY_PREFIX}{collection_id}"

    # Get all keys that match the pattern for this collection
    pattern = f"{metadata_key}:*"
    keys = await redis_client.keys(pattern)  # type: ignore

    metadata: Dict[str, List[Dict[str, Any]]] = {}
    for key in keys:
        try:
            # Extract agent_run_id from key (format: collection_metadata:collection_id:agent_run_id)
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            agent_run_id = key_str.split(":")[-1]

            # Get all metadata for this agent_run_id
            metadata_jsons: List[bytes] = await redis_client.lrange(key, 0, -1)  # type: ignore

            agent_metadata: List[Dict[str, Any]] = []
            for metadata_json in metadata_jsons:  # type: ignore
                try:
                    metadata_item = json.loads(
                        metadata_json.decode()
                        if isinstance(metadata_json, bytes)
                        else str(metadata_json)  # type: ignore
                    )
                    agent_metadata.append(metadata_item)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f"Failed to decode metadata: {e}")
                    continue

            if agent_metadata:
                metadata[agent_run_id] = agent_metadata

        except Exception as e:
            logger.error(f"Failed to process metadata for key {key}: {e}")
            continue

    return metadata


async def _get_collection_transcript_group_metadata(
    collection_id: str,
) -> Dict[str, Dict[str, Any]]:
    """Get all transcript group metadata for a collection from Redis, merging multiple calls with recent data taking precedence."""
    redis_client = await get_redis_client()
    metadata_key = f"{_COLLECTION_TRANSCRIPT_GROUP_METADATA_KEY_PREFIX}{collection_id}"

    # Get all keys that match the pattern for this collection
    pattern = f"{metadata_key}:*"
    keys = await redis_client.keys(pattern)  # type: ignore

    metadata: Dict[str, Dict[str, Any]] = {}
    for key in keys:
        try:
            # Extract transcript_group_id from key (format: collection_transcript_group_metadata:collection_id:transcript_group_id)
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            transcript_group_id = key_str.split(":")[-1]

            # Get all metadata for this transcript_group_id
            metadata_jsons: List[bytes] = await redis_client.lrange(key, 0, -1)  # type: ignore

            # Merge all metadata items, with more recent ones (earlier in the list) taking precedence
            merged_metadata: Dict[str, Any] = {}
            for metadata_json in metadata_jsons:  # type: ignore
                try:
                    metadata_item = json.loads(
                        metadata_json.decode()
                        if isinstance(metadata_json, bytes)
                        else str(metadata_json)  # type: ignore
                    )
                    # Update merged_metadata with this item, newer items will overwrite older ones
                    merged_metadata.update(metadata_item)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f"Failed to decode transcript group metadata: {e}")
                    continue

            if merged_metadata:
                metadata[transcript_group_id] = merged_metadata

        except Exception as e:
            logger.error(f"Failed to process transcript group metadata for key {key}: {e}")
            continue

    return metadata


def _create_transcript_groups_from_redis_data(
    transcript_group_metadata: Dict[str, Dict[str, Any]],
) -> List[TranscriptGroup]:
    """
    Create TranscriptGroup objects from Redis metadata.

    Args:
        transcript_group_metadata: Dictionary mapping transcript_group_id to merged metadata dict

    Returns:
        List of TranscriptGroup objects
    """
    transcript_groups: List[TranscriptGroup] = []

    for transcript_group_id, metadata in transcript_group_metadata.items():
        if not metadata:
            continue

        # Extract fields from metadata
        name = metadata.get("name")
        description = metadata.get("description")
        parent_transcript_group_id = metadata.get("parent_transcript_group_id")
        metadata_dict = metadata.get("metadata", {})

        # Create TranscriptGroup object
        transcript_group = TranscriptGroup(
            id=transcript_group_id,
            name=name,
            description=description,
            parent_transcript_group_id=parent_transcript_group_id,
            metadata=metadata_dict if metadata_dict else {},
        )

        transcript_groups.append(transcript_group)

    return transcript_groups


async def _cleanup_collection_data(collection_id: str) -> None:
    """Clean up all Redis data for a collection."""
    await _remove_collection_from_accumulation(collection_id)

    # Clean up timeout key and related data
    redis_client = await get_redis_client()
    timeout_key = f"{_COLLECTION_TIMEOUT_KEY_PREFIX}{collection_id}"
    await redis_client.delete(timeout_key)  # type: ignore

    # Clean up score list keys (they have the pattern collection_scores:collection_id:agent_run_id)
    scores_key = f"{_COLLECTION_SCORES_KEY_PREFIX}{collection_id}"
    score_keys = await redis_client.keys(f"{scores_key}:*")  # type: ignore
    for key in score_keys:
        await redis_client.delete(key)  # type: ignore

    # Clean up metadata list keys (they have the pattern collection_metadata:collection_id:agent_run_id)
    metadata_key = f"{_COLLECTION_METADATA_KEY_PREFIX}{collection_id}"
    metadata_keys = await redis_client.keys(f"{metadata_key}:*")  # type: ignore
    for key in metadata_keys:
        await redis_client.delete(key)  # type: ignore

    # Clean up transcript metadata list keys (they have the pattern collection_transcript_metadata:collection_id:transcript_id)
    transcript_metadata_key = f"{_COLLECTION_TRANSCRIPT_METADATA_KEY_PREFIX}{collection_id}"
    transcript_metadata_keys = await redis_client.keys(f"{transcript_metadata_key}:*")  # type: ignore
    for key in transcript_metadata_keys:
        await redis_client.delete(key)  # type: ignore

    # Clean up transcript group metadata list keys (they have the pattern collection_transcript_group_metadata:collection_id:transcript_group_id)
    transcript_group_metadata_key = (
        f"{_COLLECTION_TRANSCRIPT_GROUP_METADATA_KEY_PREFIX}{collection_id}"
    )
    transcript_group_metadata_keys = await redis_client.keys(f"{transcript_group_metadata_key}:*")  # type: ignore
    for key in transcript_group_metadata_keys:
        await redis_client.delete(key)  # type: ignore

    logger.info(f"Cleaned up Redis data for collection {collection_id}")


async def _process_trace_done_with_delay(
    collection_id: str, user: User, analytics: AnalyticsClient
) -> None:
    """Process a trace-done event with a delay to allow for late-arriving spans."""
    # Wait a bit to allow for late-arriving spans
    await asyncio.sleep(5)  # 5 second delay

    # Get accumulated spans for this collection
    accumulated_spans = await _get_accumulated_spans(collection_id)

    if accumulated_spans:
        logger.info(
            f"Processing trace-done for collection {collection_id} with {len(accumulated_spans)} spans"
        )
        await process_completed_collection(collection_id, accumulated_spans, user, analytics)
    else:
        logger.warning(f"No spans found for trace-done collection {collection_id}")


async def _check_collection_permissions(
    collection_ids: set[str], user: User, mono_svc: MonoService
) -> None:
    """
    Check that the user has write permissions on all collections,
    or that the collections don't exist yet (in which case they will be created).

    Args:
        collection_ids: Set of collection IDs to check
        user: The authenticated user
        mono_svc: The database service

    Raises:
        HTTPException: If user lacks write permissions on any existing collection
    """
    from docent_core._db_service.schemas.auth_models import Permission, ResourceType

    # Check permissions for each collection
    for collection_id in collection_ids:
        # Check if collection exists
        collection_exists = await mono_svc.collection_exists(collection_id)

        if collection_exists:
            # Collection exists - check write permissions
            has_write_permission = await mono_svc.has_permission(
                user=user,
                resource_type=ResourceType.COLLECTION,
                resource_id=collection_id,
                permission=Permission.WRITE,
            )

            if not has_write_permission:
                logger.error(f"Permission denied for user {user.id} on collection {collection_id}")
                raise HTTPException(
                    status_code=403,
                    detail=f"Write permission required on collection {collection_id}",
                )
        else:
            # Collection doesn't exist - this is allowed, it will be created later
            logger.info(
                f"Collection {collection_id} doesn't exist yet, will be created during processing"
            )


async def _check_single_collection_permission(collection_id: str, user: User) -> None:
    """
    Check that the user has write permissions on a single collection,
    or that the collection doesn't exist yet (in which case it will be created).

    Args:
        collection_id: The collection ID to check
        user: The authenticated user

    Raises:
        HTTPException: If user lacks write permissions on the existing collection
    """
    mono_svc = await MonoService.init()
    if await mono_svc.collection_exists(collection_id):
        from docent_core._db_service.schemas.auth_models import Permission, ResourceType

        has_write_permission = await mono_svc.has_permission(
            user=user,
            resource_type=ResourceType.COLLECTION,
            resource_id=collection_id,
            permission=Permission.WRITE,
        )
        if not has_write_permission:
            raise HTTPException(
                status_code=403,
                detail=f"Write permission required on collection {collection_id}",
            )
    else:
        # Collection doesn't exist yet - this is allowed, it will be created during processing
        logger.info(
            f"Collection {collection_id} doesn't exist yet, will be created during processing"
        )


def parse_protobuf_traces(body: bytes) -> Dict[str, Any]:
    """Parse protobuf formatted trace data."""
    try:
        # Parse the protobuf message
        export_request = trace_service_pb2.ExportTraceServiceRequest()
        export_request.ParseFromString(body)

        # Convert to dictionary for easier processing
        trace_data = MessageToDict(export_request, preserving_proto_field_name=True)
        return trace_data
    except Exception as e:
        logger.error(f"Error parsing protobuf traces: {str(e)}")
        raise ValueError(f"Invalid protobuf format: {str(e)}")


async def extract_spans(trace_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract spans from the trace data.

    Args:
        trace_data: Dictionary containing OTLP trace data

    Returns:
        List of extracted spans
    """
    extracted_spans: List[Dict[str, Any]] = []

    try:
        # Extract resource spans
        resource_spans = trace_data.get("resource_spans", [])

        for resource_span in resource_spans:
            # Extract resource attributes
            resource = resource_span.get("resource", {})
            resource_attrs = extract_attributes(resource.get("attributes", []))

            # Process scope spans
            scope_spans = resource_span.get("scope_spans", [])

            for scope_span in scope_spans:
                # Extract scope information
                scope = scope_span.get("scope", {})
                scope_name = scope.get("name", "unknown")
                scope_version = scope.get("version", "")

                # Process individual spans
                spans = scope_span.get("spans", [])

                for span in spans:
                    extracted_span = otel_span_format_to_dict(
                        span, resource_attrs, scope_name, scope_version
                    )
                    extracted_spans.append(extracted_span)

        return extracted_spans

    except Exception as e:
        logger.error(f"Error extracting spans: {str(e)}")
        raise


def _extract_single_value(value: Dict[str, Any]) -> Any:
    """Extract a single value from OTLP format based on its type."""
    if "string_value" in value:
        return value["string_value"]
    elif "int_value" in value:
        return int(value["int_value"])
    elif "double_value" in value:
        return float(value["double_value"])
    elif "bool_value" in value:
        return bool(value["bool_value"])
    elif "array_value" in value:
        return extract_array_value(value["array_value"])
    elif "kvlist_value" in value:
        return extract_kvlist_value(value["kvlist_value"])
    else:
        return None


def extract_attributes(attributes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract attributes from OTLP format to a simple dictionary.

    Example input (OTLP format):
        [
            {"key": "service.name", "value": {"string_value": "my-service"}},
            {"key": "foo", "value": {"int_value": 42}},
            {"key": "bar", "value": {"bool_value": True}},
            {"key": "tags", "value": {"array_value": {"values": [
                {"string_value": "a"}, {"string_value": "b"}
            ]}}},
        ]

    Example output:
        {
            "service.name": "my-service",
            "foo": 42,
            "bar": True,
            "tags": ["a", "b"]
        }
    """
    result: Dict[str, Any] = {}

    for attr in attributes:
        key = attr.get("key", "")
        value = attr.get("value", {})
        result[key] = _extract_single_value(value)

    return result


def extract_array_value(array_value: Dict[str, Any]) -> List[Any]:
    """Extract array values from OTLP format."""
    values: List[Any] = []
    for item in array_value.get("values", []):
        extracted_value = _extract_single_value(item)
        if extracted_value is not None:
            values.append(extracted_value)
    return values


def extract_kvlist_value(kvlist: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key-value list from OTLP format."""
    return extract_attributes(kvlist.get("values", []))


def otel_span_format_to_dict(
    span: Dict[str, Any], resource_attrs: Dict[str, Any], scope_name: str, scope_version: str
) -> Dict[str, Any]:
    """Process a single span and extract relevant information, preserving any additional fields."""

    # Extract and convert span details
    span_id = span.get("span_id", "")
    trace_id = span.get("trace_id", "")
    parent_span_id = span.get("parent_span_id", "")

    # Convert IDs from base64 if necessary
    if isinstance(span_id, str) and span_id:
        span_id = base64.b64decode(span_id).hex()
    if isinstance(trace_id, str) and trace_id:
        trace_id = base64.b64decode(trace_id).hex()
    if isinstance(parent_span_id, str) and parent_span_id:
        parent_span_id = base64.b64decode(parent_span_id).hex()

    # Extract timestamps (convert from nanoseconds) and ensure timezone-aware (UTC)
    start_time_ns = int(span.get("start_time_unix_nano", 0))
    end_time_ns = int(span.get("end_time_unix_nano", 0))
    start_time = datetime.fromtimestamp(start_time_ns / 1e9, tz=timezone.utc).isoformat()
    end_time = datetime.fromtimestamp(end_time_ns / 1e9, tz=timezone.utc).isoformat()
    duration_ms = (end_time_ns - start_time_ns) / 1e6

    # Extract span attributes
    span_attrs = extract_attributes(span.get("attributes", []))

    # Extract events
    events: List[Dict[str, Any]] = []
    for event in span.get("events", []):
        events.append(
            {
                "name": event.get("name", ""),
                "timestamp": datetime.fromtimestamp(
                    int(event.get("time_unix_nano", 0)) / 1e9, tz=timezone.utc
                ).isoformat(),
                "attributes": extract_attributes(event.get("attributes", [])),
            }
        )

    # Extract links
    links: List[Dict[str, Any]] = []
    for link in span.get("links", []):
        link_trace_id = link.get("trace_id", "")
        link_span_id = link.get("span_id", "")

        if isinstance(link_trace_id, str) and link_trace_id:
            link_trace_id = base64.b64decode(link_trace_id).hex()
        if isinstance(link_span_id, str) and link_span_id:
            link_span_id = base64.b64decode(link_span_id).hex()

        links.append(
            {
                "trace_id": link_trace_id,
                "span_id": link_span_id,
                "attributes": extract_attributes(link.get("attributes", [])),
            }
        )
    # Start with a copy of the original span to preserve all fields
    processed_span: Dict[str, Any] = span.copy()
    # Update the processed span with our enhanced fields
    processed_span.update(
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "operation_name": span.get("name", ""),
            "start_time": start_time,
            "end_time": end_time,
            "duration_ms": duration_ms,
            "status": {
                "code": span.get("status", {}).get("code", 0),
                "message": span.get("status", {}).get("message", ""),
            },
            "kind": span.get("kind", 0),
            "resource_attributes": resource_attrs,
            "attributes": span_attrs,
            "events": events,
            "links": links,
            "scope": {"name": scope_name, "version": scope_version},
        }
    )

    return processed_span


async def accumulate_spans(spans: List[Dict[str, Any]]) -> None:
    """
    Accumulate spans by collection_id for later processing.

    Args:
        spans: List of processed spans to accumulate
    """
    # Group spans by collection_id for efficient processing
    spans_by_collection: Dict[str, List[Dict[str, Any]]] = {}
    for span in spans:
        span_attrs = span.get("attributes", {})
        collection_id = span_attrs.get("collection_id")
        if collection_id:
            if collection_id not in spans_by_collection:
                spans_by_collection[collection_id] = []
            spans_by_collection[collection_id].append(span)

    # Add spans to accumulation
    for collection_id, collection_spans in spans_by_collection.items():
        await _add_spans_to_accumulation(collection_id, collection_spans)


def is_collection_complete(all_spans: List[Dict[str, Any]]) -> bool:
    """
    Check if a collection is complete based on the presence of a trace_end span.

    Args:
        all_spans: All spans in the collection

    Returns:
        True if the collection appears to be complete
    """
    # Check if any span in the collection is a trace_end span
    for collection_span in all_spans:
        span_attrs = collection_span.get("attributes", {})
        if (
            collection_span.get("operation_name") == "trace_end"
            and span_attrs.get("event.type") == "trace_end"
        ):
            return True

    return False


async def process_completed_collection(
    collection_id: str, spans: List[Dict[str, Any]], user: User, analytics: AnalyticsClient
) -> None:
    """
    Process a completed collection by creating agent runs, transcripts, and transcript groups.

    Args:
        collection_id: The collection ID that was completed
        spans: All spans in the completed collection
    """
    logger.info(f"Processing completed collection {collection_id} with {len(spans)} spans")

    # Process spans to create agent runs
    count_agent_runs = await store_spans(spans, user)

    # Clean up all Redis data for this collection after processing is complete
    await _cleanup_collection_data(collection_id)

    # Track with PostHog
    analytics.track_event(
        "agent_runs_ingested",
        properties={
            "collection_id": collection_id,
            "num_runs": count_agent_runs,
            "source": "tracing",
        },
    )


async def store_spans(spans: List[Dict[str, Any]], user: User) -> int:
    """
    Store spans by creating collections, agent runs, and transcripts.

    Args:
        spans: List of processed span dictionaries
        user: The user creating the agent runs

    Returns:
        int: Number of agent runs created
    """
    if not spans:
        return 0

    # Initialize database service
    mono_svc = await MonoService.init()

    # Organize spans by collection_id -> agent_run_id -> transcript_id -> spans[]
    spans_by_collection = _organize_spans_by_collection(spans)

    # Process each collection and its agent runs
    total_agent_runs = 0

    for collection_id, spans_by_agent_run in spans_by_collection.items():
        # Ensure collection exists
        if not await mono_svc.collection_exists(collection_id):
            logger.error(
                f"Collection {collection_id} does not exist but should have been created earlier"
            )
            raise HTTPException(
                status_code=404,
                detail=f"Collection {collection_id} not found. It should have been created during trace processing.",
            )

        # Get or create default view context for this collection
        ctx = await mono_svc.get_default_view_ctx(collection_id, user)

        # Get transcript group metadata from Redis and store to database
        transcript_group_metadata = await _get_collection_transcript_group_metadata(collection_id)
        if transcript_group_metadata:
            transcript_groups = _create_transcript_groups_from_redis_data(transcript_group_metadata)
            if transcript_groups:
                await mono_svc.store_transcript_groups(ctx, transcript_groups)
                logger.info(
                    f"Stored {len(transcript_groups)} transcript groups for collection {collection_id}"
                )

        # Create agent runs for this collection with stored scores and metadata
        collection_agent_runs = await _create_agent_runs_from_spans(
            spans_by_agent_run, collection_id
        )

        # Add agent runs to this collection
        if collection_agent_runs:
            try:
                # Add agent runs using the existing service method
                await mono_svc.update_agent_runs(ctx, collection_agent_runs)
                logger.info(
                    f"Added {len(collection_agent_runs)} agent runs to collection {collection_id}"
                )
                total_agent_runs += len(collection_agent_runs)
            except Exception as e:
                logger.error(f"Error adding agent runs to collection {collection_id}: {str(e)}")

        else:
            logger.warning(f"No agent runs created for collection {collection_id}")
            # Log agent run details for debugging
            for agent_run_id, transcripts in spans_by_agent_run.items():
                logger.debug(f"  Agent run {agent_run_id}: {len(transcripts)} transcripts")

    logger.info(f"Processed {len(spans)} spans into {total_agent_runs} agent runs")

    return total_agent_runs


def _organize_spans_by_collection(
    spans: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]]:
    """
    Organize spans by collection_id -> agent_run_id -> transcript_id -> spans[].

    Args:
        spans: List of processed span dictionaries

    Returns:
        Organized spans structure
    """
    organized_spans: Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]] = {}

    for span in spans:
        # Extract IDs from span attributes
        span_attrs = span.get("attributes", {})
        collection_id = span_attrs.get("collection_id")
        agent_run_id = span_attrs.get("agent_run_id")
        transcript_id = span_attrs.get("transcript_id")

        if not collection_id:
            logger.warning(f"Skipping span {span.get('span_id')} - missing collection_id")
            logger.debug(f"Span: {json.dumps(span, indent=2)}")
            continue

        organized_spans.setdefault(collection_id, {}).setdefault(agent_run_id, {}).setdefault(
            transcript_id, []
        ).append(span)

    return organized_spans


def _find_or_create_chat_thread(
    span_messages: List[ChatMessage], existing_chat_threads: List[List[ChatMessage]]
) -> tuple[int | None, str]:
    """
    Find the right existing chat thread to add new messages to, or indicate a new thread should be created.

    Args:
        span_messages: Messages from the current span
        existing_chat_threads: List of existing chat threads

    Returns:
        Tuple of (thread_index, action) where action is 'extend', 'skip', or 'new'
    """
    if len(span_messages) == 1:
        # Single message - create new chat thread
        return None, "new"

    # Multiple messages - try to find matching existing thread
    for i, existing_thread in enumerate(existing_chat_threads):
        # Case 1: Check if existing thread is a prefix of span_messages (extend existing)
        if len(span_messages) > len(existing_thread):
            if matching_thread_start(existing_thread, span_messages):
                logger.debug(
                    f"    Found matching thread {i} for span with {len(span_messages)} messages (extend existing)"
                )
                return i, "extend"

        # Case 2: Check if span_messages is a prefix of existing thread (skip new)
        elif len(existing_thread) >= len(span_messages):
            if matching_thread_start(span_messages, existing_thread):
                logger.debug(
                    f"    Found matching thread {i} for span with {len(span_messages)} messages (skip new - already contained)"
                )
                return i, "skip"

    # No match found - create new chat thread
    return None, "new"


def _create_transcripts_from_spans(transcript_spans: List[Dict[str, Any]]) -> List[Transcript]:
    """
    Create Transcript objects from spans.

    Args:
        transcript_spans: List of spans for a transcript

    Returns:
        List of Transcript objects
    """
    # Store all the chat threads
    chat_threads: List[List[ChatMessage]] = []

    # Extract transcript_group_id from the first span (they should all have the same one)
    transcript_group_id = None
    if transcript_spans:
        first_span_attrs = transcript_spans[0].get("attributes", {})
        transcript_group_id = first_span_attrs.get("transcript_group_id")

    for span in transcript_spans:
        # Extract messages from this span
        span_messages = _span_to_chat_messages(span)

        if not span_messages:
            continue

        # Find or create chat thread
        thread_index, action = _find_or_create_chat_thread(span_messages, chat_threads)

        if action == "new":
            # Create new chat thread
            chat_threads.append(span_messages)
            logger.debug(f"    Created new chat thread with {len(span_messages)} messages")
        elif action == "extend" and thread_index is not None:
            # Found matching thread - add new messages
            existing_thread = chat_threads[thread_index]
            new_messages = span_messages[len(existing_thread) :]
            chat_threads[thread_index].extend(new_messages)
            logger.info(
                f"    Extended chat thread {thread_index} with {len(new_messages)} new messages. First new message: {new_messages[0].text[:100] if new_messages else 'N/A'}"
            )
        elif action == "skip":
            # New messages are already contained in existing thread - skip
            logger.info(
                f"    Skipped span with {len(span_messages)} messages (already contained in thread {thread_index})"
            )

    # Create transcripts from chat threads
    transcripts: List[Transcript] = []
    if chat_threads:
        for i, chat_thread in enumerate(chat_threads):
            # Create unique transcript ID for each thread
            thread_transcript_id = str(uuid.uuid4())

            transcript = Transcript(
                id=thread_transcript_id,
                messages=chat_thread,
                name=f"Chat Thread {i + 1}" if len(chat_threads) > 1 else "",
                description="",
                transcript_group_id=transcript_group_id,
            )
            transcripts.append(transcript)
            logger.info(
                f"    Created transcript {thread_transcript_id} with {len(chat_thread)} messages and transcript_group_id: {transcript_group_id}"
            )
    else:
        logger.warning(f"    No messages extracted from {len(transcript_spans)} spans")

    return transcripts


async def _create_agent_runs_from_spans(
    agent_runs: Dict[str, Dict[str, List[Dict[str, Any]]]], collection_id: str
) -> List[AgentRun]:
    """
    Create AgentRun objects from organized spans, incorporating stored scores and metadata.

    Args:
        agent_runs: Organized spans by agent_run_id -> transcript_id -> spans[]
        collection_id: The ID of the collection these spans belong to

    Returns:
        List of AgentRun objects
    """
    collection_agent_runs: List[AgentRun] = []

    for agent_run_id, transcripts in agent_runs.items():
        logger.info(f"Processing agent_run_id: {agent_run_id}")
        agent_run_transcripts: Dict[str, Transcript] = {}
        agent_run_scores: Dict[str, int | float | bool | None] = {}
        agent_run_model: str | None = None
        agent_run_metadata_dict: Dict[str, Any] = {}

        # Process each transcript
        for transcript_id, transcript_spans in transcripts.items():
            logger.info(
                f"  Processing transcript_id: {transcript_id} with {len(transcript_spans)} spans"
            )

            # Extract metadata and scores from spans
            for span in transcript_spans:
                # Check for agent_run_score events
                for event in span.get("events", []):
                    if event.get("name") == "agent_run_score":
                        score_name = event.get("attributes", {}).get("score.name")
                        score_value = event.get("attributes", {}).get("score.value")
                        if score_name and score_value is not None:
                            agent_run_scores[score_name] = score_value
                            logger.info(f"    Found score: {score_name} = {score_value}")

                # Extract metadata from span events
                span_metadata = _extract_metadata_from_span_events(span)
                if span_metadata:
                    # Unflatten the metadata to restore nested structure
                    unflattened_metadata = _unflatten_metadata(span_metadata)
                    agent_run_metadata_dict.update(unflattened_metadata)
                    logger.info(f"    Found metadata: {unflattened_metadata}")

                # Extract model from span attributes
                span_attrs = span.get("attributes", {})
                if not agent_run_model and "gen_ai.response.model" in span_attrs:
                    agent_run_model = span_attrs["gen_ai.response.model"]
                    logger.info(f"    Found model: {agent_run_model}")

            # Create transcripts from spans
            transcripts_list = _create_transcripts_from_spans(transcript_spans)

            # Add transcripts to agent run
            for transcript in transcripts_list:
                agent_run_transcripts[transcript.id] = transcript

        # Create agent run if it has transcripts
        if agent_run_transcripts:
            # Get stored scores and metadata for this collection
            collection_scores = await _get_collection_scores(collection_id)
            collection_metadata = await _get_collection_metadata(collection_id)

            # Create metadata with scores, model, and any additional metadata using BaseAgentRunMetadata
            metadata_dict: Dict[str, Any] = {"scores": agent_run_scores}
            if agent_run_model:
                metadata_dict["model"] = agent_run_model

            # Add any additional metadata from span events
            if agent_run_metadata_dict:
                metadata_dict.update(agent_run_metadata_dict)
                logger.info(f"  Added metadata to agent run: {agent_run_metadata_dict}")

            # Add stored scores from Redis (these take precedence over span-based scores)
            if collection_scores.get(agent_run_id):
                for score_item in collection_scores[agent_run_id]:
                    stored_score_name = score_item.get("score_name")
                    stored_score_value = score_item.get("score_value")
                    if stored_score_name and stored_score_value is not None:
                        # Add the stored score to the scores dict
                        metadata_dict["scores"][stored_score_name] = stored_score_value
                        logger.info(
                            f"  Added stored score to agent run: {stored_score_name} = {stored_score_value}"
                        )

            # Add stored metadata from Redis (these take precedence over span-based metadata)
            if collection_metadata.get(agent_run_id):
                for metadata_item in collection_metadata[agent_run_id]:
                    stored_metadata = metadata_item.get("metadata", {})
                    if stored_metadata:
                        # Merge stored metadata with span-based metadata, stored metadata takes precedence
                        metadata_dict.update(stored_metadata)
                        logger.info(f"  Added stored metadata to agent run: {stored_metadata}")

            metadata = metadata_dict
            agent_run = AgentRun(
                id=agent_run_id,
                name="",
                description="",
                transcripts=agent_run_transcripts,
                metadata=metadata,
            )
            collection_agent_runs.append(agent_run)
            logger.info(
                f"  Created agent run {agent_run_id} with {len(agent_run_transcripts)} transcripts, {len(agent_run_scores)} scores, and model: {agent_run_model or 'unknown'}"
            )
        else:
            logger.warning(f"  No transcripts created for agent_run_id: {agent_run_id}")

    return collection_agent_runs


def _extract_tool_call_ids_from_message(msg: ChatMessage) -> set[str]:
    """Extract all tool call IDs from a message.

    Tool call IDs can come from:
    - ToolMessage.tool_call_id
    - AssistantMessage.tool_calls[].id

    Args:
        msg: The chat message to extract tool call IDs from

    Returns:
        Set of tool call IDs found in the message
    """
    tool_call_ids: set[str] = set()

    # Extract from ToolMessage
    if msg.role == "tool" and hasattr(msg, "tool_call_id") and msg.tool_call_id:
        tool_call_ids.add(msg.tool_call_id)

    # Extract from AssistantMessage tool_calls
    if msg.role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
        for tool_call in msg.tool_calls:
            if tool_call.id:
                tool_call_ids.add(tool_call.id)

    return tool_call_ids


def _collect_all_tool_call_ids_from_thread(thread: List[ChatMessage]) -> set[str]:
    """Collect all tool call IDs from a thread.

    Args:
        thread: List of chat messages to extract tool call IDs from

    Returns:
        Set of all tool call IDs found in the thread
    """
    tool_call_ids: set[str] = set()

    for msg in thread:
        msg_tool_ids = _extract_tool_call_ids_from_message(msg)
        tool_call_ids.update(msg_tool_ids)

    return tool_call_ids


def matching_thread_start(
    existing_thread: List[ChatMessage], new_thread: List[ChatMessage]
) -> bool:
    """Check if the beginning of new_thread matches the existing_thread.

    This function handles tool call matching by first collecting all tool call IDs
    from both threads, then doing a matching pass that's more flexible for tool calls.

    Args:
        existing_thread: The existing chat thread to match against
        new_thread: The new chat thread to check

    Returns:
        True if the beginning of new_thread matches existing_thread, False otherwise
    """
    if not existing_thread or not new_thread:
        return False

    # First, collect all tool call IDs from both threads
    existing_thread_tool_call_ids = _collect_all_tool_call_ids_from_thread(existing_thread)
    new_thread_tool_call_ids = _collect_all_tool_call_ids_from_thread(new_thread)

    existing_idx = 0
    new_idx = 0

    while existing_idx < len(existing_thread) and new_idx < len(new_thread):
        existing_msg = existing_thread[existing_idx]
        new_msg = new_thread[new_idx]

        # Check if messages match directly (same role and content)
        if existing_msg.role == new_msg.role and existing_msg.text == new_msg.text:
            existing_idx += 1
            new_idx += 1
            continue

        # For tools allow just the tool_call_id to match
        if existing_msg.role == "tool" and new_msg.role == "tool":
            if (
                existing_msg.tool_call_id
                and new_msg.tool_call_id
                and existing_msg.tool_call_id == new_msg.tool_call_id
            ):
                existing_idx += 1
                new_idx += 1
                continue

        # if they are both assistant messages, and they both have tool_calls, if the tool_call_ids are the same, its a match
        if existing_msg.role == "assistant" and new_msg.role == "assistant":
            if existing_msg.tool_calls and new_msg.tool_calls:
                existing_tool_call_ids = {tool_call.id for tool_call in existing_msg.tool_calls}
                new_tool_call_ids = {tool_call.id for tool_call in new_msg.tool_calls}
                if existing_tool_call_ids == new_tool_call_ids:
                    existing_idx += 1
                    new_idx += 1
                    continue

        # Check if existing message is a tool call we've already seen in new thread
        if (
            existing_msg.role == "tool"
            and existing_msg.tool_call_id
            and existing_msg.tool_call_id in new_thread_tool_call_ids
        ):
            existing_idx += 1
            continue

        # Check if new message is a tool call we've already seen in existing thread
        if (
            new_msg.role == "tool"
            and new_msg.tool_call_id
            and new_msg.tool_call_id in existing_thread_tool_call_ids
        ):
            new_idx += 1
            continue

        # If we get here, the messages don't match and can't be reconciled
        logger.warning(
            f"Thread matching failed: messages don't match at positions "
            f"existing_idx={existing_idx}, new_idx={new_idx}. "
            f"Existing message: role='{existing_msg.role}', text='{existing_msg.text[:50]}...' "
            f"New message: role='{new_msg.role}', text='{new_msg.text[:50]}...'"
        )
        return False

    # Return True if we've processed all of existing_thread
    result = existing_idx >= len(existing_thread)
    if not result:
        logger.warning(
            f"Thread matching failed: didn't process all of existing thread. "
            f"Processed {existing_idx}/{len(existing_thread)} existing messages, "
            f"processed {new_idx}/{len(new_thread)} new messages"
        )
    return result


def _extract_tool_calls_from_content(content: str) -> tuple[str, list[ToolCall] | None]:
    """Extract tool calls from content that may contain JSON arrays with tool_use objects.

    Args:
        content: The content string that may contain tool calls

    Returns:
        Tuple of (filtered_content, tool_calls) where tool_calls is None if no tool calls found
    """
    tool_calls = None

    # Check if content contains tool calls (JSON array with tool_use objects)
    if content.startswith("[") and content.endswith("]"):
        try:
            content_array = json.loads(content)
            if isinstance(content_array, list):
                content_array_any = cast(List[Any], content_array)
                # Only keep dict items
                dict_items: list[dict[str, Any]] = [
                    i for i in content_array_any if isinstance(i, dict)
                ]

                # Extract tool calls and filter content
                extracted_tool_calls: list[ToolCall] = []
                filtered_content_parts: list[str] = []

                for item in dict_items:
                    content_type = item.get("type")

                    if content_type == "tool_use":
                        tool_item: dict[str, Any] = item
                        tool_call = ToolCall(
                            id=str(tool_item.get("id", "")),
                            type="function",
                            function=str(tool_item.get("name", "")),
                            arguments=(
                                tool_item.get("input", {})
                                if isinstance(tool_item.get("input"), dict)
                                else {}
                            ),
                        )
                        extracted_tool_calls.append(tool_call)
                        logger.info(
                            f"Extracted tool call: id={tool_call.id}, function={tool_call.function}"
                        )
                    elif content_type in ["text", "input_text"]:
                        text_content = str(item.get("text", ""))
                        filtered_content_parts.append(text_content)
                    elif content_type == "tool_result":
                        content_str = json.dumps(item.get("content", ""))
                        logger.info(f"Processing tool_result content: {content_str[:200]}...")
                        text_content, _ = _extract_tool_calls_from_content(content_str)
                        filtered_content_parts.append(text_content)
                    else:
                        logger.warning(f"Skipping unknown content JSON type: {content_type}")

                # Update content and tool_calls
                if filtered_content_parts:
                    content = "\n".join(filtered_content_parts)
                else:
                    content = ""

                if extracted_tool_calls:
                    tool_calls = extracted_tool_calls
                    logger.info(f"Extracted {len(tool_calls)} tool calls from content")
        except json.JSONDecodeError as e:
            logger.warning(f"Content is not valid JSON: {e}, treating as regular content")

    return content, tool_calls


def _extract_tool_calls_from_span_data(tool_calls_data: dict[str, Any]) -> list[ToolCall]:
    """Extract tool calls from completion message tool_calls data.

    Args:
        tool_calls_data: Dictionary containing tool call data organized by tool index

    Returns:
        List of ToolCall objects
    """
    tool_calls: list[ToolCall] = []
    logger.debug(f"Extracting tool calls from completion data: {tool_calls_data}")

    for tool_index in sorted(tool_calls_data.keys()):
        tool_data = tool_calls_data[tool_index]
        logger.debug(f"Processing tool index {tool_index}: {tool_data}")

        # Parse arguments if present
        arguments: dict[str, Any] = {}
        if "arguments" in tool_data:
            try:
                arguments = json.loads(tool_data["arguments"])
                logger.debug(f"Successfully parsed arguments for tool {tool_index}: {arguments}")
            except json.JSONDecodeError as e:
                logger.warning(
                    f"Failed to parse tool call arguments for tool {tool_index}: {tool_data['arguments']}, error: {e}"
                )
                arguments = {"raw_arguments": tool_data["arguments"]}

        tool_call = ToolCall(
            id=tool_data.get("id", ""),
            type="function",
            function=tool_data.get("name", ""),
            arguments=arguments,
        )
        tool_calls.append(tool_call)
        logger.debug(f"Created tool call: id={tool_call.id}, function={tool_call.function}")

    logger.debug(f"Extracted {len(tool_calls)} tool calls from completion data")
    return tool_calls


def _span_to_chat_messages(span: Dict[str, Any]) -> List[ChatMessage]:
    """Convert a span to a list of chat message objects."""
    span_attrs = span.get("attributes", {})
    messages: List[ChatMessage] = []

    # Debug logging
    span_id = span.get("span_id", "unknown")
    operation_name = span.get("operation_name", "unknown")
    logger.debug(f"Processing span {span_id} ({operation_name}) with {len(span_attrs)} attributes")

    # Reformat gen_ai attributes into structured dictionary
    gen_ai_data = _reformat_gen_ai_attributes(span_attrs)

    # Extract messages from the structured gen_ai data
    messages = _extract_messages_from_gen_ai_data(gen_ai_data, span_id)

    # Debug logging
    if messages:
        logger.debug(f"Extracted {len(messages)} messages from span {span_id}")
        for i, msg in enumerate(messages):
            logger.debug(
                f"  Message {i}: role={msg.role}, content_length={len(msg.text) if hasattr(msg, 'text') else 'N/A'}"
            )
    else:
        logger.debug(f"No messages extracted from span {span_id}")

    return messages


def _reformat_gen_ai_attributes(span_attrs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reformat gen_ai attributes from flat key-value pairs to structured dictionary.

    Example:
    Input: {
        'gen_ai.prompt.0.role': 'user',
        'gen_ai.prompt.0.content': 'Hello',
        'gen_ai.prompt.1.role': 'assistant',
        'gen_ai.prompt.1.content': 'Hi there',
        'gen_ai.completion.0.role': 'assistant',
        'gen_ai.completion.0.content': 'How can I help?',
        'gen_ai.tool_calls.0.0.id': 'call_1',
        'gen_ai.tool_calls.0.1.id': 'call_2'
    }

    Output: {
        'gen_ai': {
            'prompt': {
                '0': {'role': 'user', 'content': 'Hello'},
                '1': {'role': 'assistant', 'content': 'Hi there'}
            },
            'completion': {
                '0': {'role': 'assistant', 'content': 'How can I help?'}
            },
            'tool_calls': {
                '0': {
                    '0': {'id': 'call_1'},
                    '1': {'id': 'call_2'}
                }
            }
        }
    }
    """
    gen_ai_data: Dict[str, Any] = {}

    for key, value in span_attrs.items():
        if not key.startswith("gen_ai."):
            continue

        # Split the key into parts: gen_ai.prompt.0.role -> ['gen_ai', 'prompt', '0', 'role']
        parts = key.split(".")
        if len(parts) < 2:  # Need at least gen_ai.something
            logger.warning(f"Invalid gen_ai attribute: {key} with value: {value}")
            continue

        # Navigate/create the nested structure
        current: Dict[str, Any] = gen_ai_data
        if "gen_ai" not in current:
            current["gen_ai"] = {}
        current = current["gen_ai"]  # type: ignore

        # Build up the nested structure
        for part in parts[1:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]  # type: ignore

        # Store the value at the final location
        current[parts[-1]] = value

    return gen_ai_data


def _extract_messages_from_gen_ai_data(
    gen_ai_data: Dict[str, Any], span_id: str
) -> List[ChatMessage]:
    """Extract ChatMessage objects from structured gen_ai data."""
    messages: List[ChatMessage] = []

    if "gen_ai" not in gen_ai_data:
        return messages

    gen_ai = gen_ai_data["gen_ai"]

    # Process prompt messages
    if "prompt" in gen_ai:
        # Sort keys numerically to maintain proper order
        for key in sorted(
            gen_ai["prompt"].keys(), key=lambda k: (0, int(k)) if k.isdigit() else (1, k)
        ):
            prompt_data: dict[str, Any] = gen_ai["prompt"][key]

            message = _create_message_from_data(prompt_data, span_id, f"prompt_{key}")
            if message:
                messages.append(message)

    # Process completion messages
    if "completion" in gen_ai:
        # Sort keys numerically to maintain proper order
        for key in sorted(
            gen_ai["completion"].keys(), key=lambda k: (0, int(k)) if k.isdigit() else (1, k)
        ):
            completion_data: dict[str, Any] = gen_ai["completion"][key]

            message = _create_message_from_data(
                completion_data, span_id, f"completion_{key}", assume_role="assistant"
            )
            if message:
                messages.append(message)

    return messages


def _create_message_from_data(
    data: Dict[str, Any], span_id: str, context: str, assume_role: Optional[str] = None
) -> ChatMessage | None:
    """Create a ChatMessage from structured data."""
    try:
        if "role" in data:
            role = str(data["role"])
            if role == "developer":
                role = "system"
        elif assume_role:
            role = assume_role
        else:
            logger.error(f"Invalid role '{data.get('role')}' in {context} for span {span_id}")
            return None

        # Build content from available fields
        content_parts: List[str] = []

        # Add reasoning if present
        if "reasoning" in data:
            reasoning = data["reasoning"]
            if isinstance(reasoning, list):
                reasoning = "\n".join(str(item) for item in reasoning)  # type: ignore
            content_parts.append(str(reasoning))

        # Add content if present
        if "content" in data:
            content_parts.append(str(data["content"]))

        content = "\n".join(content_parts) if content_parts else ""

        # Handle tool calls embedded in content
        if content:
            content, tool_calls = _extract_tool_calls_from_content(data["content"])
        else:
            tool_calls = None

        # Handle structured tool calls
        if not tool_calls and "tool_calls" in data:
            structured_tool_calls = _extract_tool_calls_from_span_data(data["tool_calls"])
            if structured_tool_calls:
                tool_calls = structured_tool_calls

        message_data: Dict[str, Any] = {
            "role": role,
            "content": content,
        }

        if tool_calls:
            message_data["tool_calls"] = tool_calls

        logger.debug(f"Creating {context} message with data: {message_data}")
        message = parse_chat_message(message_data)
        logger.debug(f"Successfully created {context} message: role={message.role}")
        return message

    except Exception as e:
        logger.error(f"Failed to parse {context} message for span {span_id}: {e}")
        return None


def _extract_metadata_from_span_events(span: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract metadata from span events that were created by agent_run_metadata().

    Args:
        span: The span dictionary containing events

    Returns:
        Dictionary of metadata key-value pairs
    """
    metadata: Dict[str, Any] = {}

    for event in span.get("events", []):
        if event.get("name") == "agent_run_metadata":
            event_attrs = event.get("attributes", {})

            # Extract metadata attributes that start with "metadata."
            for key, value in event_attrs.items():
                if key.startswith("metadata."):
                    # Remove the "metadata." prefix to get the actual key
                    metadata_key = key[len("metadata.") :]
                    metadata[metadata_key] = value

    return metadata


def _unflatten_metadata(flattened_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert flattened metadata with dot notation back to nested structure.

    Args:
        flattened_metadata: Dictionary with flattened keys like "user.id", "config.model"

    Returns:
        Nested dictionary structure
    """
    unflattened: Dict[str, Any] = {}

    for key, value in flattened_metadata.items():
        parts = key.split(".")
        current = unflattened

        # Navigate/create the nested structure
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        # Set the value at the final location
        current[parts[-1]] = value

    return unflattened
