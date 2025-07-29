import asyncio
import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, TypedDict, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from docent._log_util import get_logger
from docent.data_models import AgentRun, BaseAgentRunMetadata, Transcript
from docent.data_models.chat import ChatMessage, parse_chat_message
from docent.data_models.chat.tool import ToolCall
from docent_core._db_service.schemas.auth_models import User
from docent_core._db_service.service import MonoService
from docent_core._server._broker.redis_client import get_redis_client
from docent_core._server._dependencies.database import get_mono_svc
from docent_core._server._dependencies.user import get_authenticated_user

logger = get_logger(__name__)

# logger.setLevel(logging.DEBUG)

REDIS = get_redis_client()
# Redis key patterns for collection accumulation
_COLLECTION_SPANS_KEY_PREFIX = "collection_spans:"
_COLLECTION_TIMEOUT_KEY_PREFIX = "collection_timeout:"
_COLLECTION_TIMEOUT_SECONDS = 2 * 60  # Timeout for collection completion


async def _add_spans_to_accumulation(collection_id: str, spans: List[Dict[str, Any]]) -> None:
    """Add spans to accumulation using Redis."""
    collection_key = f"{_COLLECTION_SPANS_KEY_PREFIX}{collection_id}"

    # Add spans to Redis list
    for span in spans:
        await REDIS.lpush(collection_key, json.dumps(span))  # type: ignore

    # Set TTL for automatic cleanup if collection doesn't complete
    await REDIS.expire(collection_key, _COLLECTION_TIMEOUT_SECONDS)  # type: ignore

    logger.info(f"Added {len(spans)} spans to Redis for collection {collection_id}")


async def _get_accumulated_spans(collection_id: str) -> List[Dict[str, Any]]:
    """Get accumulated spans for a collection from Redis."""
    collection_key = f"{_COLLECTION_SPANS_KEY_PREFIX}{collection_id}"

    # Get all spans from Redis list
    span_jsons = cast(List[str], await REDIS.lrange(collection_key, 0, -1))  # type: ignore

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
    collection_key = f"{_COLLECTION_SPANS_KEY_PREFIX}{collection_id}"
    await REDIS.delete(collection_key)  # type: ignore


async def _cancel_collection_timeout(collection_id: str) -> None:
    """Cancel and remove a collection completion task from Redis."""
    timeout_key = f"{_COLLECTION_TIMEOUT_KEY_PREFIX}{collection_id}"
    await REDIS.delete(timeout_key)  # type: ignore


def schedule_collection_timeout(collection_id: str, user: User) -> None:
    """Schedule a timeout task for collection completion using Redis."""

    async def timeout_handler():
        await asyncio.sleep(_COLLECTION_TIMEOUT_SECONDS)

        # Check if collection still exists and hasn't been processed
        timeout_key = f"{_COLLECTION_TIMEOUT_KEY_PREFIX}{collection_id}"

        # Only process if this worker still owns the timeout
        if await REDIS.exists(timeout_key):  # type: ignore
            accumulated_spans = await _get_accumulated_spans(collection_id)
            if accumulated_spans:
                logger.info(f"Collection {collection_id} timed out, processing accumulated spans")
                await process_completed_collection(collection_id, accumulated_spans, user)
                await _remove_collection_from_accumulation(collection_id)
                await _cancel_collection_timeout(collection_id)

        # Use Redis to ensure only one worker handles the timeout

    async def _schedule_timeout():
        timeout_key = f"{_COLLECTION_TIMEOUT_KEY_PREFIX}{collection_id}"

        # Try to set the timeout key (only succeeds if it doesn't exist)
        if await REDIS.set(timeout_key, "1", nx=True):  # type: ignore
            # This worker owns the timeout, schedule the task
            asyncio.create_task(timeout_handler())

    # process the collection even if we don't get the collection done event
    asyncio.create_task(_schedule_timeout())


class AgentRunData(TypedDict):
    collection_id: str
    agent_run_id: str
    transcripts: Dict[str, Transcript]


telemetry_router = APIRouter()


@telemetry_router.post("/v1/traces")
async def trace_endpoint(
    request: Request,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
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

        # Process based on content type
        if "application/x-protobuf" in content_type:
            # Handle protobuf format
            trace_data = parse_protobuf_traces(body)
        # elif "application/json" in content_type:
        #     # Handle JSON format
        #     trace_data = process_json_traces(body)
        else:
            raise HTTPException(status_code=415, detail=f"Unsupported content type: {content_type}")

        # print(f"Headers: {dict(request.headers)}")

        # Store the raw telemetry data for request
        await mono_svc.store_telemetry_log(user.id, trace_data)

        # Extract spans from trace data
        spans = await extract_spans(trace_data)

        # Accumulate spans and check for trace completion
        await accumulate_and_check_completion(spans, user)

        # Return success response
        return JSONResponse(status_code=200, content={"status": "success", "processed": len(spans)})

    except Exception as e:
        logger.error(f"Error processing traces: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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


# def process_json_traces(body: bytes) -> Dict[str, Any]:
#     """Process JSON formatted trace data."""
#     try:
#         # Decode and parse JSON
#         trace_data = json.loads(body.decode("utf-8"))
#         return trace_data
#     except json.JSONDecodeError as e:
#         logger.error(f"Error parsing JSON traces: {str(e)}")
#         raise ValueError(f"Invalid JSON format: {str(e)}")


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


async def accumulate_and_check_completion(spans: List[Dict[str, Any]], user: User) -> None:
    """
    Accumulate spans and check for collection completion.

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

    # Check for collection completion after all spans are accumulated
    for span in spans:
        span_attrs = span.get("attributes", {})
        collection_id = span_attrs.get("collection_id")
        if not collection_id:
            continue

        # Get accumulated spans for this collection
        accumulated_spans = await _get_accumulated_spans(collection_id)

        # Check if this span indicates collection completion
        if is_collection_complete(span, accumulated_spans):
            # Process the completed collection with all accumulated spans
            await process_completed_collection(collection_id, accumulated_spans, user)

            # Clean up using targeted locks
            await _remove_collection_from_accumulation(collection_id)
            await _cancel_collection_timeout(collection_id)
        else:
            # Schedule timeout for collection completion
            schedule_collection_timeout(collection_id, user)


def is_collection_complete(span: Dict[str, Any], all_spans: List[Dict[str, Any]]) -> bool:
    """
    Check if a collection is complete based on the presence of a trace_end span.

    Args:
        span: The current span being processed
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
    collection_id: str, spans: List[Dict[str, Any]], user: User
) -> None:
    """
    Process a completed collection by creating agent runs and transcripts.

    Args:
        collection_id: The collection ID that was completed
        spans: All spans in the completed collection
    """
    logger.info(f"Processing completed collection {collection_id} with {len(spans)} spans")

    # Process spans to create agent runs
    await store_spans(spans, user)


async def store_spans(spans: List[Dict[str, Any]], user: User) -> None:
    """
    Store spans by creating collections, agent runs, and transcripts.

    Args:
        spans: List of processed span dictionaries
    """
    if not spans:
        return

    # Initialize database service
    mono_svc = await MonoService.init()

    # Organize spans by collection_id -> agent_run_id -> transcript_id -> spans[]
    organized_spans: Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]] = {}

    for span in spans:
        # Extract IDs from span attributes
        span_attrs = span.get("attributes", {})
        collection_id = span_attrs.get("collection_id")
        agent_run_id = span_attrs.get("agent_run_id")
        transcript_id = span_attrs.get("transcript_id")

        if not collection_id:
            logger.warning(f"Skipping span {span.get('span_id')} - missing collection_id")
            # pprint the json span
            print(json.dumps(span, indent=2))
            continue

        organized_spans.setdefault(collection_id, {}).setdefault(agent_run_id, {}).setdefault(
            transcript_id, []
        ).append(span)

    # Process each collection and its agent runs
    total_agent_runs = 0

    logger.info("Organized spans structure:\n%s", json.dumps(organized_spans, indent=2))

    for collection_id, agent_runs in organized_spans.items():
        # Extract service name from the first span in this collection
        collection_name = ""
        for agent_run_id, transcripts in agent_runs.items():
            for transcript_id, transcript_spans in transcripts.items():
                if transcript_spans and len(transcript_spans) > 0:
                    # Get service name from resource attributes of the first span
                    first_span = transcript_spans[0]
                    resource_attributes = first_span.get("resource_attributes", {})
                    collection_name = resource_attributes.get("service.name", "")
                    if collection_name:
                        break

        # Create collection if it doesn't exist
        try:
            if not await mono_svc.collection_exists(collection_id):
                await mono_svc.create_collection(
                    user=user,
                    collection_id=collection_id,
                    name=collection_name,
                    description="",
                )
                logger.info(
                    f"Created collection {collection_id} with service name: {collection_name}"
                )
        except Exception as e:
            logger.error(f"Error creating/checking collection {collection_id}: {str(e)}")
            continue

        # Process agent runs for this collection
        collection_agent_runs: List[AgentRun] = []

        for agent_run_id, transcripts in agent_runs.items():
            logger.info(f"Processing agent_run_id: {agent_run_id}")
            agent_run_transcripts: Dict[str, Transcript] = {}
            agent_run_scores: Dict[str, int | float | bool | None] = {}
            agent_run_model: str | None = None

            # Process each transcript
            for transcript_id, transcript_spans in transcripts.items():
                logger.info(
                    f"  Processing transcript_id: {transcript_id} with {len(transcript_spans)} spans"
                )

                # store all the chat threads
                chat_threads: List[List[ChatMessage]] = []

                for span in transcript_spans:
                    # Check for agent_run_score events
                    for event in span.get("events", []):
                        if event.get("name") == "agent_run_score":
                            score_name = event.get("attributes", {}).get("score.name")
                            score_value = event.get("attributes", {}).get("score.value")
                            if score_name and score_value is not None:
                                agent_run_scores[score_name] = score_value
                                logger.info(f"    Found score: {score_name} = {score_value}")

                    # Extract model from span attributes
                    span_attrs = span.get("attributes", {})
                    if not agent_run_model and "gen_ai.response.model" in span_attrs:
                        agent_run_model = span_attrs["gen_ai.response.model"]
                        logger.info(f"    Found model: {agent_run_model}")

                    # Extract messages from this span
                    span_messages = _span_to_chat_messages(span)

                    if not span_messages:
                        continue

                    # look at each span (which will include the chat history, if any)
                    # if there is only 1 message it's a new chat thread
                    # if there are multiple messages we need to find the chat thread it's continuing
                    # by matching the span messages (+role and order) to the existing chat threads
                    # if we find a match, we add any new messages to the existing chat thread
                    # if we don't find a match, we create a new chat thread

                    if len(span_messages) == 1:
                        # Single message - create new chat thread
                        chat_threads.append(span_messages)
                        logger.debug(f"    Created new chat thread with 1 message")
                    else:
                        # Multiple messages - try to find matching existing thread
                        matched_thread_index = None
                        match_type = None  # 'extend' or 'skip'

                        for i, existing_thread in enumerate(chat_threads):
                            # Case 1: Check if existing thread is a prefix of span_messages (extend existing)
                            if len(span_messages) > len(existing_thread):
                                if matching_thread_start(existing_thread, span_messages):
                                    matched_thread_index = i
                                    match_type = "extend"
                                    logger.debug(
                                        f"    Found matching thread {i} for span with {len(span_messages)} messages (extend existing)"
                                    )
                                    break

                            # Case 2: Check if span_messages is a prefix of existing thread (skip new)
                            elif len(existing_thread) >= len(span_messages):
                                if matching_thread_start(span_messages, existing_thread):
                                    matched_thread_index = i
                                    match_type = "skip"
                                    logger.debug(
                                        f"    Found matching thread {i} for span with {len(span_messages)} messages (skip new - already contained)"
                                    )
                                    break

                        if matched_thread_index is not None:
                            if match_type == "extend":
                                # Found matching thread - add new messages
                                existing_thread = chat_threads[matched_thread_index]
                                new_messages = span_messages[len(existing_thread) :]
                                chat_threads[matched_thread_index].extend(new_messages)
                                logger.info(
                                    f"    Extended chat thread {matched_thread_index} with {len(new_messages)} new messages (reason: matched existing thread). First new message: {new_messages[0].text[:100] if new_messages else 'N/A'}"
                                )
                            else:  # match_type == 'skip'
                                # New messages are already contained in existing thread - skip
                                logger.info(
                                    f"    Skipped span with {len(span_messages)} messages (reason: already contained in thread {matched_thread_index})"
                                )
                        else:
                            # No match found - create new chat thread
                            chat_threads.append(span_messages)
                            logger.info(
                                f"    Created new chat thread with {len(span_messages)} messages (reason: no matching existing thread found)"
                            )
                            # Log span messages in a readable format for debugging
                            for i, span_message in enumerate(span_messages):
                                logger.info(
                                    f"      Span message {i}: role={getattr(span_message, 'role', 'N/A')}, "
                                    f"text={getattr(span_message, 'text', '').strip()[:100]}{'...' if len(getattr(span_message, 'text', '').strip()) > 100 else ''}"
                                )

                # update this to record each chat thread as a transcript
                if chat_threads:
                    # Create a transcript for each chat thread
                    for i, chat_thread in enumerate(chat_threads):
                        # Create unique transcript ID for each thread
                        thread_transcript_id = str(uuid.uuid4())

                        transcript = Transcript(
                            id=thread_transcript_id,
                            messages=chat_thread,
                            name=f"Chat Thread {i + 1}" if len(chat_threads) > 1 else "",
                            description="",
                        )
                        agent_run_transcripts[thread_transcript_id] = transcript
                        logger.info(
                            f"    Created transcript {thread_transcript_id} with {len(chat_thread)} messages"
                        )
                else:
                    logger.warning(
                        f"    No messages extracted from {len(transcript_spans)} spans for transcript {transcript_id}"
                    )
                    # Log span details for debugging
                    for i, span in enumerate(transcript_spans):
                        span_attrs = span.get("attributes", {})
                        logger.debug(
                            f"      Span {i}: {span.get('operation_name')} - keys: {list(span_attrs.keys())}"
                        )

                    # Create agent run if it has transcripts
            if agent_run_transcripts:
                # Create metadata with scores and model using BaseAgentRunMetadata
                metadata_dict: Dict[str, Any] = {"scores": agent_run_scores}
                if agent_run_model:
                    metadata_dict["model"] = agent_run_model

                metadata = BaseAgentRunMetadata(**metadata_dict)
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
                # Log transcript details for debugging
                for transcript_id, transcript_spans in transcripts.items():
                    logger.debug(f"    Transcript {transcript_id}: {len(transcript_spans)} spans")

        # Add agent runs to this collection
        if collection_agent_runs:
            try:
                # Get or create default view context for this collection
                ctx = await mono_svc.get_default_view_ctx(collection_id, user)

                # Add agent runs using the existing service method
                await mono_svc.add_agent_runs(ctx, collection_agent_runs)
                logger.info(
                    f"Added {len(collection_agent_runs)} agent runs to collection {collection_id}"
                )
                total_agent_runs += len(collection_agent_runs)
            except Exception as e:
                logger.error(f"Error adding agent runs to collection {collection_id}: {str(e)}")
        else:
            logger.warning(f"No agent runs created for collection {collection_id}")
            # Log agent run details for debugging
            for agent_run_id, transcripts in agent_runs.items():
                logger.debug(f"  Agent run {agent_run_id}: {len(transcripts)} transcripts")

    logger.info(f"Processed {len(spans)} spans into {total_agent_runs} agent runs")


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
        for key in sorted(gen_ai["prompt"].keys(), key=lambda k: int(k) if k.isdigit() else k):
            prompt_data: dict[str, Any] = gen_ai["prompt"][key]

            message = _create_message_from_data(prompt_data, span_id, f"prompt_{key}")
            if message:
                messages.append(message)

    # Process completion messages
    if "completion" in gen_ai:
        # Sort keys numerically to maintain proper order
        for key in sorted(gen_ai["completion"].keys(), key=lambda k: int(k) if k.isdigit() else k):
            completion_data: dict[str, Any] = gen_ai["completion"][key]

            message = _create_message_from_data(completion_data, span_id, f"completion_{key}")
            if message:
                messages.append(message)

    return messages


def _create_message_from_data(
    data: Dict[str, Any], span_id: str, context: str
) -> ChatMessage | None:
    """Create a ChatMessage from structured data."""
    if "role" not in data:
        logger.warning(f"Missing role in {context} data for span {span_id}")
        return None

    try:
        role = str(data["role"])
        if role == "developer":
            role = "system"

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

    except ValueError as e:
        logger.error(f"Invalid role '{data.get('role')}' in {context} for span {span_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to parse {context} message for span {span_id}: {e}")
        return None
