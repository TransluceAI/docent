import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, cast
from uuid import uuid4

from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent.data_models import (
    AgentRun,
    Transcript,
    TranscriptGroup,
)
from docent.data_models.chat import (
    ChatMessage,
    Content,
    ContentReasoning,
    ContentText,
    ToolMessage,
    parse_chat_message,
)
from docent.data_models.chat.tool import ToolCall
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import (
    SQLAAgentRun,
    SQLATelemetryAgentRunStatus,
    SQLATelemetryLog,
    SQLATranscript,
    SQLATranscriptGroup,
    TelemetryAgentRunStatus,
    sanitize_pg_text,
)
from docent_core.docent.services.monoservice import (
    MonoService,
    sort_transcript_groups_by_parent_order,
)
from docent_core.docent.services.telemetry_accumulation import TelemetryAccumulationService

logger = get_logger(__name__)


class TelemetryService:
    def __init__(self, session: AsyncSession, mono_svc: MonoService):
        self.session = session
        self.mono_svc = mono_svc

    ###################
    # Telemetry Logs  #
    ###################

    async def store_telemetry_log(
        self,
        user_id: str,
        type: str,
        version: str,
        json_data: dict[str, Any],
        *,
        collection_id: str | None = None,
    ) -> str:
        """Store telemetry log data in the database."""
        # Sanitize the JSON data to remove null characters and other problematic Unicode sequences
        # Convert to JSON string, sanitize, then parse back to dict
        json_str = json.dumps(json_data)
        sanitized_json_str = sanitize_pg_text(json_str)
        sanitized_json_data = json.loads(sanitized_json_str)

        telemetry_id = str(uuid4())
        self.session.add(
            SQLATelemetryLog(
                id=telemetry_id,
                user_id=user_id,
                collection_id=collection_id,
                type=type,
                version=version,
                json_data=sanitized_json_data,
            )
        )
        await self.session.commit()
        return telemetry_id

    async def update_telemetry_log_collection_id(self, telemetry_id: str, collection_id: str):
        """Update the collection ID for a telemetry log entry."""
        await self.session.execute(
            update(SQLATelemetryLog)
            .where(SQLATelemetryLog.id == telemetry_id)
            .values(collection_id=collection_id)
        )

    async def get_telemetry_log(self, telemetry_id: str) -> SQLATelemetryLog | None:
        """Get a telemetry log entry by ID."""
        result = await self.session.execute(
            select(SQLATelemetryLog).where(SQLATelemetryLog.id == telemetry_id)
        )
        return result.scalar_one_or_none()

    async def get_telemetry_logs_by_user(
        self, user_id: str, limit: int = 100
    ) -> list[SQLATelemetryLog]:
        """Get telemetry logs for a user, ordered by creation time (newest first)."""
        result = await self.session.execute(
            select(SQLATelemetryLog)
            .where(SQLATelemetryLog.user_id == user_id)
            .order_by(SQLATelemetryLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_telemetry_logs_by_collection(
        self, collection_id: str, limit: int = 100
    ) -> list[SQLATelemetryLog]:
        """Get telemetry logs for a collection, ordered by creation time (newest first)."""
        result = await self.session.execute(
            select(SQLATelemetryLog)
            .where(SQLATelemetryLog.collection_id == collection_id)
            .order_by(SQLATelemetryLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    ######################
    # Trace Processing   #
    ######################

    async def process_agent_runs_for_collection(self, collection_id: str, user: User) -> List[str]:
        """
        Process all agent runs that need processing for a collection.

        This method handles the complete processing workflow for a collection,
        processing each agent run individually by pulling its accumulated data
        and creating the necessary database objects.

        Args:
            collection_id: The collection ID to process
            user: The user who initiated the processing

        Returns:
            List[str]: List of agent run IDs that were successfully processed
        """
        # Atomically get agent runs that need processing and mark them as processing
        agent_run_versions = await self.get_and_mark_agent_runs_for_processing(collection_id)

        if not agent_run_versions:
            logger.info(f"No agent runs need processing for collection {collection_id}")
            return []

        logger.info(
            f"Found and marked {len(agent_run_versions)} agent runs for processing in collection {collection_id}"
        )

        # Process each agent run individually
        processed_count = 0
        successfully_processed_agent_run_ids: List[str] = []
        successfully_processed_versions: dict[str, int] = {}

        for agent_run_id, current_version in agent_run_versions.items():
            try:
                logger.info(
                    f"Processing agent run {agent_run_id} (version {current_version}) in collection {collection_id}"
                )

                # Process this agent run (handles both new and existing agent runs)
                success = await self._process_single_agent_run(
                    agent_run_id,
                    collection_id,
                    user,
                )

                if success:
                    processed_count += 1
                    successfully_processed_agent_run_ids.append(agent_run_id)
                    successfully_processed_versions[agent_run_id] = current_version
                    logger.info(
                        f"Successfully processed agent run {agent_run_id} (version {current_version})"
                    )
                else:
                    logger.error(f"Failed to process agent run {agent_run_id}")
                    # Mark agent run as errored on failure
                    await self._mark_agent_runs_as_errored(
                        collection_id, {agent_run_id}, "Processing failed"
                    )

            except Exception as e:
                # Mark agent run as needs_processing again if processing failed
                await self._mark_agent_runs_as_errored(collection_id, {agent_run_id}, str(e))
                logger.error(f"Error processing agent run {agent_run_id}: {str(e)}")
                continue

        # Mark all successfully processed agent runs as completed with their versions
        if successfully_processed_versions:
            await self._mark_agent_runs_as_completed(collection_id, successfully_processed_versions)

        logger.info(
            f"Successfully processed {processed_count} out of {len(agent_run_versions)} agent runs in collection {collection_id}"
        )

        # Track with analytics if available
        try:
            analytics = AnalyticsClient()
            with analytics.user_context(user):
                analytics.track_event(
                    "telemetry_processing_completed",
                    properties={
                        "collection_id": collection_id,
                        "agent_runs_attempted": len(agent_run_versions),
                        "agent_runs_processed": processed_count,
                    },
                )
        except Exception as e:
            logger.warning(f"Failed to track analytics event: {str(e)}")

        return successfully_processed_agent_run_ids

    async def check_agent_run_needs_reprocessing(
        self, collection_id: str, agent_run_id: str
    ) -> bool:
        """
        Check if an agent run needs reprocessing by comparing current_version to processed_version.

        Args:
            collection_id: The collection ID
            agent_run_id: The agent run ID

        Returns:
            True if the agent run needs reprocessing (current_version > processed_version)
        """
        result = await self.session.execute(
            select(
                SQLATelemetryAgentRunStatus.current_version,
                SQLATelemetryAgentRunStatus.processed_version,
            ).where(
                SQLATelemetryAgentRunStatus.collection_id == collection_id,
                SQLATelemetryAgentRunStatus.agent_run_id == agent_run_id,
            )
        )

        row = result.first()
        if not row:
            return False

        return row.current_version > row.processed_version

    async def _process_single_agent_run(
        self,
        agent_run_id: str,
        collection_id: str,
        user: User,
    ) -> bool:
        """
        Process a single agent run by creating all necessary database objects.

        Args:
            agent_run_id: The agent run ID to process
            collection_id: The collection ID
            user: The user creating the agent run

        Returns:
            bool: True if processing was successful, False otherwise
        """
        try:
            from docent_core.docent.services.telemetry_accumulation import (
                TelemetryAccumulationService,
            )

            accumulation_service = TelemetryAccumulationService(self.session)

            agent_run_spans = await accumulation_service.get_agent_run_spans(
                collection_id, agent_run_id
            )
            if not agent_run_spans:
                logger.info(f"No spans found for agent run {agent_run_id}")
                return True  # Consider this a success even with no spans

            agent_run_scores = await accumulation_service.get_agent_run_scores(
                collection_id, agent_run_id
            )
            agent_run_metadata = await accumulation_service.get_agent_run_metadata(
                collection_id, agent_run_id
            )
            agent_run_transcript_group_metadata = (
                await accumulation_service.get_agent_run_transcript_group_metadata(
                    collection_id, agent_run_id
                )
            )

            # Organize spans by transcript_id -> spans[]
            spans_by_transcript: Dict[str, List[Dict[str, Any]]] = {}
            default_transcript_id = str(uuid4())
            for span in agent_run_spans:
                transcript_id = span.get("attributes", {}).get("transcript_id")
                if not transcript_id:
                    span["attributes"]["transcript_id"] = default_transcript_id
                    transcript_id = default_transcript_id
                if transcript_id:
                    if transcript_id not in spans_by_transcript:
                        spans_by_transcript[transcript_id] = []
                    spans_by_transcript[transcript_id].append(span)

            # Create transcript groups for this agent run
            transcript_groups = []
            if agent_run_transcript_group_metadata:
                transcript_groups = self._create_transcript_groups_from_accumulation_data(
                    agent_run_transcript_group_metadata
                )

            # Create agent run from spans
            agent_run_spans_dict = {agent_run_id: spans_by_transcript}
            transcript_groups_by_agent_run = {agent_run_id: transcript_groups}
            collection_scores = {agent_run_id: agent_run_scores}
            collection_metadata = {agent_run_id: agent_run_metadata}

            # Create agent run from spans
            collection_agent_runs = await self._create_agent_runs_from_spans(
                agent_run_spans_dict,
                transcript_groups_by_agent_run,
                collection_scores,
                collection_metadata,
            )

            if not collection_agent_runs:
                logger.warning(f"No agent run created from spans for {agent_run_id}")
                return False

            # TODO(gregor): Use the original user who created the telemetry data instead of the processing user
            # Get or create default view context for this collection
            ctx = await self.mono_svc.get_default_view_ctx(collection_id, user)
            # Store the agent run in the database
            await self.update_agent_runs_for_telemetry(ctx, collection_agent_runs)

            logger.info(
                f"Successfully created agent run {agent_run_id} with {len(spans_by_transcript)} transcripts"
            )
            return True

        except Exception as e:
            logger.error(f"Error processing single agent run {agent_run_id}: {str(e)}")
            return False

    def extract_collection_info_from_spans(
        self,
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

    async def ensure_collections_exist(
        self, collection_ids: set[str], collection_names: Dict[str, str], user: User
    ) -> None:
        """
        Ensure all collections exist, creating them if necessary.

        Args:
            collection_ids: Set of collection IDs to ensure exist
            collection_names: Dictionary mapping collection IDs to their names
            user: The user creating the collections
        """
        for collection_id in collection_ids:
            try:
                collection_name = collection_names.get(collection_id)
                await self.ensure_collection_exists(collection_id, user, collection_name)
            except Exception as e:
                logger.error(f"Error creating/checking collection {collection_id}: {str(e)}")
                raise

    async def ensure_collection_exists(
        self, collection_id: str, user: User, collection_name: str | None = None
    ) -> None:
        """
        Ensure a collection exists, creating it with the specified name if it doesn't.
        Update the name if it's currently not set.

        Args:
            collection_id: The collection ID to ensure exists
            collection_name: The name to use for the collection
            user: The user creating the collection
        """
        try:
            if not await self.mono_svc.collection_exists(collection_id):
                try:
                    await self.mono_svc.create_collection(
                        user=user,
                        collection_id=collection_id,
                        name=collection_name,
                        description="",
                    )
                    logger.info(f"Created collection {collection_id} with name: {collection_name}")
                except IntegrityError as e:
                    logger.info(
                        f"Collection {collection_id} was created by another process: {str(e)}"
                    )
            else:
                if collection_name:
                    collection = await self.mono_svc.get_collection(collection_id)
                    if collection and not collection.name:
                        await self.mono_svc.update_collection(
                            collection_id=collection_id,
                            name=collection_name,
                        )
        except Exception as e:
            logger.error(f"Error creating collection {collection_id}: {str(e)}")
            raise

    async def ensure_write_permission_for_collections(
        self, collection_ids: set[str], user: User
    ) -> None:
        """
        Check that the user has write permissions on all collections,
        or that the collections don't exist yet (in which case they will be created).

        Args:
            collection_ids: Set of collection IDs to check
            user: The authenticated user

        Raises:
            HTTPException: If user lacks write permissions on any existing collection
        """
        from fastapi import HTTPException

        from docent_core.docent.db.schemas.auth_models import Permission, ResourceType

        # Check permissions for each collection
        for collection_id in collection_ids:
            # Check if collection exists
            collection_exists = await self.mono_svc.collection_exists(collection_id)

            if collection_exists:
                # Collection exists - check write permissions
                has_write_permission = await self.mono_svc.has_permission(
                    user=user,
                    resource_type=ResourceType.COLLECTION,
                    resource_id=collection_id,
                    permission=Permission.WRITE,
                )

                if not has_write_permission:
                    logger.error(
                        f"Permission denied for user {user.id} on collection {collection_id}"
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"Write permission required on collection {collection_id}",
                    )
            else:
                # Collection doesn't exist - this is allowed, it will be created later
                logger.info(
                    f"Collection {collection_id} doesn't exist yet, will be created during processing"
                )

    async def ensure_write_permission_for_collection(self, collection_id: str, user: User) -> None:
        """
        Check that the user has write permissions on a single collection,
        or that the collection doesn't exist yet (in which case it will be created).

        Args:
            collection_id: The collection ID to check
            user: The authenticated user

        Raises:
            HTTPException: If user lacks write permissions on the existing collection
        """
        await self.ensure_write_permission_for_collections({collection_id}, user)

    def parse_protobuf_traces(self, body: bytes) -> Dict[str, Any]:
        """Parse protobuf formatted trace data."""
        try:
            # Parse the protobuf message
            export_request = trace_service_pb2.ExportTraceServiceRequest()
            export_request.ParseFromString(body)

            # Convert to dictionary for easier processing
            trace_data = MessageToDict(export_request, preserving_proto_field_name=True)

            # Sanitize the trace data to remove null characters and other problematic Unicode sequences
            # Convert to JSON string, sanitize, then parse back to dict
            json_str = json.dumps(trace_data)
            sanitized_json_str = sanitize_pg_text(json_str)
            sanitized_trace_data = json.loads(sanitized_json_str)
            return sanitized_trace_data
        except Exception as e:
            logger.error(f"Error parsing protobuf traces: {str(e)}")
            raise ValueError(f"Invalid protobuf format: {str(e)}")

    async def extract_spans(self, trace_data: Dict[str, Any]) -> List[Dict[str, Any]]:
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
                resource_attrs = self.extract_attributes(resource.get("attributes", []))

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
                        extracted_span = self.otel_span_format_to_dict(
                            span, resource_attrs, scope_name, scope_version
                        )
                        extracted_spans.append(extracted_span)

                        logger.debug(
                            f"  Extracted span: {self._get_span_debug_info(extracted_span)}"
                        )

            return extracted_spans

        except Exception as e:
            logger.error(f"Error extracting spans: {str(e)}")
            raise

    def _extract_single_value(self, value: Dict[str, Any]) -> Any:
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
            return self.extract_array_value(value["array_value"])
        elif "kvlist_value" in value:
            return self.extract_kvlist_value(value["kvlist_value"])
        else:
            return None

    def extract_attributes(self, attributes: List[Dict[str, Any]]) -> Dict[str, Any]:
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
            result[key] = self._extract_single_value(value)

        return result

    def extract_array_value(self, array_value: Dict[str, Any]) -> List[Any]:
        """Extract array values from OTLP format."""
        values: List[Any] = []
        for item in array_value.get("values", []):
            extracted_value = self._extract_single_value(item)
            if extracted_value is not None:
                values.append(extracted_value)
        return values

    def extract_kvlist_value(self, kvlist: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key-value list from OTLP format."""
        return self.extract_attributes(kvlist.get("values", []))

    def otel_span_format_to_dict(
        self,
        span: Dict[str, Any],
        resource_attrs: Dict[str, Any],
        scope_name: str,
        scope_version: str,
    ) -> Dict[str, Any]:
        """Process a single span and extract relevant information, preserving any additional fields."""

        # Extract and convert span details
        raw_span_id = span.get("span_id", "")
        raw_trace_id = span.get("trace_id", "")
        raw_parent_span_id = span.get("parent_span_id", "")

        # Convert IDs from base64 if necessary
        span_id = raw_span_id
        trace_id = raw_trace_id
        parent_span_id = raw_parent_span_id

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
        span_attrs = self.extract_attributes(span.get("attributes", []))

        # Extract events
        events: List[Dict[str, Any]] = []
        for event in span.get("events", []):
            events.append(
                {
                    "name": event.get("name", ""),
                    "timestamp": datetime.fromtimestamp(
                        int(event.get("time_unix_nano", 0)) / 1e9, tz=timezone.utc
                    ).isoformat(),
                    "attributes": self.extract_attributes(event.get("attributes", [])),
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
                    "attributes": self.extract_attributes(link.get("attributes", [])),
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
                "raw_span_id": raw_span_id,
                "raw_trace_id": raw_trace_id,
                "raw_parent_span_id": raw_parent_span_id,
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

        # Sanitize the processed span to remove null characters and other problematic Unicode sequences
        # Convert to JSON string, sanitize, then parse back to dict
        json_str = json.dumps(processed_span)
        sanitized_json_str = sanitize_pg_text(json_str)
        sanitized_span = json.loads(sanitized_json_str)
        return sanitized_span

    async def accumulate_spans(
        self,
        spans: List[Dict[str, Any]],
        user_id: str | None = None,
        accumulation_service: TelemetryAccumulationService | None = None,
    ) -> None:
        """
        Accumulate spans by collection_id for later processing and mark agent runs as needing processing.

        Args:
            spans: List of processed spans to accumulate
            user_id: Optional user ID for tracking who created the spans
            accumulation_service: Optional service instance to use
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
            else:
                logger.error(
                    f"Skipping span - missing collection_id - {self._get_span_debug_info(span)}"
                )

        # Add spans to accumulation
        for collection_id, collection_spans in spans_by_collection.items():
            if accumulation_service:
                await accumulation_service.add_spans(collection_id, collection_spans, user_id)
            else:
                logger.error("Accumulation service not found, skipping accumulation")

    async def get_and_mark_agent_runs_for_processing(self, collection_id: str) -> dict[str, int]:
        """
        Atomically get agent runs that need processing and mark them as processing.
        Returns both the agent run IDs and their current versions.

        Args:
            collection_id: The collection ID

        Returns:
            Dictionary mapping agent_run_id to current_version for successfully marked agent runs
        """

        stmt = (
            update(SQLATelemetryAgentRunStatus)
            .where(
                or_(
                    SQLATelemetryAgentRunStatus.status
                    == TelemetryAgentRunStatus.NEEDS_PROCESSING.value,
                    SQLATelemetryAgentRunStatus.current_version
                    > SQLATelemetryAgentRunStatus.processed_version,
                ),
                SQLATelemetryAgentRunStatus.collection_id == collection_id,
            )
            .values(status=TelemetryAgentRunStatus.PROCESSING.value)
            .returning(
                SQLATelemetryAgentRunStatus.agent_run_id,
                SQLATelemetryAgentRunStatus.current_version,
            )
        )

        # Log the SQL query for debugging
        logger.info(f"SQL Query: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await self.session.execute(stmt)
        rows = result.fetchall()

        agent_run_versions = {row.agent_run_id: row.current_version for row in rows}

        logger.info(
            f"Atomically marked {len(agent_run_versions)} agent runs as processing in collection {collection_id}"
        )
        return agent_run_versions

    async def has_remaining_work(self, collection_id: str) -> bool:
        """
        Check if there are agent runs that still need processing for a collection.
        An agent run needs processing if it has status NEEDS_PROCESSING OR if its current_version > processed_version.

        Args:
            collection_id: The collection ID to check

        Returns:
            True if there are agent runs that need processing, False otherwise
        """
        stmt = (
            select(SQLATelemetryAgentRunStatus.agent_run_id)
            .where(
                SQLATelemetryAgentRunStatus.collection_id == collection_id,
                or_(
                    SQLATelemetryAgentRunStatus.status
                    == TelemetryAgentRunStatus.NEEDS_PROCESSING.value,
                    SQLATelemetryAgentRunStatus.current_version
                    > SQLATelemetryAgentRunStatus.processed_version,
                ),
            )
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def ensure_telemetry_processing_for_collection(
        self, collection_id: str, user: User
    ) -> str | None:
        """
        Check if a collection has remaining telemetry work and queue a job if needed.
        This combines the logic of checking for remaining work and queueing a job.

        Args:
            collection_id: The collection ID to check and potentially process
            user: The user who initiated the check

        Returns:
            The job ID if a job was created and enqueued, None if no work was found or job already exists
        """

        # Check if there's remaining work
        has_work = await self.has_remaining_work(collection_id)

        if not has_work:
            logger.debug(f"No remaining telemetry work for collection {collection_id}")
            return None

        # No existing job and there's work to do, create and enqueue a job
        logger.info(
            f"Found remaining telemetry work for collection {collection_id}, queueing processing job"
        )
        return await self.mono_svc.add_and_enqueue_telemetry_processing_job(collection_id, user)

    async def _mark_agent_runs_as_completed(
        self, collection_id: str, agent_run_versions: dict[str, int]
    ) -> None:
        """
        Mark agent runs as completed after successful processing.
        Updates the processed_version to match the version that was processed.
        Only mark as completed if currently processing to prevent the case where new data arrives while agent runs are being processed.

        Args:
            collection_id: The collection ID
            agent_run_versions: Dictionary mapping agent_run_id to the version that was processed
        """
        if not agent_run_versions:
            return

        # Update each agent run individually to set the correct processed_version
        for agent_run_id, processed_version in agent_run_versions.items():
            update_stmt = (
                update(SQLATelemetryAgentRunStatus)
                .where(
                    SQLATelemetryAgentRunStatus.agent_run_id == agent_run_id,
                    SQLATelemetryAgentRunStatus.collection_id == collection_id,
                    SQLATelemetryAgentRunStatus.status == TelemetryAgentRunStatus.PROCESSING.value,
                )
                .values(
                    status=TelemetryAgentRunStatus.COMPLETED.value,
                    processed_version=processed_version,
                )
            )

            result = await self.session.execute(update_stmt)
            if result.rowcount > 0:
                logger.info(
                    f"Marked agent run {agent_run_id} as completed with processed_version {processed_version}"
                )
            else:
                logger.warning(
                    f"Agent run {agent_run_id} was not marked as completed (may have been marked for reprocessing by new data)"
                )

    async def _mark_agent_runs_as_errored(
        self, collection_id: str, agent_run_ids: set[str], error_message: str | None = None
    ) -> None:
        """
        Mark agent runs as needs_processing after failed processing.
        Also tracks error count and error messages.

        Args:
            collection_id: The collection ID
            agent_run_ids: Set of agent run IDs to mark as needs_processing
            error_message: Optional error message to store
        """
        if not agent_run_ids:
            return

        # Update status and track error information
        for agent_run_id in agent_run_ids:
            # Get current metadata to update error count
            query = select(SQLATelemetryAgentRunStatus.metadata_json).where(
                SQLATelemetryAgentRunStatus.agent_run_id == agent_run_id,
                SQLATelemetryAgentRunStatus.collection_id == collection_id,
            )
            result = await self.session.execute(query)
            current_metadata: dict[str, Any] = result.scalar_one_or_none() or {}

            # Update error count and message
            error_count = current_metadata.get("error_count", 0) + 1
            error_history = current_metadata.get("error_history", [])
            if error_message:
                error_history.append({"error": error_message})

            if len(error_history) > 5:
                error_history = error_history[-5:]

            status = TelemetryAgentRunStatus.NEEDS_PROCESSING.value
            if error_count > 3:
                status = TelemetryAgentRunStatus.ERROR.value

            update_stmt = (
                update(SQLATelemetryAgentRunStatus)
                .where(
                    SQLATelemetryAgentRunStatus.agent_run_id == agent_run_id,
                    SQLATelemetryAgentRunStatus.collection_id == collection_id,
                )
                .values(
                    status=status,
                    metadata_json={
                        "error_count": error_count,
                        "error_history": error_history,
                    },
                )
            )

            await self.session.execute(update_stmt)

        await self.session.commit()

        logger.info(
            f"Marked {len(agent_run_ids)} agent runs as needs_processing after error in collection {collection_id}"
        )

    async def update_agent_runs_for_telemetry(
        self, ctx: ViewContext, agent_runs: Sequence[AgentRun]
    ):
        """
        Update agent runs - create if they don't exist, update if they do exist.
        For transcripts, delete existing ones and recreate them.
        For transcript groups, upsert them with proper parent-child ordering.
        """
        # Convert AgentRun objects to SQLAlchemy objects using existing conversion functions
        agent_run_data: list[SQLAAgentRun] = []
        transcript_data: list[SQLATranscript] = []
        transcript_group_data: list[SQLATranscriptGroup] = []
        agent_run_ids = [ar.id for ar in agent_runs]

        # Check collection size limit
        query = select(func.count()).where(SQLAAgentRun.collection_id == ctx.collection_id)
        result = await self.session.execute(query)
        existing_count = result.scalar_one()

        # Count how many new agent runs we'll be adding (not updating)
        existing_agent_run_query = select(SQLAAgentRun.id).where(
            SQLAAgentRun.collection_id == ctx.collection_id, SQLAAgentRun.id.in_(agent_run_ids)
        )
        existing_agent_run_result = await self.session.execute(existing_agent_run_query)
        existing_agent_run_ids = set(existing_agent_run_result.scalars().all())
        new_agent_run_count = len(agent_run_ids) - len(existing_agent_run_ids)

        if existing_count + new_agent_run_count > 100_000:
            raise ValueError("Number of agent runs in the current collection is too large")

        # Process all agent runs, transcripts, and transcript groups first
        for agent_run in agent_runs:
            # Use the existing from_agent_run method to get all fields properly
            sqla_agent_run = SQLAAgentRun.from_agent_run(agent_run, ctx.collection_id)
            agent_run_data.append(sqla_agent_run)

            # Process transcripts for this agent run
            for t in agent_run.transcripts:
                # Use the existing from_transcript method to get all fields properly
                sqla_transcript = SQLATranscript.from_transcript(
                    t, t.id, ctx.collection_id, agent_run.id
                )
                transcript_data.append(sqla_transcript)

            # Process transcript groups for this agent run
            if hasattr(agent_run, "transcript_groups") and agent_run.transcript_groups:
                for tg in agent_run.transcript_groups:
                    sqla_transcript_group = SQLATranscriptGroup.from_transcript_group(
                        tg, ctx.collection_id
                    )
                    transcript_group_data.append(sqla_transcript_group)

        # Handle agent runs - upsert (insert or update)
        for sqla_agent_run in agent_run_data:
            # Use merge to handle both insert and update
            await self.session.merge(sqla_agent_run)

        # Validate transcript group parent references before saving transcript groups
        if transcript_group_data:
            await self._validate_transcript_group_parent_references(transcript_group_data)

        # Handle transcript groups
        if transcript_group_data:
            # Sort transcript groups to ensure parent groups come before children
            sorted_transcript_group_data = sort_transcript_groups_by_parent_order(
                transcript_group_data
            )
            for sqla_transcript_group in sorted_transcript_group_data:
                # Use merge to handle both insert and update
                await self.session.merge(sqla_transcript_group)
                logger.debug(
                    f"Saved transcript group: {sqla_transcript_group.id} with parent {sqla_transcript_group.parent_transcript_group_id}"
                )
        await self.session.commit()

        # Validate transcript_group_id references before inserting transcripts
        await self._validate_transcript_group_references(transcript_data, transcript_group_data)

        # Handle transcripts - delete existing and recreate
        # Delete existing transcripts for these agent runs
        delete_transcript_query = delete(SQLATranscript).where(
            SQLATranscript.agent_run_id.in_(agent_run_ids)
        )
        await self.session.execute(delete_transcript_query)

        # Insert new transcripts
        self.session.add_all(transcript_data)

        logger.info(
            f"Added {len(agent_runs)} agent runs, {len(transcript_data)} transcripts, and {len(transcript_group_data)} transcript groups"
        )

    async def _validate_transcript_group_parent_references(
        self, transcript_group_data: List[SQLATranscriptGroup]
    ) -> None:
        """
        Validate that all parent_transcript_group_id references in transcript groups exist in the current batch.
        If a parent reference doesn't exist in the current batch, set it to None to avoid foreign key violations.
        This ensures that parent groups are saved before their children.

        Args:
            transcript_group_data: List of SQLATranscriptGroup objects to validate
        """
        # Create a set of all transcript group IDs in the current batch
        current_group_ids = {group.id for group in transcript_group_data}

        # Check for parent references that don't exist in the current batch
        invalid_parent_references: List[tuple[str, str]] = []
        for group in transcript_group_data:
            if (
                group.parent_transcript_group_id
                and group.parent_transcript_group_id not in current_group_ids
            ):
                invalid_parent_references.append((group.id, group.parent_transcript_group_id))

        if invalid_parent_references:
            logger.warning(
                f"Found {len(invalid_parent_references)} transcript groups with parent references not in current batch"
            )
            # Set parent_transcript_group_id to None for groups referencing missing parents
            for group_id, parent_id in invalid_parent_references:
                for group in transcript_group_data:
                    if group.id == group_id:
                        logger.warning(
                            f"Removing reference to parent transcript group {parent_id} (not in current batch) from transcript group {group_id}"
                        )
                        group.parent_transcript_group_id = None
                        break

    async def _validate_transcript_group_references(
        self,
        transcript_data: list[SQLATranscript],
        transcript_group_data: list[SQLATranscriptGroup],
    ) -> None:
        """
        Validate that all transcript_group_id references in transcripts exist in either the database
        or the transcript groups being added in the current batch.
        If a reference doesn't exist in either place, set it to None to avoid foreign key violations.

        Args:
            transcript_data: List of SQLATranscript objects to validate
            transcript_group_data: List of SQLATranscriptGroup objects being added in the current batch
        """
        # Collect all unique transcript_group_ids that are not None
        referenced_group_ids: set[str] = set()
        for transcript in transcript_data:
            if transcript.transcript_group_id:
                referenced_group_ids.add(transcript.transcript_group_id)

        if not referenced_group_ids:
            return

        # Create a set of transcript group IDs from the current batch
        current_batch_group_ids = {group.id for group in transcript_group_data}

        # Check which transcript groups exist in the database (excluding those in current batch)
        db_referenced_ids = referenced_group_ids - current_batch_group_ids
        existing_group_ids: set[str] = set()

        if db_referenced_ids:
            query = select(SQLATranscriptGroup.id).where(
                SQLATranscriptGroup.id.in_(list(db_referenced_ids))
            )
            result = await self.session.execute(query)
            existing_group_ids = set(result.scalars().all())

        # Combine existing database groups with current batch groups
        all_valid_group_ids = existing_group_ids | current_batch_group_ids

        # Find missing transcript groups
        missing_group_ids = referenced_group_ids - all_valid_group_ids

        if missing_group_ids:
            logger.warning(
                f"Found {len(missing_group_ids)} missing transcript groups: {missing_group_ids}"
            )
            # Set transcript_group_id to None for transcripts referencing missing groups
            for transcript in transcript_data:
                if transcript.transcript_group_id in missing_group_ids:
                    logger.warning(
                        f"Removing reference to missing transcript group {transcript.transcript_group_id} from transcript {transcript.id}"
                    )
                    transcript.transcript_group_id = None

    def _organize_spans_by_collection(
        self,
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
                logger.warning(
                    f"Skipping span - missing collection_id: {self._get_span_debug_info(span)}"
                )
                logger.debug(f"Span: {json.dumps(span, indent=2)}")
                continue

            organized_spans.setdefault(collection_id, {}).setdefault(agent_run_id, {}).setdefault(
                transcript_id, []
            ).append(span)

        return organized_spans

    def _create_transcript_groups_from_accumulation_data(
        self, transcript_group_metadata: Dict[str, Dict[str, Any]]
    ) -> List[TranscriptGroup]:
        """
        Create TranscriptGroup objects from accumulation metadata.

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
            agent_run_id = metadata.get("agent_run_id")
            collection_id = metadata.get("collection_id")
            parent_transcript_group_id = metadata.get("parent_transcript_group_id")
            metadata_dict = metadata.get("metadata", {})

            # Skip if required fields are missing
            if not agent_run_id:
                logger.warning(
                    f"Skipping transcript group {transcript_group_id} - missing agent_run_id"
                )
                continue

            if not collection_id:
                logger.warning(
                    f"Skipping transcript group {transcript_group_id} - missing collection_id"
                )
                continue

            # Create TranscriptGroup object
            transcript_group = TranscriptGroup(
                id=transcript_group_id,
                name=name,
                description=description,
                agent_run_id=agent_run_id,
                parent_transcript_group_id=parent_transcript_group_id,
                metadata=metadata_dict if metadata_dict else {},
            )

            transcript_groups.append(transcript_group)

        return transcript_groups

    async def _create_agent_runs_from_spans(
        self,
        agent_run_spans: Dict[str, Dict[str, List[Dict[str, Any]]]],
        transcript_groups_by_agent_run: Dict[str, List[TranscriptGroup]] | None = None,
        collection_scores: Dict[str, List[Dict[str, Any]]] | None = None,
        collection_metadata: Dict[str, List[Dict[str, Any]]] | None = None,
    ) -> List[AgentRun]:
        """
        Create AgentRun objects from organized spans, incorporating stored scores and metadata.

        Args:
            agent_run_spans: Organized spans by agent_run_id -> transcript_id -> spans[]
            transcript_groups_by_agent_run: Transcript groups organized by agent run ID
            collection_scores: Stored scores for the collection, organized by agent run ID
            collection_metadata: Stored metadata for the collection, organized by agent run ID

        Returns:
            List of AgentRun objects
        """
        collection_agent_runs: List[AgentRun] = []

        for agent_run_id, transcripts in agent_run_spans.items():
            logger.info(f"Processing agent_run_id: {agent_run_id}")

            logger.debug(
                f"_create_agent_runs_from_spans: agent_run_id={agent_run_id}, "
                f"num_transcripts={len(transcripts)}, "
                f"transcript_groups_by_agent_run={len(transcript_groups_by_agent_run[agent_run_id]) if transcript_groups_by_agent_run and agent_run_id in transcript_groups_by_agent_run else 'None'}, "
                f"collection_scores={len(collection_scores[agent_run_id]) if collection_scores and agent_run_id in collection_scores else 'None'}, "
                f"collection_metadata={len(collection_metadata[agent_run_id]) if collection_metadata and agent_run_id in collection_metadata else 'None'}"
            )

            agent_run_transcripts: list[Transcript] = []
            agent_run_scores: Dict[str, int | float | bool | None] = {}
            agent_run_model: str | None = None
            agent_run_metadata_dict: Dict[str, Any] = {}

            # Process each transcript
            for transcript_id, transcript_spans in transcripts.items():
                logger.info(
                    f"  Processing transcript_id: {transcript_id} with {len(transcript_spans)} spans"
                )

                # Debug: Log span details to understand what's in the spans
                for i, span in enumerate(transcript_spans):
                    span_attrs = span.get("attributes", {})
                    logger.debug(f"    Span {i}: attributes={list(span_attrs.keys())}")

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
                    span_metadata = self._extract_metadata_from_span_events(span)
                    if span_metadata:
                        # Unflatten the metadata to restore nested structure
                        unflattened_metadata = self._unflatten_metadata(span_metadata)
                        agent_run_metadata_dict.update(unflattened_metadata)
                        logger.info(f"    Found metadata: {unflattened_metadata}")

                    # Extract model from span attributes
                    span_attrs = span.get("attributes", {})
                    if not agent_run_model and "gen_ai.response.model" in span_attrs:
                        llm_request_type = (
                            span_attrs.get("llm", {}).get("request", {}).get("type", None)
                        )
                        if llm_request_type != "embedding":
                            agent_run_model = span_attrs["gen_ai.response.model"]
                            logger.info(f"    Found model: {agent_run_model}")

                # Create transcripts from spans
                transcripts_list = self._create_transcripts_from_spans(transcript_spans)
                logger.debug(
                    f"    Created {len(transcripts_list)} transcripts from {len(transcript_spans)} spans"
                )

                if not transcripts_list:
                    logger.warning(
                        f"    No transcripts created from {len(transcript_spans)} spans for transcript_id: {transcript_id}"
                    )
                    # Log more details about why no transcripts were created
                    for i, span in enumerate(transcript_spans):
                        span_attrs = span.get("attributes", {})
                        gen_ai_keys = [k for k in span_attrs.keys() if k.startswith("gen_ai")]
                        logger.debug(f"      Span {i} gen_ai keys: {gen_ai_keys}")
                        if not gen_ai_keys:
                            logger.debug(
                                f"      Span {i} has no gen_ai keys. All keys: {list(span_attrs.keys())}"
                            )

                # Add transcripts to agent run
                agent_run_transcripts.extend(transcripts_list)

            # Create agent run if it has transcripts
            if agent_run_transcripts:
                # Create metadata with scores, model, and any additional metadata using BaseAgentRunMetadata
                metadata_dict: Dict[str, Any] = {"scores": agent_run_scores}
                if agent_run_model:
                    metadata_dict["model"] = agent_run_model

                # Add any additional metadata from span events
                if agent_run_metadata_dict:
                    metadata_dict.update(agent_run_metadata_dict)
                    logger.info(f"  Added metadata to agent run: {agent_run_metadata_dict}")

                # Add stored scores (these take precedence over span-based scores)
                if collection_scores and collection_scores.get(agent_run_id):
                    for score_item in collection_scores[agent_run_id]:
                        stored_score_name = score_item.get("score_name")
                        stored_score_value = score_item.get("score_value")
                        if stored_score_name and stored_score_value is not None:
                            # Add the stored score to the scores dict
                            metadata_dict["scores"][stored_score_name] = stored_score_value
                            logger.info(
                                f"  Added stored score to agent run: {stored_score_name} = {stored_score_value}"
                            )

                # Add stored metadata (these take precedence over span-based metadata)
                if collection_metadata and collection_metadata.get(agent_run_id):
                    for metadata_item in collection_metadata[agent_run_id]:
                        stored_metadata = metadata_item.get("metadata", {})
                        if stored_metadata:
                            # Merge stored metadata with span-based metadata, stored metadata takes precedence
                            metadata_dict.update(stored_metadata)
                            logger.info(f"  Added stored metadata to agent run: {stored_metadata}")

                metadata = metadata_dict

                # Get transcript groups for this agent run
                agent_run_transcript_groups: list[TranscriptGroup] = []
                if (
                    transcript_groups_by_agent_run
                    and agent_run_id in transcript_groups_by_agent_run
                ):
                    for tg in transcript_groups_by_agent_run[agent_run_id]:
                        agent_run_transcript_groups.append(tg)

                agent_run = AgentRun(
                    id=agent_run_id,
                    name="",
                    description="",
                    transcripts=agent_run_transcripts,
                    transcript_groups=agent_run_transcript_groups,
                    metadata=metadata,
                )
                collection_agent_runs.append(agent_run)
                logger.info(
                    f"  Created agent run {agent_run_id} with {len(agent_run_transcripts)} transcripts, {len(agent_run_scores)} scores, and model: {agent_run_model or 'unknown'}"
                )
            else:
                logger.warning(f"  No transcripts created for agent_run_id: {agent_run_id}")

        return collection_agent_runs

    def _create_transcripts_from_spans(
        self, transcript_spans: List[Dict[str, Any]]
    ) -> List[Transcript]:
        """
        Create Transcript objects from spans.

        Args:
            transcript_spans: List of spans for a transcript

        Returns:
            List of Transcript objects
        """
        # Store all the chat threads and track which spans contributed to each
        chat_threads: List[List[ChatMessage]] = []
        thread_span_indices: List[List[int]] = []  # Track which spans contributed to each thread

        for span_idx, span in enumerate(transcript_spans):
            # Extract messages from this span
            span_messages = self._span_to_chat_messages(span)

            if not span_messages:
                continue

            # Find or create chat thread
            thread_index, action = self._find_or_create_chat_thread(span_messages, chat_threads)

            if action == "new":
                # Create new chat thread
                chat_threads.append(span_messages)
                thread_span_indices.append([span_idx])
                logger.debug(f"    Created new chat thread with {len(span_messages)} messages")
            elif action == "extend" and thread_index is not None:
                # Found matching thread - add new messages
                existing_thread = chat_threads[thread_index]
                new_messages = span_messages[len(existing_thread) :]

                # Update empty tool call results in existing thread with new results
                self._update_empty_tool_call_results(existing_thread, span_messages)

                chat_threads[thread_index].extend(new_messages)
                thread_span_indices[thread_index].append(span_idx)
                logger.debug(
                    f"    Extended chat thread {thread_index} with {len(new_messages)} new messages. First new message: {new_messages[0].text[:100].replace('\n', ' ') if new_messages else 'N/A'}"
                )
            elif action == "skip":
                # New messages are already contained in existing thread - skip
                logger.debug(
                    f"    Skipped span with {len(span_messages)} messages (already contained in thread {thread_index})"
                )

        # Create transcripts from chat threads
        transcripts: List[Transcript] = []
        logger.debug(
            f"    Created {len(chat_threads)} chat threads from {len(transcript_spans)} spans"
        )

        if chat_threads:
            for i, chat_thread in enumerate(chat_threads):
                # Create unique transcript ID for each thread
                thread_transcript_id = str(uuid.uuid4())

                # Determine transcript_group_id for this thread based on contributing spans
                thread_transcript_group_id = None
                if thread_span_indices[i]:
                    # Use the transcript_group_id from the last span that contributed to this thread
                    last_contributing_span_idx = thread_span_indices[i][-1]
                    last_contributing_span = transcript_spans[last_contributing_span_idx]
                    last_span_attrs = last_contributing_span.get("attributes", {})
                    thread_transcript_group_id = last_span_attrs.get("transcript_group_id")

                transcript = Transcript(
                    id=thread_transcript_id,
                    messages=chat_thread,
                    name=f"Chat Thread {i + 1}" if len(chat_threads) > 1 else "",
                    description="",
                    transcript_group_id=thread_transcript_group_id,
                )
                transcripts.append(transcript)
                logger.info(
                    f"    Created transcript {thread_transcript_id} with {len(chat_thread)} messages and transcript_group_id: {thread_transcript_group_id}"
                )
        else:
            logger.warning(f"    No messages extracted from {len(transcript_spans)} spans")
            # Log more details about why no chat threads were created
            total_messages = 0
            for span_idx, span in enumerate(transcript_spans):
                span_messages = self._span_to_chat_messages(span)
                total_messages += len(span_messages)
                logger.debug(f"      Span {span_idx}: extracted {len(span_messages)} messages")
            logger.debug(f"    Total messages extracted from all spans: {total_messages}")

        return transcripts

    def _find_or_create_chat_thread(
        self, span_messages: List[ChatMessage], existing_chat_threads: List[List[ChatMessage]]
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
                if self.matching_thread_start(existing_thread, span_messages):
                    logger.debug(
                        f"    Found matching thread {i} for span with {len(span_messages)} messages (extend existing)"
                    )
                    return i, "extend"

            # Case 2: Check if span_messages is a prefix of existing thread (skip new)
            elif len(existing_thread) >= len(span_messages):
                if self.matching_thread_start(span_messages, existing_thread):
                    logger.debug(
                        f"    Found matching thread {i} for span with {len(span_messages)} messages (skip new - already contained)"
                    )
                    return i, "skip"

        # No match found - create new chat thread
        return None, "new"

    def matching_thread_start(
        self, existing_thread: List[ChatMessage], new_thread: List[ChatMessage]
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
        existing_thread_tool_call_ids = self._collect_all_tool_call_ids_from_thread(existing_thread)
        new_thread_tool_call_ids = self._collect_all_tool_call_ids_from_thread(new_thread)

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
            logger.debug(
                f"Thread matching failed: messages don't match at positions "
                f"existing_idx={existing_idx}, new_idx={new_idx}. "
                f"Existing message: role='{existing_msg.role}', text='{existing_msg.text[:50]}...' "
                f"New message: role='{new_msg.role}', text='{new_msg.text[:50]}...'"
            )
            return False

        # Return True if we've processed all of existing_thread
        result = existing_idx >= len(existing_thread)
        if not result:
            logger.debug(
                f"Thread matching failed: didn't process all of existing thread. "
                f"Processed {existing_idx}/{len(existing_thread)} existing messages, "
                f"processed {new_idx}/{len(new_thread)} new messages"
            )
        return result

    def _extract_tool_call_ids_from_message(self, msg: ChatMessage) -> set[str]:
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

    def _collect_all_tool_call_ids_from_thread(self, thread: List[ChatMessage]) -> set[str]:
        """Collect all tool call IDs from a thread.

        Args:
            thread: List of chat messages to extract tool call IDs from

        Returns:
            Set of all tool call IDs found in the thread
        """
        tool_call_ids: set[str] = set()

        for msg in thread:
            msg_tool_ids = self._extract_tool_call_ids_from_message(msg)
            tool_call_ids.update(msg_tool_ids)

        return tool_call_ids

    def _update_empty_tool_call_results(
        self, existing_thread: List[ChatMessage], new_messages: List[ChatMessage]
    ) -> None:
        """Update empty tool call results in existing thread with new results.

        When extending a thread, check if the old thread had any empty tool call results
        (ToolMessage with empty content) and if the new thread has tool call results with
        the same tool_call_id and non-empty content, update the old thread's tool call results.

        Args:
            existing_thread: The existing chat thread that may have empty tool call results
            new_messages: The new messages that may contain updated tool call results
        """
        # Find empty tool call results in existing thread
        empty_tool_results: Dict[str, int] = {}  # tool_call_id -> message_index
        for i, msg in enumerate(existing_thread):
            if msg.role == "tool" and msg.tool_call_id and (not msg.text or msg.text.strip() == ""):
                empty_tool_results[msg.tool_call_id] = i
                logger.debug(f"Found empty tool result for tool_call_id: {msg.tool_call_id}")

        if not empty_tool_results:
            return

        # Find corresponding non-empty tool call results in new messages
        for msg in new_messages:
            if (
                msg.role == "tool"
                and msg.tool_call_id
                and msg.tool_call_id in empty_tool_results
                and msg.text
                and msg.text.strip() != ""
            ):

                # Update the existing empty tool result with the new content
                existing_msg_index = empty_tool_results[msg.tool_call_id]

                # Create updated message with new content
                updated_msg = ToolMessage(
                    content=msg.text,
                    tool_call_id=msg.tool_call_id,
                    function=msg.function,
                    error=msg.error,
                )

                # Replace the existing message
                existing_thread[existing_msg_index] = updated_msg
                logger.info(
                    f"Updated empty tool result for tool_call_id {msg.tool_call_id} "
                    f"with content: {msg.text[:100]}..."
                )

    def _span_to_chat_messages(self, span: Dict[str, Any]) -> List[ChatMessage]:
        """Convert a span to a list of chat message objects."""
        span_attrs = span.get("attributes", {})
        messages: List[ChatMessage] = []

        # Debug logging
        logger.debug(
            f"Processing span with {len(span_attrs)} attributes: {self._get_span_debug_info(span)}"
        )

        # Check for embedding request type
        llm_request_type = span_attrs.get("llm.request.type")
        if llm_request_type == "embedding":
            logger.info(f"Skipping embedding span: {self._get_span_debug_info(span)}")
            return []

        messages = self._extract_messages_from_span(span)

        # Debug logging
        if messages:
            logger.debug(
                f"Extracted {len(messages)} messages from span: {self._get_span_debug_info(span)}"
            )
            for i, msg in enumerate(messages):
                logger.debug(
                    f"  Message {i}: role={msg.role}, content_length={len(msg.text) if hasattr(msg, 'text') else 'N/A'}"
                )
        else:
            logger.debug(f"No messages extracted from span: {self._get_span_debug_info(span)}")
            # Additional debugging to understand why no messages were extracted
            span_attrs = span.get("attributes", {})
            gen_ai_keys = [k for k in span_attrs.keys() if k.startswith("gen_ai")]
            if gen_ai_keys:
                logger.debug(f"  Span has gen_ai keys: {gen_ai_keys}")
            else:
                logger.debug(
                    f"  Span has no gen_ai keys. Available keys: {list(span_attrs.keys())}"
                )

        return messages

    def _get_span_debug_info(self, span: Dict[str, Any]) -> str:
        """
        Generate helpful debugging information from a span for logging purposes.

        Args:
            span: The span dictionary

        Returns:
            String with key identifiers for easy log searching
        """
        span_attrs = span.get("attributes", {})
        collection_id = span_attrs.get("collection_id", "unknown")
        agent_run_id = span_attrs.get("agent_run_id", "unknown")
        transcript_group_id = span_attrs.get("transcript_group_id", "unknown")
        transcript_id = span_attrs.get("transcript_id", "unknown")
        raw_span_id = span.get("raw_span_id", span.get("span_id", "unknown"))

        return f"collection_id={collection_id}, agent_run_id={agent_run_id}, transcript_group_id={transcript_group_id}, transcript_id={transcript_id}, span_id={raw_span_id}"

    def _reformat_gen_ai_attributes(self, span_attrs: Dict[str, Any]) -> Dict[str, Any]:
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

    def _extract_messages_from_span(self, span: Dict[str, Any]) -> List[ChatMessage]:
        """Extract ChatMessage objects from structured gen_ai data."""
        messages: List[ChatMessage] = []
        span_attrs = span.get("attributes", {})
        gen_ai_data = self._reformat_gen_ai_attributes(span_attrs)

        if "gen_ai" not in gen_ai_data:
            logger.debug(
                f"No gen_ai data found in span. Available keys: {list(gen_ai_data.keys())}"
            )
            return messages

        gen_ai = gen_ai_data["gen_ai"]

        # Process prompt messages
        if "prompt" in gen_ai:
            # Sort keys numerically to maintain proper order
            for key in sorted(
                gen_ai["prompt"].keys(), key=lambda k: (0, int(k)) if k.isdigit() else (1, k)
            ):
                # Skip keys that aren't digits
                if not key.isdigit():
                    logger.info(f"Skipping non-digit key: {key}")
                    continue

                prompt_data: dict[str, Any] = gen_ai["prompt"][key]

                message = self._create_message_from_data(prompt_data, span, f"prompt_{key}")
                if message:
                    messages.append(message)

        # Process completion messages
        fields_moved_from_previous_key = {}
        if "completion" in gen_ai:
            # Sort keys numerically to maintain proper order
            for key in sorted(
                gen_ai["completion"].keys(), key=lambda k: (0, int(k)) if k.isdigit() else (1, k)
            ):
                # Skip keys that aren't digits
                if not key.isdigit():
                    logger.info(f"Skipping non-digit key: {key}")
                    continue

                # openllmetry anthropic instrumentation handles thinking blocks by changing the role to "thinking" and then incrementing the key used for subsequent blocks
                # https://github.com/traceloop/openllmetry/blob/84f5ee346baa5f7bc323f03b58f19167c87c6062/packages/opentelemetry-instrumentation-anthropic/opentelemetry/instrumentation/anthropic/span_utils.py#L193-L214
                if (
                    "role" in gen_ai["completion"][key]
                    and gen_ai["completion"][key]["role"] == "thinking"
                ):
                    # Use this in the next iteration of the loop
                    fields_moved_from_previous_key = {
                        "reasoning": gen_ai["completion"][key]["content"],
                    }
                    continue

                completion_data: dict[str, Any] = (
                    gen_ai["completion"][key] | fields_moved_from_previous_key
                )

                message = self._create_message_from_data(
                    completion_data, span, f"completion_{key}", assume_role="assistant"
                )
                # Reset this, since if it was used it should not be used again
                fields_moved_from_previous_key = {}
                if message:
                    messages.append(message)

        return messages

    def _create_message_from_data(
        self,
        data: Dict[str, Any],
        span: Dict[str, Any],
        context: str,
        assume_role: Optional[str] = None,
    ) -> ChatMessage | None:
        """Create a ChatMessage from structured data."""
        raw_span_id = span.get("raw_span_id", span.get("span_id", "unknown"))
        try:
            # Determine role
            if "role" in data:
                role = str(data["role"])
                if role == "developer":
                    role = "system"
            elif assume_role:
                role = assume_role
            elif "user" in data:
                role = "user"
            elif "assistant" in data:
                role = "assistant"
            elif "system" in data:
                role = "system"
            elif "developer" in data:
                role = "system"
            else:
                logger.error(
                    f"No valid role found in {context} for span {raw_span_id}. Available keys: {list(data.keys())}"
                )
                return None

            # Build content from available fields
            content_parts: List[Content] = []

            # Add reasoning if present
            if "reasoning" in data:
                reasoning = data["reasoning"]
                if isinstance(reasoning, str):
                    reasoning = [reasoning]
                for reasoning_item in reasoning:
                    content_parts.append(ContentReasoning(reasoning=reasoning_item))

            # Find the content key to use
            content_key = None
            possible_content_keys = [
                "content",
                "user",
                "assistant",
                "system",
                "developer",
            ]
            for possible_content_key in possible_content_keys:
                if possible_content_key in data:
                    content_key = possible_content_key
                    break

            # Extract tool calls embedded in content, return the cleaned content
            tool_calls: List[ToolCall] = []
            if content_key in data:
                try:
                    extracted_content, content_tool_calls = self._extract_tool_calls_from_content(
                        data[content_key]
                    )
                    if content_tool_calls:
                        tool_calls.extend(content_tool_calls)
                    content_parts.append(ContentText(text=extracted_content))

                except Exception as e:
                    logger.warning(
                        f"Failed to extract tool calls from content in {context} for span: {e} {self._get_span_debug_info(span)}"
                    )
                    # Continue without tool calls from content

            content = content_parts
            if len(content_parts) == 1 and content_parts[0].type == "text":
                content = content_parts[0].text

            # Handle structured tool calls
            if "tool_calls" in data:
                try:
                    structured_tool_calls = self._extract_tool_calls_from_span_data(
                        data["tool_calls"]
                    )
                    if structured_tool_calls:
                        tool_calls.extend(structured_tool_calls)
                except Exception as e:
                    logger.warning(
                        f"Failed to extract structured tool calls in {context} for span {raw_span_id}. Available keys: {list(data.keys())}. Error: {e}"
                    )
                    # Continue without structured tool calls

            message_data: Dict[str, Any] = {
                "role": role,
                "content": content,
            }

            if tool_calls:
                message_data["tool_calls"] = tool_calls

            message = parse_chat_message(message_data)
            logger.debug(f"Successfully created {context} message: role={message.role}")
            return message

        except KeyError as e:
            logger.error(
                f"Missing required field {e} in {context} for span {raw_span_id}. Available keys: {list(data.keys())}"
            )
            return None
        except ValueError as e:
            logger.error(f"Invalid value in {context} for span {raw_span_id}: {e}")
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error creating {context} message for span {raw_span_id}. Available keys: {list(data.keys())}. Error: {e}",
                exc_info=True,
            )
            return None

    def _extract_tool_calls_from_content(self, content: str) -> tuple[str, list[ToolCall] | None]:
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
                            if text_content and text_content != "":
                                filtered_content_parts.append(text_content)
                        elif content_type == "tool_result":
                            content_str = json.dumps(item.get("content", ""))
                            logger.info(f"Processing tool_result content: {content_str[:200]}...")
                            text_content, _ = self._extract_tool_calls_from_content(content_str)
                            filtered_content_parts.append(text_content)
                        else:
                            if content_type:
                                logger.error(f"Unknown content JSON type: {content_type}")
                            else:
                                logger.debug("No content type found for item")

                    # Update content and tool_calls
                    if filtered_content_parts:
                        filtered_content = "\n".join(filtered_content_parts)
                        if filtered_content and filtered_content != "":
                            content = filtered_content

                    if extracted_tool_calls:
                        tool_calls = extracted_tool_calls
                        logger.info(f"Extracted {len(tool_calls)} tool calls from content")

                    if not filtered_content_parts and not extracted_tool_calls:
                        logger.debug(
                            "No content or tool calls found for item, treating as regular content"
                        )
            except json.JSONDecodeError as e:
                logger.debug(
                    f"Content is not valid JSON: {e}, treating as regular content. Start of content: {str(content)[:200]}"
                )

        return content, tool_calls

    def _extract_tool_calls_from_span_data(self, tool_calls_data: dict[str, Any]) -> list[ToolCall]:
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
                    logger.debug(
                        f"Successfully parsed arguments for tool {tool_index}: {arguments}"
                    )
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

    def _extract_metadata_from_span_events(self, span: Dict[str, Any]) -> Dict[str, Any]:
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

    def _unflatten_metadata(self, flattened_metadata: Dict[str, Any]) -> Dict[str, Any]:
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
