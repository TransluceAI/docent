import asyncio
import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, TypedDict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from docent._log_util import get_logger
from docent.data_models import AgentRun, BaseAgentRunMetadata, Transcript
from docent.data_models.chat import ChatMessage, parse_chat_message
from docent_core._db_service.service import MonoService

logger = get_logger(__name__)

# Global state for accumulating spans across multiple requests
_accumulated_spans: Dict[str, List[Dict[str, Any]]] = {}
_trace_completion_tasks: Dict[str, asyncio.Task[None]] = {}
_TRACE_TIMEOUT_SECONDS = 5 * 60  # Timeout for trace completion


class AgentRunData(TypedDict):
    collection_id: str
    agent_run_id: str
    transcripts: Dict[str, Transcript]


telemetry_router = APIRouter()


@telemetry_router.post("/v1/traces")
async def trace_endpoint(request: Request):
    """
    Direct trace endpoint for OpenTelemetry collector HTTP exporter.

    This endpoint accepts OTLP HTTP format telemetry data and logs it.
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
            trace_data = process_protobuf_traces(body)
        elif "application/json" in content_type:
            # Handle JSON format
            trace_data = process_json_traces(body)
        else:
            raise HTTPException(status_code=415, detail=f"Unsupported content type: {content_type}")

        # Process the traces
        processing_result = await process_traces(trace_data)

        # Return success response
        return JSONResponse(
            status_code=200, content={"status": "success", "processed": processing_result["count"]}
        )

    except Exception as e:
        logger.error(f"Error processing traces: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def process_protobuf_traces(body: bytes) -> Dict[str, Any]:
    """Process protobuf formatted trace data."""
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


def process_json_traces(body: bytes) -> Dict[str, Any]:
    """Process JSON formatted trace data."""
    try:
        # Decode and parse JSON
        trace_data = json.loads(body.decode("utf-8"))
        return trace_data
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON traces: {str(e)}")
        raise ValueError(f"Invalid JSON format: {str(e)}")


async def process_traces(trace_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process the trace data - extract spans, accumulate them, and detect trace completion.

    Args:
        trace_data: Dictionary containing OTLP trace data

    Returns:
        Processing result with statistics
    """
    processed_spans: List[Dict[str, Any]] = []
    total_spans = 0

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
                    processed_span = process_single_span(
                        span, resource_attrs, scope_name, scope_version
                    )
                    processed_spans.append(processed_span)
                    total_spans += 1

        # Accumulate spans and check for trace completion
        await accumulate_and_check_completion(processed_spans)

        return {
            "count": total_spans,
            "resource_count": len(resource_spans),
            "spans": processed_spans,
        }

    except Exception as e:
        logger.error(f"Error in trace processing: {str(e)}")
        raise


def extract_attributes(attributes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract attributes from OTLP format to a simple dictionary."""
    result: Dict[str, Any] = {}

    for attr in attributes:
        key = attr.get("key", "")
        value = attr.get("value", {})

        # Extract the actual value based on its type
        if "string_value" in value:
            result[key] = value["string_value"]
        elif "int_value" in value:
            result[key] = int(value["int_value"])
        elif "double_value" in value:
            result[key] = float(value["double_value"])
        elif "bool_value" in value:
            result[key] = bool(value["bool_value"])
        elif "array_value" in value:
            result[key] = extract_array_value(value["array_value"])
        elif "kvlist_value" in value:
            result[key] = extract_kvlist_value(value["kvlist_value"])

    return result


def extract_array_value(array_value: Dict[str, Any]) -> List[Any]:
    """Extract array values from OTLP format."""
    values: List[Any] = []
    for item in array_value.get("values", []):
        if "string_value" in item:
            values.append(item["string_value"])
        elif "int_value" in item:
            values.append(int(item["int_value"]))
        elif "double_value" in item:
            values.append(float(item["double_value"]))
        elif "bool_value" in item:
            values.append(bool(item["bool_value"]))
    return values


def extract_kvlist_value(kvlist: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key-value list from OTLP format."""
    return extract_attributes(kvlist.get("values", []))


def process_single_span(
    span: Dict[str, Any], resource_attrs: Dict[str, Any], scope_name: str, scope_version: str
) -> Dict[str, Any]:
    """Process a single span and extract relevant information."""

    # Extract span details
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
    start_time = datetime.fromtimestamp(start_time_ns / 1e9, tz=timezone.utc)
    end_time = datetime.fromtimestamp(end_time_ns / 1e9, tz=timezone.utc)
    duration_ms = (end_time_ns - start_time_ns) / 1e6

    # Extract span attributes
    span_attrs = extract_attributes(span.get("attributes", []))

    # Extract events
    events: List[Dict[str, Any]] = []
    for event in span.get("events", []):
        events.append(
            {
                "name": event.get("name", ""),
                "timestamp": int(event.get("time_unix_nano", 0)) / 1e9,
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

    # Build the processed span
    processed_span: Dict[str, Any] = {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "operation_name": span.get("name", ""),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_ms": duration_ms,
        "status": {
            "code": span.get("status", {}).get("code", 0),
            "message": span.get("status", {}).get("message", ""),
        },
        "kind": span.get("kind", 0),
        "resource_attributes": resource_attrs,
        "span_attributes": span_attrs,
        "events": events,
        "links": links,
        "scope": {"name": scope_name, "version": scope_version},
    }

    return processed_span


async def accumulate_and_check_completion(spans: List[Dict[str, Any]]) -> None:
    """
    Accumulate spans and check for trace completion.

    Args:
        spans: List of processed spans to accumulate
    """
    global _accumulated_spans, _trace_completion_tasks

    # First, add all spans to accumulation
    for span in spans:
        trace_id = span.get("trace_id")
        if not trace_id:
            continue

        # Initialize trace accumulation if not exists
        if trace_id not in _accumulated_spans:
            _accumulated_spans[trace_id] = []

        # Add span to accumulation
        _accumulated_spans[trace_id].append(span)

    # Then check for trace completion after all spans are accumulated
    for span in spans:
        trace_id = span.get("trace_id")
        if not trace_id:
            continue

        # Check if this span indicates trace completion
        if is_trace_complete(span, _accumulated_spans[trace_id]):
            # Process the completed trace with all accumulated spans
            await process_completed_trace(trace_id, _accumulated_spans[trace_id])

            # Clean up
            del _accumulated_spans[trace_id]
            if trace_id in _trace_completion_tasks:
                _trace_completion_tasks[trace_id].cancel()
                del _trace_completion_tasks[trace_id]
        else:
            # Schedule timeout for trace completion
            schedule_trace_timeout(trace_id)


def is_trace_complete(span: Dict[str, Any], all_spans: List[Dict[str, Any]]) -> bool:
    """
    Check if a trace is complete based on span status and structure.

    Args:
        span: The current span being processed
        all_spans: All spans in the trace

    Returns:
        True if the trace appears to be complete
    """
    # Check if this is a root span (no parent)
    if not span.get("parent_span_id"):
        return True

    return False


def schedule_trace_timeout(trace_id: str) -> None:
    """Schedule a timeout task for trace completion."""
    global _trace_completion_tasks

    # Cancel existing timeout if any
    if trace_id in _trace_completion_tasks:
        _trace_completion_tasks[trace_id].cancel()

    # Create new timeout task
    async def timeout_handler():
        await asyncio.sleep(_TRACE_TIMEOUT_SECONDS)
        if trace_id in _accumulated_spans:
            logger.info(f"Trace {trace_id} timed out, processing accumulated spans")
            await process_completed_trace(trace_id, _accumulated_spans[trace_id])
            del _accumulated_spans[trace_id]
            if trace_id in _trace_completion_tasks:
                del _trace_completion_tasks[trace_id]

    _trace_completion_tasks[trace_id] = asyncio.create_task(timeout_handler())


async def process_completed_trace(trace_id: str, spans: List[Dict[str, Any]]) -> None:
    """
    Process a completed trace by creating collections, agent runs, and transcripts.

    Args:
        trace_id: The trace ID that was completed
        spans: All spans in the completed trace
    """
    logger.info(f"Processing completed trace {trace_id} with {len(spans)} spans")

    # Process spans to create agent runs
    await store_spans(spans)


async def store_spans(spans: List[Dict[str, Any]]) -> None:
    """
    Store spans by creating collections, agent runs, and transcripts.

    Args:
        spans: List of processed span dictionaries
    """
    if not spans:
        return

    # Initialize database service
    mono_svc = await MonoService.init()

    # Get test user for telemetry operations (for testing purposes)
    # You can change this email to your test user's email
    test_user_email = "gregor@transluce.org"  # Change this to your test user's email
    user = await mono_svc.get_user_by_email(test_user_email)

    if not user:
        # Fallback to anonymous user if test user doesn't exist
        logger.warning(f"Test user {test_user_email} not found, creating anonymous user")
        user = await mono_svc.create_anonymous_user()
    else:
        logger.info(f"Using test user: {user.email} (ID: {user.id})")

    # Organize spans by collection_id -> agent_run_id -> transcript_id -> spans[]
    organized_spans: Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]] = {}

    for span in spans:
        # Extract IDs from span attributes
        span_attrs = span.get("span_attributes", {})
        collection_id = span_attrs.get("collection_id")
        agent_run_id = span_attrs.get("agent_run_id")
        transcript_id = span_attrs.get("transcript_id")

        if not collection_id or not agent_run_id:
            logger.warning(
                f"Skipping span {span.get('span_id')} - missing collection_id or agent_run_id"
            )
            continue

        # Use setdefault to organize spans (following existing codebase patterns)
        organized_spans.setdefault(collection_id, {}).setdefault(agent_run_id, {}).setdefault(
            transcript_id, []
        ).append(span)

    # Process each collection and its agent runs
    total_agent_runs = 0

    for collection_id, agent_runs in organized_spans.items():
        # Extract service name from the first span in this collection
        collection_name = ""
        for agent_run_id, transcripts in agent_runs.items():
            for transcript_id, transcript_spans in transcripts.items():
                if transcript_spans:
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

                # Convert spans to chat messages and collect scores
                messages: List[ChatMessage] = []

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
                    span_attrs = span.get("span_attributes", {})
                    if not agent_run_model and "gen_ai.response.model" in span_attrs:
                        agent_run_model = span_attrs["gen_ai.response.model"]
                        logger.info(f"    Found model: {agent_run_model}")

                    # Convert span to chat messages and deduplicate
                    span_messages = _span_to_chat_message(span)
                    new_messages = _deduplicate_messages(span_messages, messages)

                    if new_messages:
                        logger.debug(
                            f"    Added {len(new_messages)} new messages from span {span.get('span_id')}"
                        )
                        messages.extend(new_messages)
                    else:
                        logger.debug(
                            f"    No new messages from span {span.get('span_id')} (all duplicates)"
                        )

                if messages:
                    # Create transcript directly with ChatMessage objects
                    transcript = Transcript(
                        id=transcript_id,
                        messages=messages,
                        name="",
                        description="",
                    )
                    agent_run_transcripts[transcript_id] = transcript
                    logger.info(
                        f"    Created transcript {transcript_id} with {len(messages)} messages"
                    )
                else:
                    logger.warning(
                        f"    No messages extracted from {len(transcript_spans)} spans for transcript {transcript_id}"
                    )
                    # Log span details for debugging
                    for i, span in enumerate(transcript_spans):
                        span_attrs = span.get("span_attributes", {})
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


def _span_to_chat_message(span: Dict[str, Any]) -> List[ChatMessage]:
    """Convert a span to a list of chat message objects."""
    span_attrs = span.get("span_attributes", {})
    messages: List[ChatMessage] = []

    # Debug logging
    span_id = span.get("span_id", "unknown")
    operation_name = span.get("operation_name", "unknown")
    logger.debug(f"Processing span {span_id} ({operation_name}) with {len(span_attrs)} attributes")

    # Extract prompt messages from gen_ai.prompt.{index}.role/content format
    prompt_messages: Dict[int, Dict[str, str]] = {}

    for key, value in span_attrs.items():
        prefix = "gen_ai.prompt."
        if key.startswith(prefix) and "." in key[len(prefix) :]:
            # Extract index and field (role or content)
            parts = key[len(prefix) :].split(".", 1)
            if len(parts) == 2:
                try:
                    index = int(parts[0])
                    field = parts[1]
                    if field in ["role", "content"]:
                        if index not in prompt_messages:
                            prompt_messages[index] = {}
                        prompt_messages[index][field] = str(value)
                except Exception as e:
                    logger.error(f"Failed to parse prompt message key '{key}': {e}")
                    continue

    # Convert prompt messages to ChatMessage objects
    for index in sorted(prompt_messages.keys()):
        msg_data = prompt_messages[index]
        if "role" in msg_data and "content" in msg_data:
            try:
                message = parse_chat_message(
                    {
                        "role": msg_data["role"],
                        "content": msg_data["content"],
                    }
                )
                messages.append(message)
            except ValueError as e:
                logger.error(
                    f"Invalid role '{msg_data['role']}' in span {span.get('span_id')} at prompt index {index}: {e}"
                )
                continue
            except Exception as e:
                logger.error(f"Failed to parse message at index {index}: {e}")
                continue

    # Extract completion messages from gen_ai.completion.{index}.role/content format
    completion_messages: Dict[int, Dict[str, str]] = {}

    for key, value in span_attrs.items():
        prefix = "gen_ai.completion."
        if key.startswith(prefix) and "." in key[len(prefix) :]:
            # Extract index and field (role or content)
            parts = key[len(prefix) :].split(".", 1)
            if len(parts) == 2:
                try:
                    index = int(parts[0])
                    field = parts[1]
                    if field in ["role", "content"]:
                        if index not in completion_messages:
                            completion_messages[index] = {}
                        completion_messages[index][field] = str(value)
                except Exception as e:
                    logger.error(f"Failed to parse completion message key '{key}': {e}")
                    continue

    # Convert completion messages to ChatMessage objects
    for index in sorted(completion_messages.keys()):
        msg_data = completion_messages[index]
        if "role" in msg_data and "content" in msg_data:
            try:
                completion_message = parse_chat_message(
                    {
                        "role": msg_data["role"],
                        "content": msg_data["content"],
                    }
                )
                messages.append(completion_message)
            except ValueError as e:
                logger.error(
                    f"Invalid completion role '{msg_data['role']}' in span {span.get('span_id')} at completion index {index}: {e}"
                )
            except Exception as e:
                logger.error(f"Failed to parse completion message at index {index}: {e}")

    # Debug logging
    if messages:
        logger.debug(f"Extracted {len(messages)} messages from span {span_id}")
    else:
        logger.debug(
            f"No messages extracted from span {span_id} - prompt_messages: {len(prompt_messages)}, completion_messages: {len(completion_messages)}"
        )

    return messages


def _deduplicate_messages(
    span_messages: List[ChatMessage],
    existing_messages: List[ChatMessage],
) -> List[ChatMessage]:
    """
    Deduplicate messages from a span and log conflicts.

    Args:
        span_messages: Messages extracted from the current span
        existing_messages: List of messages already processed

    Returns:
        List of new messages that should be added
    """

    new_messages: List[ChatMessage] = []

    for i, message in enumerate(span_messages):
        # Check if we already have a message at this index
        if i < len(existing_messages):
            existing_message = existing_messages[i]

            # Check if the message content matches what we've seen before
            if existing_message.role != message.role or existing_message.content != message.content:
                changes: List[str] = []
                if existing_message.role != message.role:
                    changes.append(f"role: '{existing_message.role}' -> '{message.role}'")
                if existing_message.content != message.content:
                    changes.append(f"content: '{existing_message.content}' -> '{message.content}'")

                logger.error(f"Message at index {i} changed: {', '.join(changes)}")
                continue
            # Message already exists and matches, skip it
            continue
        else:
            # This is a new message, add it
            new_messages.append(message)

    return new_messages
