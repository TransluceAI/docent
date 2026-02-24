import base64
import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import (
    Any,
    DefaultDict,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    TypedDict,
    cast,
)
from uuid import uuid4

from asyncpg.exceptions import DeadlockDetectedError
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from redis.exceptions import LockError
from sqlalchemy import Integer, and_, case, delete, func, not_, or_, select, update
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Result
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from docent._log_util import get_logger
from docent.data_models import (
    AgentRun,
    Transcript,
    TranscriptGroup,
)
from docent.data_models.chat import (
    AssistantMessage,
    ChatMessage,
    Content,
    ContentReasoning,
    ContentText,
    ToolMessage,
    parse_chat_message,
)
from docent.data_models.chat.tool import ToolCall
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server._broker.redis_client import get_redis_client
from docent_core._worker.constants import WorkerFunction, get_job_timeout_seconds
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import (
    SQLAAgentRun,
    SQLACollection,
    SQLATelemetryAccumulation,
    SQLATelemetryAgentRunStatus,
    SQLATelemetryLineage,
    SQLATelemetryLog,
    SQLATranscript,
    SQLATranscriptGroup,
    SQLAUser,
    TelemetryAgentRunStatus,
)
from docent_core.docent.services.monoservice import (
    MonoService,
    sort_transcript_groups_by_parent_order,
)
from docent_core.docent.services.telemetry_accumulation import (
    TelemetryAccumulationService,
    deep_merge_dicts,
)

logger = get_logger(__name__)

LineageEntry = Dict[str, Any]


class MessageSourceInfo(TypedDict):
    """Source information for a single message, used to create lineage entries."""

    message_idx: int
    raw_span_id: str
    telemetry_log_id: str | None
    telemetry_accumulation_id: str | None
    first_seen_span_start_time: str | None
    collection_id: str
    agent_run_id: str


class TranscriptSourceInfo(TypedDict):
    """Source information for a transcript, used to create lineage entries."""

    raw_span_id: str
    telemetry_log_id: str | None
    telemetry_accumulation_id: str | None
    collection_id: str
    agent_run_id: str


class TranscriptLineageData(TypedDict):
    """
    Data needed to create lineage entries for a transcript.

    This is returned from _create_transcripts_from_spans and used to create
    lineage entries AFTER ID reconciliation, ensuring the correct IDs are used.
    """

    transcript: Transcript
    raw_transcript_id: str
    message_sources: list[MessageSourceInfo]
    transcript_sources: list[TranscriptSourceInfo]


AGENT_RUN_LOCK_PREFIX = "telemetry_agent_run_lock"
TELEMETRY_PROCESSING_TIMEOUT_SECONDS = get_job_timeout_seconds(
    WorkerFunction.TELEMETRY_PROCESSING_JOB
)
AGENT_RUN_LOCK_TIMEOUT_SECONDS = TELEMETRY_PROCESSING_TIMEOUT_SECONDS + 60


class TelemetryService:
    def __init__(self, session: AsyncSession, mono_svc: MonoService):
        self.session = session
        self.mono_svc = mono_svc

    async def get_message_otel_payload(
        self, *, collection_id: str, transcript_id: str, message_id: str
    ) -> dict[str, Any] | None:
        """
        Fetch the OpenTelemetry span payload associated with a transcript message.

        The linkage is maintained via SQLATelemetryLineage rows written during telemetry processing.
        """
        lineage_stmt = (
            select(SQLATelemetryLineage)
            .where(
                SQLATelemetryLineage.collection_id == collection_id,
                SQLATelemetryLineage.derived_type == "transcript_message",
                SQLATelemetryLineage.derived_id == transcript_id,
                SQLATelemetryLineage.derived_key == message_id,
            )
            .order_by(SQLATelemetryLineage.created_at.asc())
            .limit(1)
        )
        lineage_result = await self.session.execute(lineage_stmt)
        lineage = lineage_result.scalar_one_or_none()
        if lineage is None:
            return None

        telemetry_accumulation_id = lineage.telemetry_accumulation_id
        if not telemetry_accumulation_id:
            return None

        span_stmt = select(SQLATelemetryAccumulation).where(
            SQLATelemetryAccumulation.id == telemetry_accumulation_id
        )
        span_result = await self.session.execute(span_stmt)
        span_row = span_result.scalar_one_or_none()
        if span_row is None:
            return None

        return {
            "telemetry_accumulation_id": span_row.id,
            "telemetry_log_id": lineage.telemetry_log_id,
            "raw_span_id": lineage.source_id,
            "span": span_row.data,
            "first_seen_span_start_time": cast(dict[str, Any], lineage.attributes or {}).get(
                "first_seen_span_start_time"
            ),
        }

    @staticmethod
    def _stable_transcript_message_id(transcript_id: str, message_index: int) -> str:
        """
        Generate a stable identifier for a message inside a transcript.

        We store transcripts as a single blob (messages list). To reliably join UI message
        rows to telemetry lineage across re-processing, we need a deterministic per-message
        identifier that doesn't require a separate messages table.
        """
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"docent:transcript_message:{transcript_id}:{message_index}",
            )
        )

    def _ensure_transcript_message_ids(self, transcript: Transcript) -> None:
        """
        Ensure every transcript message has a stable ID.

        Message IDs are preserved if already present (e.g. emitted by an upstream SDK),
        otherwise a deterministic ID based on transcript + index is assigned.
        """
        for idx, message in enumerate(transcript.messages):
            if not getattr(message, "id", None):
                message.id = self._stable_transcript_message_id(transcript.id, idx)

    def _agent_run_lock_key(self, collection_id: str, agent_run_id: str) -> str:
        return f"{AGENT_RUN_LOCK_PREFIX}_{collection_id}_{agent_run_id}"

    @staticmethod
    def _is_deadlock_error(exc: Exception) -> bool:
        if isinstance(exc, DeadlockDetectedError):
            return True

        if isinstance(exc, DBAPIError):
            if isinstance(exc.orig, DeadlockDetectedError):
                return True
            return isinstance(getattr(exc.orig, "__cause__", None), DeadlockDetectedError)

        return isinstance(getattr(exc, "__cause__", None), DeadlockDetectedError)

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
        telemetry_id = str(uuid4())
        self.session.add(
            SQLATelemetryLog(
                id=telemetry_id,
                user_id=user_id,
                collection_id=collection_id,
                type=type,
                version=version,
                json_data=json_data,
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

    async def process_agent_runs_for_collection(
        self,
        collection_id: str,
        user: User,
        *,
        limit: int | None = None,
        time_budget_seconds: int | None = None,
    ) -> List[str]:
        """
        Process all agent runs that need processing for a collection.

        This method handles the complete processing workflow for a collection,
        processing each agent run individually by pulling its accumulated data
        and creating the necessary database objects.

        Args:
            collection_id: The collection ID to process
            user: The user who initiated the processing
            limit: Optional maximum number of agent runs to process in this invocation
            time_budget_seconds: Optional max wall-clock seconds to spend before returning early

        Returns:
            List[str]: List of agent run IDs that were successfully processed
        """
        if limit is not None and limit <= 0:
            raise ValueError("limit must be a positive integer when provided")

        if time_budget_seconds is not None and time_budget_seconds <= 0:
            raise ValueError("time_budget_seconds must be positive when provided")

        start_time = time.monotonic()

        # Atomically get agent runs that need processing and mark them as processing
        mark_start = time.monotonic()
        agent_run_versions = await self.get_agent_runs_to_process(collection_id, limit=limit)
        mark_duration = time.monotonic() - mark_start

        if not agent_run_versions:
            logger.info(
                "telemetry_processing phase=mark_runs collection_id=%s duration=%.3fs status=no_work limit=%s",
                collection_id,
                mark_duration,
                limit if limit is not None else "none",
            )
            return []

        logger.info(
            "telemetry_processing phase=mark_runs collection_id=%s duration=%.3fs status=marked count=%s limit=%s",
            collection_id,
            mark_duration,
            len(agent_run_versions),
            limit if limit is not None else "none",
        )

        redis_client = await get_redis_client()

        # Process each agent run individually
        processed_count = 0
        successfully_processed_agent_run_ids: List[str] = []
        successfully_processed_versions: dict[str, int] = {}
        lock_contention_count = 0

        for agent_run_id, current_version in agent_run_versions.items():
            if time_budget_seconds is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= time_budget_seconds:
                    logger.info(
                        "Stopping telemetry processing for collection %s after %.2fs to stay under budget; processed %s of %s agent runs",
                        collection_id,
                        elapsed,
                        processed_count,
                        len(agent_run_versions),
                    )
                    break

            per_run_start = time.monotonic()
            lock = redis_client.lock(
                self._agent_run_lock_key(collection_id, agent_run_id),
                timeout=AGENT_RUN_LOCK_TIMEOUT_SECONDS,
                blocking=False,
            )
            try:
                async with lock:
                    try:
                        # Ensure clean session state before processing this agent run
                        await self.session.rollback()
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
                            run_elapsed = time.monotonic() - per_run_start
                            logger.info(
                                "telemetry_processing phase=process_agent_run collection_id=%s agent_run_id=%s version=%s duration=%.3fs status=success",
                                collection_id,
                                agent_run_id,
                                current_version,
                                run_elapsed,
                            )
                        else:
                            run_elapsed = time.monotonic() - per_run_start
                            logger.error(
                                "telemetry_processing phase=process_agent_run collection_id=%s agent_run_id=%s version=%s duration=%.3fs status=failed reason=unknown",
                                collection_id,
                                agent_run_id,
                                current_version,
                                run_elapsed,
                            )
                            # Mark agent run as errored on failure
                            await self._mark_agent_runs_as_errored(
                                collection_id,
                                {agent_run_id: current_version},
                                "Processing failed",
                            )

                    except Exception as e:
                        # Mark agent run as needs_processing again if processing failed
                        await self._mark_agent_runs_as_errored(
                            collection_id,
                            {agent_run_id: current_version},
                            str(e),
                        )
                        run_elapsed = time.monotonic() - per_run_start
                        logger.error(
                            "telemetry_processing phase=process_agent_run collection_id=%s agent_run_id=%s version=%s duration=%.3fs status=failed reason=exception error=%s",
                            collection_id,
                            agent_run_id,
                            current_version,
                            run_elapsed,
                            str(e),
                        )
                        continue
            except LockError:
                lock_contention_count += 1
                run_elapsed = time.monotonic() - per_run_start
                logger.warning(
                    "telemetry_processing phase=process_agent_run collection_id=%s agent_run_id=%s duration=%.3fs status=skipped reason=lock_contention",
                    collection_id,
                    agent_run_id,
                    run_elapsed,
                )
                continue

        # Mark all successfully processed agent runs as completed with their versions
        if successfully_processed_versions:
            completion_start = time.monotonic()
            await self._mark_agent_runs_as_completed(collection_id, successfully_processed_versions)
            completion_duration = time.monotonic() - completion_start
            logger.info(
                "telemetry_processing phase=mark_completed collection_id=%s duration=%.3fs count=%s",
                collection_id,
                completion_duration,
                len(successfully_processed_versions),
            )

        total_elapsed = time.monotonic() - start_time
        logger.info(
            "telemetry_processing phase=summary collection_id=%s duration=%.3fs processed=%s attempted=%s lock_contention=%s",
            collection_id,
            total_elapsed,
            processed_count,
            len(agent_run_versions),
            lock_contention_count,
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

            accumulation_fetch_start = time.monotonic()
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
            accumulation_fetch_duration = time.monotonic() - accumulation_fetch_start
            logger.info(
                "telemetry_processing phase=load_accumulation collection_id=%s agent_run_id=%s duration=%.3fs spans=%s scores=%s metadata_entries=%s transcript_group_entries=%s",
                collection_id,
                agent_run_id,
                accumulation_fetch_duration,
                len(agent_run_spans),
                len(agent_run_scores),
                len(agent_run_metadata),
                len(agent_run_transcript_group_metadata or {}),
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
            existing_transcripts_by_agent_run = await self._load_existing_transcripts(
                collection_id, [agent_run_id]
            )

            # Create agent run from spans
            transform_start = time.monotonic()
            collection_agent_runs, lineage_entries = await self._create_agent_runs_from_spans(
                agent_run_spans_dict,
                transcript_groups_by_agent_run,
                collection_scores,
                collection_metadata,
                existing_transcripts_by_agent_run,
            )
            transform_duration = time.monotonic() - transform_start
            logger.info(
                "telemetry_processing phase=transform_spans collection_id=%s agent_run_id=%s duration=%.3fs agent_runs=%s",
                collection_id,
                agent_run_id,
                transform_duration,
                len(collection_agent_runs),
            )

            if not collection_agent_runs:
                logger.warning(f"No agent run created from spans for {agent_run_id}")
                return False

            # TODO(gregor): Use the original user who created the telemetry data instead of the processing user
            # Get or create default view context for this collection
            ctx = await self.mono_svc.get_default_view_ctx(collection_id, user)
            # Store the agent run in the database
            persist_start = time.monotonic()
            await self.update_agent_runs_for_telemetry(
                ctx, collection_agent_runs, lineage_entries=lineage_entries
            )
            persist_duration = time.monotonic() - persist_start
            logger.info(
                "telemetry_processing phase=persist_agent_run collection_id=%s agent_run_id=%s duration=%.3fs",
                collection_id,
                agent_run_id,
                persist_duration,
            )

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
                        detail=f"User {user.id} does not have write permission on collection {collection_id}",
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

            return trace_data
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

        return processed_span

    async def accumulate_spans(
        self,
        spans: List[Dict[str, Any]],
        user_id: str | None = None,
        accumulation_service: TelemetryAccumulationService | None = None,
        *,
        telemetry_log_id: str | None = None,
        replace_existing_for_log: bool = False,
    ) -> None:
        """
        Accumulate spans by collection_id for later processing and mark agent runs as needing processing.

        Args:
            spans: List of processed spans to accumulate
            user_id: Optional user ID for tracking who created the spans
            accumulation_service: Optional service instance to use
            telemetry_log_id: Optional telemetry log identifier for idempotent accumulation
            replace_existing_for_log: Delete previous spans written for this telemetry log before adding
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
                await accumulation_service.add_spans(
                    collection_id,
                    collection_spans,
                    user_id,
                    telemetry_log_id=telemetry_log_id,
                    replace_existing_for_log=replace_existing_for_log,
                )
            else:
                logger.error("Accumulation service not found, skipping accumulation")

    async def get_agent_runs_to_process(
        self,
        collection_id: str,
        *,
        limit: int | None = None,
    ) -> dict[str, int]:
        """
        Atomically get agent runs that need processing and mark them as processing.
        Returns both the agent run IDs and their current versions.

        Args:
            collection_id: The collection ID
            limit: Optional maximum number of agent runs to mark in this pass

        Returns:
            Dictionary mapping agent_run_id to current_version for successfully marked agent runs
        """
        if limit is not None and limit <= 0:
            raise ValueError("limit must be a positive integer when provided")

        # Track the latest version that failed so new data can retry even if status is ERROR
        errored_version = func.coalesce(
            sa_cast(
                SQLATelemetryAgentRunStatus.metadata_json["errored_version"].astext,
                Integer,
            ),
            0,
        )
        needs_processing_condition = (
            SQLATelemetryAgentRunStatus.status == TelemetryAgentRunStatus.NEEDS_PROCESSING.value
        )
        version_greater_than_processed = (
            SQLATelemetryAgentRunStatus.current_version
            > SQLATelemetryAgentRunStatus.processed_version
        )
        needs_processing_condition = and_(
            SQLATelemetryAgentRunStatus.status == TelemetryAgentRunStatus.NEEDS_PROCESSING.value,
            version_greater_than_processed,
        )
        completed_with_new_data_condition = and_(
            SQLATelemetryAgentRunStatus.status == TelemetryAgentRunStatus.COMPLETED.value,
            version_greater_than_processed,
        )
        errored_with_new_data_condition = and_(
            SQLATelemetryAgentRunStatus.status == TelemetryAgentRunStatus.ERROR.value,
            version_greater_than_processed,
            SQLATelemetryAgentRunStatus.current_version > errored_version,
        )
        fallback_condition = and_(
            version_greater_than_processed,
            not_(
                and_(
                    SQLATelemetryAgentRunStatus.status == TelemetryAgentRunStatus.ERROR.value,
                    SQLATelemetryAgentRunStatus.current_version <= errored_version,
                ),
            ),
        )
        processing_filter = or_(
            needs_processing_condition,
            completed_with_new_data_condition,
            errored_with_new_data_condition,
            fallback_condition,
        )

        stmt = select(
            SQLATelemetryAgentRunStatus.id,
            SQLATelemetryAgentRunStatus.agent_run_id,
            SQLATelemetryAgentRunStatus.current_version,
        ).where(
            SQLATelemetryAgentRunStatus.collection_id == collection_id,
            processing_filter,
        )

        if limit is not None:
            # Prioritize cleanly queued runs before fallback dirty rows when enforcing a limit.
            priority_case = case(
                (needs_processing_condition, 1),
                (completed_with_new_data_condition, 2),
                (errored_with_new_data_condition, 3),
                (fallback_condition, 4),
                else_=5,
            )
            stmt = stmt.order_by(
                priority_case.asc(),
                SQLATelemetryAgentRunStatus.created_at.asc(),
                SQLATelemetryAgentRunStatus.id.asc(),
            ).limit(limit)

        # Reserve rows without waiting on locks; other workers skip locked rows instead of deadlocking.
        candidate_cte = stmt.with_for_update(skip_locked=True).cte("candidate_runs")

        update_stmt = (
            update(SQLATelemetryAgentRunStatus)
            .where(SQLATelemetryAgentRunStatus.id.in_(select(candidate_cte.c.id)))
            .values(status=TelemetryAgentRunStatus.PROCESSING.value)
            .returning(
                SQLATelemetryAgentRunStatus.agent_run_id,
                SQLATelemetryAgentRunStatus.current_version,
            )
        )

        result = await self.session.execute(update_stmt)
        rows = result.fetchall()
        logger.info(
            "Telemetry mark query returned %s agent runs for collection %s",
            len(rows),
            collection_id,
        )
        agent_run_versions = {row.agent_run_id: row.current_version for row in rows}

        return agent_run_versions

    async def mark_single_agent_run_for_processing(
        self, collection_id: str, agent_run_id: str
    ) -> int | None:
        """
        Atomically mark a single agent run as processing when newer data exists.
        Returns the current_version selected for processing, or None if no work.
        """
        errored_version = func.coalesce(
            sa_cast(
                SQLATelemetryAgentRunStatus.metadata_json["errored_version"].astext,
                Integer,
            ),
            0,
        )
        version_greater_than_processed = (
            SQLATelemetryAgentRunStatus.current_version
            > SQLATelemetryAgentRunStatus.processed_version
        )
        processing_filter = and_(
            version_greater_than_processed,
            or_(
                SQLATelemetryAgentRunStatus.status != TelemetryAgentRunStatus.ERROR.value,
                SQLATelemetryAgentRunStatus.current_version > errored_version,
            ),
        )

        update_stmt = (
            update(SQLATelemetryAgentRunStatus)
            .where(
                SQLATelemetryAgentRunStatus.collection_id == collection_id,
                SQLATelemetryAgentRunStatus.agent_run_id == agent_run_id,
                processing_filter,
            )
            .values(status=TelemetryAgentRunStatus.PROCESSING.value)
            .returning(SQLATelemetryAgentRunStatus.current_version)
        )

        result = await self.session.execute(update_stmt)
        row = result.first()
        if row is None:
            logger.info(
                "telemetry_processing mark_single_agent_run status=no_work collection_id=%s agent_run_id=%s",
                collection_id,
                agent_run_id,
            )
            return None

        selected_version = int(row.current_version)
        logger.info(
            "telemetry_processing mark_single_agent_run status=marked collection_id=%s agent_run_id=%s version=%s",
            collection_id,
            agent_run_id,
            selected_version,
        )
        return selected_version

    async def process_single_agent_run_job(
        self, collection_id: str, agent_run_id: str, user: User
    ) -> bool:
        """
        Process a single agent run end-to-end with locking, status updates, and requeue checks.
        """
        selected_version = await self.mark_single_agent_run_for_processing(
            collection_id, agent_run_id
        )
        if selected_version is None:
            return False

        redis_client = await get_redis_client()
        lock = redis_client.lock(
            self._agent_run_lock_key(collection_id, agent_run_id),
            timeout=AGENT_RUN_LOCK_TIMEOUT_SECONDS,
            blocking=False,
        )

        try:
            async with lock:
                await self.session.rollback()
                processing_start = time.monotonic()
                success = await self._process_single_agent_run(
                    agent_run_id,
                    collection_id,
                    user,
                )
                processing_duration = time.monotonic() - processing_start

                if success:
                    await self._mark_agent_runs_as_completed(
                        collection_id, {agent_run_id: selected_version}
                    )
                    logger.info(
                        "telemetry_processing agent_run status=success collection_id=%s agent_run_id=%s version=%s duration=%.3fs",
                        collection_id,
                        agent_run_id,
                        selected_version,
                        processing_duration,
                    )
                else:
                    await self._mark_agent_runs_as_errored(
                        collection_id, {agent_run_id: selected_version}, "Processing failed"
                    )
                    logger.error(
                        "telemetry_processing agent_run status=failed collection_id=%s agent_run_id=%s version=%s duration=%.3fs",
                        collection_id,
                        agent_run_id,
                        selected_version,
                        processing_duration,
                    )
        except LockError:
            logger.warning(
                "telemetry_processing agent_run status=skipped reason=lock_contention collection_id=%s agent_run_id=%s",
                collection_id,
                agent_run_id,
            )
            return False
        finally:
            try:
                await self.ensure_telemetry_processing_for_agent_run(
                    collection_id, agent_run_id, user
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "telemetry_processing agent_run status=enqueue_failed collection_id=%s agent_run_id=%s error=%s",
                    collection_id,
                    agent_run_id,
                    exc,
                )

        return True

    async def has_remaining_work(self, collection_id: str) -> bool:
        """
        Check if there are agent runs that still need processing for a collection.
        Work remains if an agent run is marked NEEDS_PROCESSING or has newer data
        (current_version > processed_version) that is either not errored or newer
        than the last errored version.

        Args:
            collection_id: The collection ID to check

        Returns:
            True if there are agent runs that need processing, False otherwise
        """
        errored_version = func.coalesce(
            sa_cast(
                SQLATelemetryAgentRunStatus.metadata_json["errored_version"].astext,
                Integer,
            ),
            0,
        )

        version_greater_than_processed = (
            SQLATelemetryAgentRunStatus.current_version
            > SQLATelemetryAgentRunStatus.processed_version
        )

        stmt = (
            select(SQLATelemetryAgentRunStatus.agent_run_id)
            .where(
                SQLATelemetryAgentRunStatus.collection_id == collection_id,
                or_(
                    and_(
                        SQLATelemetryAgentRunStatus.status
                        == TelemetryAgentRunStatus.NEEDS_PROCESSING.value,
                        version_greater_than_processed,
                    ),
                    and_(
                        version_greater_than_processed,
                        or_(
                            SQLATelemetryAgentRunStatus.status
                            != TelemetryAgentRunStatus.ERROR.value,
                            SQLATelemetryAgentRunStatus.current_version > errored_version,
                        ),
                    ),
                ),
            )
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def has_agent_run_remaining_work(self, collection_id: str, agent_run_id: str) -> bool:
        """
        Check if a specific agent run still needs processing.
        """
        errored_version = func.coalesce(
            sa_cast(
                SQLATelemetryAgentRunStatus.metadata_json["errored_version"].astext,
                Integer,
            ),
            0,
        )
        version_greater_than_processed = (
            SQLATelemetryAgentRunStatus.current_version
            > SQLATelemetryAgentRunStatus.processed_version
        )

        stmt = (
            select(SQLATelemetryAgentRunStatus.agent_run_id)
            .where(
                SQLATelemetryAgentRunStatus.collection_id == collection_id,
                SQLATelemetryAgentRunStatus.agent_run_id == agent_run_id,
                or_(
                    and_(
                        SQLATelemetryAgentRunStatus.status
                        == TelemetryAgentRunStatus.NEEDS_PROCESSING.value,
                        version_greater_than_processed,
                    ),
                    and_(
                        version_greater_than_processed,
                        or_(
                            SQLATelemetryAgentRunStatus.status
                            != TelemetryAgentRunStatus.ERROR.value,
                            SQLATelemetryAgentRunStatus.current_version > errored_version,
                        ),
                    ),
                ),
            )
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def ensure_telemetry_processing_for_collection(
        self, collection_id: str, user: User, *, force: bool = False
    ) -> str | None:
        """
        Check if a collection has remaining telemetry work and queue a job if needed.
        This combines the logic of checking for remaining work and queueing a job.

        Args:
            collection_id: The collection ID to check and potentially process
            user: The user who initiated the check
            force: When True, skip the guard that blocks scheduling while a job is still running.

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
        return await self.mono_svc.add_and_enqueue_telemetry_processing_job(
            collection_id, user, force=force
        )

    async def ensure_telemetry_processing_for_agent_run(
        self,
        collection_id: str,
        agent_run_id: str,
        user: User,
        *,
        force: bool = False,
    ) -> str | None:
        """
        Queue telemetry processing for a specific agent run if work remains.
        """
        has_work = await self.has_agent_run_remaining_work(collection_id, agent_run_id)
        if not has_work:
            logger.debug(
                "No remaining telemetry work for collection %s agent_run_id=%s",
                collection_id,
                agent_run_id,
            )
            return None

        logger.info(
            "Found telemetry work for collection %s agent_run_id=%s, queueing processing job",
            collection_id,
            agent_run_id,
        )
        return await self.mono_svc.add_and_enqueue_telemetry_processing_job(
            collection_id, user, agent_run_id=agent_run_id, force=force
        )

    async def _get_collection_owner_user(self, collection_id: str) -> User | None:
        stmt = (
            select(SQLAUser)
            .join(SQLACollection, SQLACollection.created_by == SQLAUser.id)
            .where(SQLACollection.id == collection_id)
            .options(selectinload(SQLAUser.organizations))
        )
        result = await self.session.execute(stmt)
        owner = result.scalar_one_or_none()

        if owner is None:
            logger.warning(
                "Unable to resolve owner for collection %s when ensuring telemetry processing",
                collection_id,
            )
            return None

        return owner.to_user()

    async def ensure_telemetry_processing_for_collection_as_owner(
        self, collection_id: str, *, force: bool = False
    ) -> str | None:
        """
        Queue telemetry processing using the collection owner as the acting user.
        Admin tools call this to reuse the owner's view context when they trigger work.
        """
        owner_user = await self._get_collection_owner_user(collection_id)
        if owner_user is None:
            return None

        return await self.ensure_telemetry_processing_for_collection(
            collection_id, owner_user, force=force
        )

    async def _mark_agent_runs_as_completed(
        self, collection_id: str, agent_run_versions: dict[str, int]
    ) -> None:
        """
        Mark agent runs as completed after successful processing.
        Always advance processed_version to at least the version that was processed, even if status was updated concurrently.

        Args:
            collection_id: The collection ID
            agent_run_versions: Dictionary mapping agent_run_id to the version that was processed
        """
        if not agent_run_versions:
            return

        # Ensure prior processing work is committed so deadlock retries don't roll back earlier DB writes.
        await self.session.commit()

        # Sort updates to take row locks in a stable order and reduce lock inversion risk.
        sorted_agent_runs = sorted(agent_run_versions.items())
        completed_rows: list[tuple[str, int, int]] = []

        for agent_run_id, processed_version in sorted_agent_runs:
            update_stmt = (
                update(SQLATelemetryAgentRunStatus)
                .where(
                    SQLATelemetryAgentRunStatus.agent_run_id == agent_run_id,
                    SQLATelemetryAgentRunStatus.collection_id == collection_id,
                )
                .values(
                    status=TelemetryAgentRunStatus.COMPLETED.value,
                    processed_version=func.greatest(
                        SQLATelemetryAgentRunStatus.processed_version, processed_version
                    ),
                )
            )

            result = await self.session.execute(update_stmt)
            rowcount: int = getattr(result, "rowcount", None) or 0
            completed_rows.append((agent_run_id, processed_version, rowcount))

        await self.session.commit()

        for agent_run_id, processed_version, rowcount in completed_rows:
            if rowcount > 0:
                logger.info(
                    f"Marked agent run {agent_run_id} as completed with processed_version {processed_version}"
                )
            else:
                logger.warning(
                    f"Agent run {agent_run_id} was not marked as completed (may have been marked for reprocessing by new data)"
                )

    async def _mark_agent_runs_as_errored(
        self,
        collection_id: str,
        agent_run_versions: Mapping[str, int],
        error_message: str | None = None,
    ) -> None:
        """
        Mark agent runs as errored after failed processing.
        Also tracks error count, messages, and the version that failed so we only retain error data for the newest version.

        Args:
            collection_id: The collection ID
            agent_run_versions: Mapping of agent run IDs to the version that produced the error
            error_message: Optional error message to store
        """
        if not agent_run_versions:
            return

        # Update status and track error information
        for agent_run_id, provided_version in agent_run_versions.items():
            # Get current metadata and version information for this agent run
            query = select(SQLATelemetryAgentRunStatus.metadata_json).where(
                SQLATelemetryAgentRunStatus.agent_run_id == agent_run_id,
                SQLATelemetryAgentRunStatus.collection_id == collection_id,
            )
            result = await self.session.execute(query)
            row = result.one_or_none()
            if row is None:
                logger.warning(
                    f"No telemetry status row found for agent run {agent_run_id} in collection {collection_id}"
                )
                continue
            stored_metadata: dict[str, Any] = row.metadata_json or {}

            previous_error_version = stored_metadata.get("errored_version", 0)

            if previous_error_version == provided_version:
                # Same version as last error, increment error count
                error_count = int(stored_metadata.get("error_count", 0)) + 1
                stored_history: list[dict[str, Any]] = stored_metadata.get("error_history", [])
                error_history: list[dict[str, Any]] = list[dict[str, Any]](stored_history)
            elif previous_error_version < provided_version:
                # Newer version than last error, reset error count and history
                error_count = 1
                error_history = []
            else:
                # Older version than last error, error out and ignore
                logger.error(
                    f"Agent run {agent_run_id} has a newer version than the last error (DB version {previous_error_version} > provided version {provided_version})"
                )
                continue

            if error_message:
                error_history.append({"error": error_message})
                if len(error_history) > 5:
                    error_history = error_history[-5:]

            status = TelemetryAgentRunStatus.NEEDS_PROCESSING.value
            if error_count > 3:
                status = TelemetryAgentRunStatus.ERROR.value
            metadata_json = {
                "errored_version": provided_version,
                "error_count": error_count,
                "error_history": error_history,
            }

            update_stmt = (
                update(SQLATelemetryAgentRunStatus)
                .where(
                    SQLATelemetryAgentRunStatus.agent_run_id == agent_run_id,
                    SQLATelemetryAgentRunStatus.collection_id == collection_id,
                )
                .values(
                    status=status,
                    metadata_json=metadata_json,
                )
            )

            await self.session.execute(update_stmt)

        await self.session.commit()

        logger.info(
            f"Marked {len(agent_run_versions)} agent runs as needs_processing after error in collection {collection_id}"
        )

    async def update_agent_runs_for_telemetry(
        self,
        ctx: ViewContext,
        agent_runs: Sequence[AgentRun],
        *,
        lineage_entries: Sequence[LineageEntry] | None = None,
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

        # Count how many new agent runs we'll be adding (not updating)
        existing_agent_run_query = select(SQLAAgentRun.id).where(
            SQLAAgentRun.collection_id == ctx.collection_id, SQLAAgentRun.id.in_(agent_run_ids)
        )
        existing_agent_run_result = await self.session.execute(existing_agent_run_query)
        existing_agent_run_ids = set(existing_agent_run_result.scalars().all())
        new_agent_run_count = len(agent_run_ids) - len(existing_agent_run_ids)

        # Check collection size limit using the centralized method
        await self.mono_svc.dont_actually_check_space_for_runs(ctx, new_agent_run_count)

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
            batch_debug_snapshot = [
                {
                    "id": tg.id,
                    "parent": tg.parent_transcript_group_id,
                    "agent_run_id": tg.agent_run_id,
                    "collection_id": tg.collection_id,
                }
                for tg in transcript_group_data
            ]
            logger.debug("Transcript group batch (pre-validation): %s", batch_debug_snapshot)
            # Ensure parent IDs exist either in batch or DB before merge
            batch_ids = {tg.id for tg in transcript_group_data}
            parent_ids = {
                tg.parent_transcript_group_id
                for tg in transcript_group_data
                if tg.parent_transcript_group_id
            }
            existing_parent_ids: set[str] = set()
            if parent_ids:
                query = (
                    select(SQLATranscriptGroup.id)
                    .where(SQLATranscriptGroup.collection_id == ctx.collection_id)
                    .where(SQLATranscriptGroup.id.in_(parent_ids))
                )
                parent_id_result = await self.session.execute(query)
                existing_parent_ids = set(parent_id_result.scalars().all())
            logger.debug(
                "Transcript group parent check: batch_ids=%s parent_ids=%s existing_parent_ids=%s",
                batch_ids,
                parent_ids,
                existing_parent_ids,
            )
            missing_parent_ids = {
                pid for pid in parent_ids if pid not in batch_ids and pid not in existing_parent_ids
            }
            if missing_parent_ids:
                logger.debug(
                    "Clearing missing parents in batch: missing_parent_ids=%s batch_ids=%s",
                    missing_parent_ids,
                    batch_ids,
                )
                # Clear parents for affected groups in this batch before merge
                await self.session.execute(
                    update(SQLATranscriptGroup)
                    .where(
                        SQLATranscriptGroup.id.in_(batch_ids),
                        SQLATranscriptGroup.parent_transcript_group_id.in_(missing_parent_ids),
                    )
                    .values(parent_transcript_group_id=None)
                )
            invalid_child_ids: set[str] = set()
            for tg in transcript_group_data:
                pid = tg.parent_transcript_group_id
                if pid and pid in missing_parent_ids:
                    logger.warning(
                        "Removing reference to missing parent transcript group %s from %s before merge (tg.agent_run_id=%s)",
                        pid,
                        tg.id,
                        tg.agent_run_id,
                    )
                    tg.parent_transcript_group_id = None
                    invalid_child_ids.add(tg.id)
                elif pid:
                    # If parent is not in this batch, double-check the DB directly
                    if pid not in batch_ids:
                        parent_exists = False
                        res = await self.session.execute(
                            select(SQLATranscriptGroup.id).where(
                                SQLATranscriptGroup.id == pid,
                                SQLATranscriptGroup.collection_id == ctx.collection_id,
                            )
                        )
                        parent_exists = res.scalar_one_or_none() is not None
                        if not parent_exists:
                            logger.warning(
                                "Clearing parent transcript group %s from %s after DB check (agent_run_id=%s)",
                                pid,
                                tg.id,
                                tg.agent_run_id,
                            )
                            tg.parent_transcript_group_id = None
                            invalid_child_ids.add(tg.id)
                            continue
                    logger.debug(
                        "Keeping parent transcript group %s for %s (in_batch=%s, in_db=%s)",
                        pid,
                        tg.id,
                        pid in batch_ids,
                        pid in existing_parent_ids,
                    )
                else:
                    logger.debug(
                        "Transcript group %s has no parent; agent_run_id=%s", tg.id, tg.agent_run_id
                    )

            if invalid_child_ids:
                logger.debug(
                    "Persistently clearing parents for invalid children: %s", invalid_child_ids
                )
                await self.session.execute(
                    update(SQLATranscriptGroup)
                    .where(
                        SQLATranscriptGroup.collection_id == ctx.collection_id,
                        SQLATranscriptGroup.id.in_(invalid_child_ids),
                    )
                    .values(parent_transcript_group_id=None)
                )
            post_clean_snapshot = [
                {
                    "id": tg.id,
                    "parent": tg.parent_transcript_group_id,
                    "agent_run_id": tg.agent_run_id,
                    "collection_id": tg.collection_id,
                }
                for tg in transcript_group_data
            ]
            logger.debug("Transcript group batch (post-validation): %s", post_clean_snapshot)

            # Sort transcript groups to ensure parent groups come before children
            sorted_transcript_group_data = sort_transcript_groups_by_parent_order(
                transcript_group_data
            )
            persisted_parent_ids: set[str] = set(existing_parent_ids)
            for sqla_transcript_group in sorted_transcript_group_data:
                pid = sqla_transcript_group.parent_transcript_group_id
                if pid and pid not in persisted_parent_ids and pid not in existing_parent_ids:
                    logger.warning(
                        "Clearing parent transcript group %s from %s before merge due to missing parent in batch or DB",
                        pid,
                        sqla_transcript_group.id,
                    )
                    sqla_transcript_group.parent_transcript_group_id = None
                    pid = None
                # Use merge to handle both insert and update
                logger.debug(
                    "Merging transcript group id=%s parent=%s agent_run_id=%s collection_id=%s",
                    sqla_transcript_group.id,
                    sqla_transcript_group.parent_transcript_group_id,
                    sqla_transcript_group.agent_run_id,
                    sqla_transcript_group.collection_id,
                )
                await self.session.merge(sqla_transcript_group)
                # Flush so parent groups are persisted before children to satisfy FK constraints
                await self.session.flush()
                persisted_parent_ids.add(sqla_transcript_group.id)
                logger.debug(
                    f"Saved transcript group: {sqla_transcript_group.id} with parent {sqla_transcript_group.parent_transcript_group_id}"
                )
        await self.session.commit()

        # Validate transcript_group_id references before inserting transcripts
        await self._validate_transcript_group_references(transcript_data, transcript_group_data)

        # Handle transcripts - delete existing and recreate
        if not transcript_data:
            logger.warning(
                "No transcripts were constructed for agent_run_ids=%s; leaving existing transcripts untouched",
                agent_run_ids,
            )
        else:
            new_transcript_ids = {t.id for t in transcript_data}
            existing_id_result = await self.session.execute(
                select(SQLATranscript.id).where(
                    SQLATranscript.collection_id == ctx.collection_id,
                    SQLATranscript.agent_run_id.in_(agent_run_ids),
                )
            )
            existing_transcript_ids = set(existing_id_result.scalars().all())
            ids_to_delete = existing_transcript_ids - new_transcript_ids

            # Upsert transcripts
            for sqla_transcript in transcript_data:
                await self.session.merge(sqla_transcript)

            if ids_to_delete:
                await self.session.execute(
                    delete(SQLATranscript).where(
                        SQLATranscript.collection_id == ctx.collection_id,
                        SQLATranscript.id.in_(ids_to_delete),
                    )
                )

            if lineage_entries:
                normalized_lineage_entries = [
                    self._normalize_lineage_entry_for_upsert(entry) for entry in lineage_entries
                ]
                if normalized_lineage_entries:
                    for lineage_batch in self._batched_lineage_entries(normalized_lineage_entries):
                        lineage_insert = insert(SQLATelemetryLineage).values(lineage_batch)
                        conflict_columns = [
                            SQLATelemetryLineage.collection_id,
                            SQLATelemetryLineage.agent_run_id,
                            SQLATelemetryLineage.derived_type,
                            SQLATelemetryLineage.derived_id,
                            SQLATelemetryLineage.derived_key,
                            SQLATelemetryLineage.source_type,
                            SQLATelemetryLineage.source_id,
                            SQLATelemetryLineage.source_idx,
                        ]
                        upsert_update_columns = {
                            "telemetry_log_id": lineage_insert.excluded.telemetry_log_id,
                            "telemetry_accumulation_id": lineage_insert.excluded.telemetry_accumulation_id,
                            "source_transcript_id": lineage_insert.excluded.source_transcript_id,
                            "attributes": lineage_insert.excluded.attributes,
                        }
                        upsert_stmt = lineage_insert.on_conflict_do_update(
                            index_elements=conflict_columns,
                            set_=upsert_update_columns,
                        )
                        await self.session.execute(upsert_stmt)
            logger.info(
                "Upserted %s transcripts for agent_run_ids=%s (new=%s updated=%s deleted=%s)",
                len(transcript_data),
                agent_run_ids,
                len(new_transcript_ids - existing_transcript_ids),
                len(new_transcript_ids & existing_transcript_ids),
                len(ids_to_delete),
            )

            # Force a commit and verify from a fresh session to ensure transcripts are persisted
            await self.session.commit()
            try:
                async_session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
                    self.session.bind  # type: ignore[arg-type]
                )
                async with async_session_maker() as verify_session:
                    verification_result: Result[
                        tuple[str, str | None]
                    ] = await verify_session.execute(
                        select(SQLATranscript.id, SQLATranscript.transcript_group_id).where(
                            SQLATranscript.agent_run_id.in_(agent_run_ids)
                        )
                    )
                    persisted: list[tuple[str, str | None]] = [
                        tuple(row) for row in verification_result.all()
                    ]
                    logger.info(
                        "Post-commit verification for agent_run_ids=%s found %s transcripts: %s",
                        agent_run_ids,
                        len(persisted),
                        persisted,
                    )
            except Exception as verify_exc:
                logger.warning(
                    "Failed verification query for agent_run_ids=%s: %s", agent_run_ids, verify_exc
                )

            logger.info(
                f"Added {len(agent_runs)} agent runs, {len(transcript_data)} transcripts, and {len(transcript_group_data)} transcript groups"
            )

    async def _validate_transcript_group_parent_references(
        self, transcript_group_data: List[SQLATranscriptGroup]
    ) -> None:
        """
        Validate that all parent_transcript_group_id references in transcript groups exist in the current batch
        or already exist in the database. If not, set parent to None to avoid foreign key violations.
        This ensures that parent groups are saved before their children.

        Args:
            transcript_group_data: List of SQLATranscriptGroup objects to validate
        """
        # Create a set of all transcript group IDs in the current batch
        current_group_ids = {group.id for group in transcript_group_data}

        # Parent IDs referenced in this batch
        parent_ids = {
            group.parent_transcript_group_id
            for group in transcript_group_data
            if group.parent_transcript_group_id
        }

        logger.debug(
            "Validating transcript group parents: current_group_ids=%s parent_ids=%s",
            current_group_ids,
            parent_ids,
        )

        if not parent_ids:
            return

        # Parents not present in this batch
        missing_in_batch = {pid for pid in parent_ids if pid not in current_group_ids}

        # Check for parents that already exist in the database
        existing_parent_ids: set[str] = set()
        if missing_in_batch:
            query = select(SQLATranscriptGroup.id).where(
                SQLATranscriptGroup.id.in_(missing_in_batch)
            )
            result = await self.session.execute(query)
            existing_parent_ids = set(result.scalars().all())

        # Parents that are neither in the batch nor in the DB
        missing_anywhere = missing_in_batch - existing_parent_ids
        logger.debug(
            "Parent validation intermediate: missing_in_batch=%s existing_parent_ids=%s missing_anywhere=%s",
            missing_in_batch,
            existing_parent_ids,
            missing_anywhere,
        )

        # Check for parent references that don't exist anywhere
        invalid_parent_references: List[tuple[str, str]] = []
        for group in transcript_group_data:
            if (
                group.parent_transcript_group_id
                and group.parent_transcript_group_id in missing_anywhere
            ):
                invalid_parent_references.append((group.id, group.parent_transcript_group_id))

        if invalid_parent_references:
            logger.warning(
                f"Found {len(invalid_parent_references)} transcript groups with parent references not in current batch"
            )
            logger.debug("Invalid parent references: %s", invalid_parent_references)
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

    async def _load_existing_transcripts(
        self, collection_id: str, agent_run_ids: Sequence[str]
    ) -> dict[str, list[Transcript]]:
        """
        Load existing transcripts for the given agent runs so we can reuse IDs when content matches.
        """
        if not agent_run_ids:
            return {}

        stmt = (
            select(SQLATranscript)
            .where(SQLATranscript.collection_id == collection_id)
            .where(SQLATranscript.agent_run_id.in_(agent_run_ids))
        )
        result = await self.session.execute(stmt)
        transcripts_by_agent_run: dict[str, list[Transcript]] = {}
        for row in result.scalars().all():
            messages_value = cast(bytes | bytearray | memoryview, row.messages)
            messages_blob: bytes = bytes(messages_value)
            messages_raw = json.loads(messages_blob)

            parsed_messages: list[ChatMessage] = []
            for msg in messages_raw:
                parsed_messages.append(parse_chat_message(msg))

            metadata_value = cast(bytes | bytearray | memoryview, row.metadata_json)
            metadata_blob: bytes = bytes(metadata_value)
            metadata_raw = json.loads(metadata_blob)
            metadata_dict: Dict[str, Any] = (
                cast(Dict[str, Any], metadata_raw) if isinstance(metadata_raw, dict) else {}
            )
            transcript = Transcript(
                id=row.id,
                name=row.name,
                description=row.description,
                transcript_group_id=row.transcript_group_id,
                created_at=row.created_at,
                messages=parsed_messages,
                metadata=metadata_dict,
            )
            transcripts_by_agent_run.setdefault(row.agent_run_id, []).append(transcript)

        return transcripts_by_agent_run

    async def _create_agent_runs_from_spans(
        self,
        agent_run_spans: Dict[str, Dict[str, List[Dict[str, Any]]]],
        transcript_groups_by_agent_run: Dict[str, List[TranscriptGroup]] | None = None,
        collection_scores: Dict[str, List[Dict[str, Any]]] | None = None,
        collection_metadata: Dict[str, List[Dict[str, Any]]] | None = None,
        existing_transcripts_by_agent_run: dict[str, list[Transcript]] | None = None,
    ) -> tuple[List[AgentRun], List[LineageEntry]]:
        """
        Create AgentRun objects from organized spans, incorporating stored scores and metadata.

        Args:
            agent_run_spans: Organized spans by agent_run_id -> transcript_id -> spans[]
            transcript_groups_by_agent_run: Transcript groups organized by agent run ID
            collection_scores: Stored scores for the collection, organized by agent run ID
            collection_metadata: Stored metadata for the collection, organized by agent run ID

        Returns:
            Tuple of (AgentRun objects, lineage entries)
        """
        collection_agent_runs: List[AgentRun] = []
        lineage_entries: List[LineageEntry] = []

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
            agent_run_lineage_data: List[TranscriptLineageData] = []
            agent_run_scores: Dict[str, int | float | bool | None] = {}
            agent_run_model: str | None = None
            agent_run_metadata_dict: Dict[str, Any] = {}
            agent_run_metadata_events: List[Dict[str, Any]] = []
            transcript_group_events: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
            collection_id: str | None = None

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
                    for metadata_event in self._extract_metadata_events_from_span(span):
                        event_name = metadata_event.get("name")
                        if event_name == "agent_run_metadata":
                            agent_run_metadata_events.append(metadata_event)
                        elif event_name == "transcript_group_metadata":
                            group_id = metadata_event.get("attributes", {}).get(
                                "transcript_group_id"
                            )
                            if group_id:
                                transcript_group_events[group_id].append(metadata_event)

                    # Extract model from span attributes
                    span_attrs = span.get("attributes", {})
                    if collection_id is None:
                        collection_attr = span_attrs.get("collection_id")
                        if isinstance(collection_attr, str):
                            collection_id = collection_attr
                    if not agent_run_model and "gen_ai.response.model" in span_attrs:
                        llm_request_type = (
                            span_attrs.get("llm", {}).get("request", {}).get("type", None)
                        )
                        if llm_request_type != "embedding":
                            agent_run_model = span_attrs["gen_ai.response.model"]
                            logger.info(f"    Found model: {agent_run_model}")

                # Create transcripts from spans (lineage entries created later, after ID reconciliation)
                lineage_data_list = self._create_transcripts_from_spans(
                    transcript_id, transcript_spans
                )
                transcripts_list = [data["transcript"] for data in lineage_data_list]
                logger.info(
                    "    Transcript extraction summary: agent_run_id=%s transcript_id=%s "
                    "span_count=%s transcripts_created=%s",
                    agent_run_id,
                    transcript_id,
                    len(transcript_spans),
                    len(transcripts_list),
                )

                if not transcripts_list:
                    logger.warning(
                        f"    No transcripts created from {len(transcript_spans)} spans for transcript_id: {transcript_id}"
                    )
                    for i, span in enumerate(transcript_spans):
                        span_attrs = span.get("attributes", {})
                        gen_ai_keys = [k for k in span_attrs.keys() if k.startswith("gen_ai")]
                        logger.debug(f"      Span {i} gen_ai keys: {gen_ai_keys}")
                        if not gen_ai_keys:
                            logger.debug(
                                f"      Span {i} has no gen_ai keys. All keys: {list(span_attrs.keys())}"
                            )

                # Add transcripts and lineage data to agent run
                agent_run_transcripts.extend(transcripts_list)
                agent_run_lineage_data.extend(lineage_data_list)

            # Create agent run if it has transcripts
            if agent_run_transcripts:
                logger.info(
                    "  agent_run_id=%s finalized with %s transcripts before DB update",
                    agent_run_id,
                    len(agent_run_transcripts),
                )
                # Create metadata with scores, model, and any additional metadata using BaseAgentRunMetadata
                metadata_dict: Dict[str, Any] = {"scores": agent_run_scores}
                if agent_run_model:
                    metadata_dict["model"] = agent_run_model

                if agent_run_metadata_events:
                    self._apply_agent_run_metadata_events(
                        agent_run_metadata_events, agent_run_metadata_dict
                    )

                # Add any additional metadata from span events
                if agent_run_metadata_dict:
                    deep_merge_dicts(metadata_dict, agent_run_metadata_dict)
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
                            deep_merge_dicts(metadata_dict, stored_metadata)
                            logger.info(f"  Added stored metadata to agent run: {stored_metadata}")

                metadata = metadata_dict

                # Get transcript groups for this agent run
                agent_run_transcript_groups_map: Dict[str, TranscriptGroup] = {}
                if transcript_group_events:
                    metadata_map = self._transcript_group_events_to_metadata_map(
                        transcript_group_events
                    )
                    event_transcript_groups = self._create_transcript_groups_from_accumulation_data(
                        metadata_map
                    )
                    for group_id, events in transcript_group_events.items():
                        for event_idx, event in enumerate(events):
                            span_id = event.get("span_id")
                            if not span_id:
                                logger.error(
                                    "Missing span_id for transcript_group_metadata event; skipping lineage entry (group_id=%s, event_idx=%s, agent_run_id=%s)",
                                    group_id,
                                    event_idx,
                                    agent_run_id,
                                )
                                continue
                            event_attrs = cast(Dict[str, Any], event.get("attributes", {}) or {})
                            lineage_collection_id = (
                                event_attrs.get("collection_id") or collection_id
                            )
                            lineage_agent_run_id = event_attrs.get("agent_run_id") or agent_run_id
                            if isinstance(lineage_collection_id, str) and isinstance(
                                lineage_agent_run_id, str
                            ):
                                lineage_entries.append(
                                    {
                                        "collection_id": lineage_collection_id,
                                        "agent_run_id": lineage_agent_run_id,
                                        "derived_type": "transcript_group",
                                        "derived_id": group_id,
                                        "derived_key": None,
                                        "source_type": "span_event",
                                        "source_id": span_id,
                                        "source_idx": event_idx,
                                        "source_transcript_id": event.get("raw_transcript_id"),
                                        "telemetry_log_id": event.get("telemetry_log_id"),
                                        "telemetry_accumulation_id": event.get(
                                            "telemetry_accumulation_id"
                                        ),
                                        "attributes": None,
                                    }
                                )
                    for tg in event_transcript_groups:
                        if tg.agent_run_id == agent_run_id:
                            agent_run_transcript_groups_map[tg.id] = tg

                if (
                    transcript_groups_by_agent_run
                    and agent_run_id in transcript_groups_by_agent_run
                ):
                    for tg in transcript_groups_by_agent_run[agent_run_id]:
                        agent_run_transcript_groups_map[tg.id] = tg

                agent_run_transcript_groups = list(agent_run_transcript_groups_map.values())

                # Reconcile IDs with existing transcripts to preserve telemetry linkage.
                # _reuse_existing_transcript_ids updates transcript.id and message.id
                # directly on the Transcript objects in agent_run_transcripts.
                existing_transcripts_for_run = (
                    existing_transcripts_by_agent_run.get(agent_run_id, [])
                    if existing_transcripts_by_agent_run
                    else []
                )
                if existing_transcripts_for_run:
                    self._reuse_existing_transcript_ids(
                        agent_run_transcripts, existing_transcripts_for_run
                    )

                # Create lineage entries AFTER ID reconciliation so they use the
                # correct (reconciled) IDs. This avoids having to update entries later.
                transcript_lineage_entries = self._create_lineage_entries_from_data(
                    agent_run_lineage_data
                )
                lineage_entries.extend(transcript_lineage_entries)

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

        return collection_agent_runs, lineage_entries

    def _reuse_existing_transcript_ids(
        self, new_transcripts: list[Transcript], existing_transcripts: list[Transcript]
    ) -> tuple[dict[str, str], dict[str, str]]:
        """
        Reuse transcript and message IDs when content matches existing transcripts.

        Returns:
            A tuple of (transcript_id_mapping, message_id_mapping) where:
            - transcript_id_mapping: old_transcript_id -> matched_transcript_id
            - message_id_mapping: old_message_id -> matched_message_id
        """
        remaining_existing: dict[str, Transcript] = {t.id: t for t in existing_transcripts}
        transcript_id_mapping: dict[str, str] = {}
        message_id_mapping: dict[str, str] = {}

        def threads_match(existing: Transcript, new: Transcript) -> bool:
            return self.matching_thread_start(
                existing.messages, new.messages
            ) or self.matching_thread_start(new.messages, existing.messages)

        for transcript in new_transcripts:
            preferred_candidates = [
                t
                for t in remaining_existing.values()
                if t.transcript_group_id == transcript.transcript_group_id
            ]
            candidates = (
                preferred_candidates if preferred_candidates else list(remaining_existing.values())
            )

            matched: Transcript | None = None
            for candidate in candidates:
                if threads_match(candidate, transcript):
                    matched = candidate
                    break

            if not matched:
                continue

            old_transcript_id = transcript.id
            transcript.id = matched.id
            if not transcript.transcript_group_id:
                transcript.transcript_group_id = matched.transcript_group_id
            if matched.created_at and not transcript.created_at:
                transcript.created_at = matched.created_at
            if not transcript.metadata:
                transcript.metadata = matched.metadata
            transcript_id_mapping[old_transcript_id] = matched.id

            # Reuse message IDs from the matched transcript by position.
            # Message IDs depend on transcript ID, so we need to update them
            # to preserve telemetry lineage links.
            for idx, message in enumerate(transcript.messages):
                old_message_id = getattr(message, "id", None)
                if idx < len(matched.messages):
                    existing_message_id = getattr(matched.messages[idx], "id", None)
                    if existing_message_id:
                        if old_message_id and old_message_id != existing_message_id:
                            message_id_mapping[old_message_id] = existing_message_id
                        message.id = existing_message_id
                else:
                    # Message at this index doesn't exist in matched transcript.
                    # Regenerate a stable ID based on the new (matched) transcript ID.
                    new_stable_id = self._stable_transcript_message_id(matched.id, idx)
                    if old_message_id and old_message_id != new_stable_id:
                        message_id_mapping[old_message_id] = new_stable_id
                    message.id = new_stable_id

            remaining_existing.pop(matched.id, None)

        return transcript_id_mapping, message_id_mapping

    def _create_transcripts_from_spans(
        self, raw_transcript_id: str, transcript_spans: List[Dict[str, Any]]
    ) -> List[TranscriptLineageData]:
        """
        Create Transcript objects from spans and collect lineage source data.

        Lineage entries are NOT created here - instead, we return the source data
        needed to create them. This allows lineage entries to be created AFTER
        ID reconciliation, using the correct (reconciled) IDs.

        Args:
            raw_transcript_id: transcript_id as sent in telemetry
            transcript_spans: List of spans for a transcript

        Returns:
            List of TranscriptLineageData objects containing transcripts and their
            lineage source information.
        """
        # Store all the chat threads and track which spans contributed to each
        chat_threads: List[List[ChatMessage]] = []
        thread_span_indices: List[List[int]] = []
        thread_message_sources: List[List[Dict[str, Any]]] = []
        span_lookup_by_id: Dict[str, Dict[str, Any]] = {}

        # Prefer chronological processing to keep thread reconstruction stable.
        transcript_spans_sorted = sorted(
            transcript_spans, key=lambda span: cast(str, span.get("start_time") or "")
        )

        for span_idx, span in enumerate(transcript_spans_sorted):
            span_messages = self._span_to_chat_messages(span)
            if not span_messages:
                continue

            raw_span_id = span.get("raw_span_id")
            if isinstance(raw_span_id, str) and raw_span_id:
                span_lookup_by_id.setdefault(raw_span_id, span)

            span_start_time = span.get("start_time")
            telemetry_log_id = span.get("telemetry_log_id")
            telemetry_accumulation_id = span.get("telemetry_accumulation_id")

            thread_index, action = self._find_or_create_chat_thread(span_messages, chat_threads)

            if action == "new":
                chat_threads.append(span_messages)
                thread_span_indices.append([span_idx])
                source_entries: List[Dict[str, Any]] = []
                for message_idx in range(len(span_messages)):
                    source_entries.append(
                        {
                            "message_index": message_idx,
                            "first_seen_span_start_time": span_start_time,
                            "raw_span_id": raw_span_id,
                            "telemetry_log_id": telemetry_log_id,
                            "telemetry_accumulation_id": telemetry_accumulation_id,
                        }
                    )
                thread_message_sources.append(source_entries)
                logger.debug(f"    Created new chat thread with {len(span_messages)} messages")
            elif action == "extend" and thread_index is not None:
                existing_thread = chat_threads[thread_index]
                new_messages = span_messages[len(existing_thread) :]
                self._update_empty_tool_call_results(existing_thread, span_messages)
                chat_threads[thread_index].extend(new_messages)
                thread_span_indices[thread_index].append(span_idx)
                existing_sources = thread_message_sources[thread_index]
                for offset in range(len(new_messages)):
                    message_idx = len(existing_thread) + offset
                    existing_sources.append(
                        {
                            "message_index": message_idx,
                            "first_seen_span_start_time": span_start_time,
                            "raw_span_id": raw_span_id,
                            "telemetry_log_id": telemetry_log_id,
                            "telemetry_accumulation_id": telemetry_accumulation_id,
                        }
                    )
                first_message_preview = (
                    new_messages[0].text[:100].replace("\n", " ") if new_messages else "N/A"
                )
                logger.debug(
                    f"    Extended chat thread {thread_index} with {len(new_messages)} new messages. "
                    f"First new message: {first_message_preview}"
                )
            elif action == "skip":
                logger.debug(
                    f"    Skipped span with {len(span_messages)} messages "
                    f"(already contained in thread {thread_index})"
                )

        # Build TranscriptLineageData for each chat thread
        result: List[TranscriptLineageData] = []
        logger.debug(
            f"    Created {len(chat_threads)} chat threads from {len(transcript_spans)} spans"
        )

        if not chat_threads:
            logger.warning(f"    No messages extracted from {len(transcript_spans)} spans")
            total_messages = 0
            for span_idx, span in enumerate(transcript_spans):
                span_messages = self._span_to_chat_messages(span)
                total_messages += len(span_messages)
                logger.debug(f"      Span {span_idx}: extracted {len(span_messages)} messages")
            logger.debug(f"    Total messages extracted from all spans: {total_messages}")
            return result

        for i, chat_thread in enumerate(chat_threads):
            thread_transcript_id = str(uuid.uuid4())

            # Determine transcript_group_id from the last contributing span
            thread_transcript_group_id = None
            if thread_span_indices[i]:
                last_contributing_span_idx = thread_span_indices[i][-1]
                last_contributing_span = transcript_spans[last_contributing_span_idx]
                last_span_attrs = last_contributing_span.get("attributes", {})
                thread_transcript_group_id = last_span_attrs.get("transcript_group_id")

            transcript = Transcript(
                id=thread_transcript_id,
                messages=chat_thread,
                transcript_group_id=thread_transcript_group_id,
            )
            self._ensure_transcript_message_ids(transcript)

            # Build message source info for lineage
            message_sources: list[MessageSourceInfo] = []
            per_message_sources = (
                thread_message_sources[i] if i < len(thread_message_sources) else []
            )
            for message_idx, _ in enumerate(transcript.messages):
                source_info = (
                    per_message_sources[message_idx]
                    if message_idx < len(per_message_sources)
                    else None
                )
                if not source_info:
                    continue

                source_span_id = source_info.get("raw_span_id")
                if not isinstance(source_span_id, str) or not source_span_id:
                    continue

                span = span_lookup_by_id.get(source_span_id)
                span_attrs: Dict[str, Any] = (
                    cast(Dict[str, Any], span.get("attributes", {}) or {}) if span else {}
                )
                collection_id = span_attrs.get("collection_id")
                agent_run_id = span_attrs.get("agent_run_id")
                if not (isinstance(collection_id, str) and isinstance(agent_run_id, str)):
                    continue

                message_sources.append(
                    MessageSourceInfo(
                        message_idx=message_idx,
                        raw_span_id=source_span_id,
                        telemetry_log_id=source_info.get("telemetry_log_id"),
                        telemetry_accumulation_id=source_info.get("telemetry_accumulation_id"),
                        first_seen_span_start_time=source_info.get("first_seen_span_start_time"),
                        collection_id=collection_id,
                        agent_run_id=agent_run_id,
                    )
                )

            # Build transcript source info for lineage
            transcript_sources: list[TranscriptSourceInfo] = []
            for idx in thread_span_indices[i]:
                span = transcript_spans[idx]
                span_raw_id = span.get("raw_span_id")
                if not isinstance(span_raw_id, str) or not span_raw_id:
                    continue

                span_attrs = cast(Dict[str, Any], span.get("attributes", {}) or {})
                collection_id = span_attrs.get("collection_id")
                agent_run_id = span_attrs.get("agent_run_id")
                if not (isinstance(collection_id, str) and isinstance(agent_run_id, str)):
                    continue

                transcript_sources.append(
                    TranscriptSourceInfo(
                        raw_span_id=span_raw_id,
                        telemetry_log_id=span.get("telemetry_log_id"),
                        telemetry_accumulation_id=(
                            span.get("telemetry_accumulation_id")
                            if isinstance(span.get("telemetry_accumulation_id"), str)
                            else None
                        ),
                        collection_id=collection_id,
                        agent_run_id=agent_run_id,
                    )
                )

            result.append(
                TranscriptLineageData(
                    transcript=transcript,
                    raw_transcript_id=raw_transcript_id,
                    message_sources=message_sources,
                    transcript_sources=transcript_sources,
                )
            )

        return result

    def _create_lineage_entries_from_data(
        self, lineage_data_list: List[TranscriptLineageData]
    ) -> List[LineageEntry]:
        """
        Create lineage entries from TranscriptLineageData.

        This is called AFTER ID reconciliation, so the transcript and message IDs
        in the Transcript objects are the final (reconciled) IDs.

        Args:
            lineage_data_list: List of TranscriptLineageData from _create_transcripts_from_spans

        Returns:
            List of lineage entries ready for database insertion.
        """
        lineage_entries: List[LineageEntry] = []

        for data in lineage_data_list:
            transcript = data["transcript"]
            raw_transcript_id = data["raw_transcript_id"]

            # Create message-level lineage entries
            for msg_source in data["message_sources"]:
                message_idx = msg_source["message_idx"]
                if message_idx >= len(transcript.messages):
                    continue

                message_id = getattr(transcript.messages[message_idx], "id", None)
                if not isinstance(message_id, str) or not message_id:
                    continue

                lineage_entries.append(
                    {
                        "collection_id": msg_source["collection_id"],
                        "agent_run_id": msg_source["agent_run_id"],
                        "derived_type": "transcript_message",
                        "derived_id": transcript.id,
                        "derived_key": message_id,
                        "source_type": "span",
                        "source_id": msg_source["raw_span_id"],
                        "source_idx": message_idx,
                        "source_transcript_id": raw_transcript_id,
                        "telemetry_log_id": msg_source["telemetry_log_id"],
                        "telemetry_accumulation_id": msg_source["telemetry_accumulation_id"],
                        "attributes": {
                            "first_seen_span_start_time": msg_source["first_seen_span_start_time"]
                        },
                    }
                )

            # Create transcript-level lineage entries
            for t_source in data["transcript_sources"]:
                lineage_entries.append(
                    {
                        "collection_id": t_source["collection_id"],
                        "agent_run_id": t_source["agent_run_id"],
                        "derived_type": "transcript",
                        "derived_id": transcript.id,
                        "derived_key": None,
                        "source_type": "span",
                        "source_id": t_source["raw_span_id"],
                        "source_transcript_id": raw_transcript_id,
                        "telemetry_log_id": t_source["telemetry_log_id"],
                        "telemetry_accumulation_id": t_source["telemetry_accumulation_id"],
                        "attributes": None,
                    }
                )

        return lineage_entries

    def _normalize_lineage_entry_for_upsert(self, entry: LineageEntry) -> LineageEntry:
        """
        Normalize optional fields so composite uniqueness and upserts work reliably.
        """
        normalized = dict(entry)
        normalized["derived_key"] = normalized.get("derived_key") or ""
        normalized["source_id"] = normalized.get("source_id") or ""
        normalized["source_idx"] = (
            normalized.get("source_idx") if normalized.get("source_idx") is not None else -1
        )
        normalized["attributes"] = normalized.get("attributes") or {}
        return normalized

    def _batched_lineage_entries(
        self, entries: Sequence[LineageEntry]
    ) -> Iterable[Sequence[LineageEntry]]:
        """
        Yield lineage batches sized to stay under the asyncpg bind parameter limit.
        """
        column_count = len(SQLATelemetryLineage.__table__.columns)

        max_bind_params = 32000
        batch_size = max(1, max_bind_params // (column_count + 1))

        for start in range(0, len(entries), batch_size):
            yield entries[start : start + batch_size]

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
        if isinstance(msg, ToolMessage) and msg.tool_call_id:
            tool_call_ids.add(msg.tool_call_id)

        # Extract from AssistantMessage tool_calls
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
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
            if (
                isinstance(msg, ToolMessage)
                and msg.tool_call_id
                and (not msg.text or msg.text.strip() == "")
            ):
                empty_tool_results[msg.tool_call_id] = i
                logger.debug(f"Found empty tool result for tool_call_id: {msg.tool_call_id}")

        if not empty_tool_results:
            return

        # Find corresponding non-empty tool call results in new messages
        for msg in new_messages:
            if (
                isinstance(msg, ToolMessage)
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
                    if key != "prompt_filter_results":
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
                    if key != "prompt_filter_results":
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
                elif role == "model":
                    role = "assistant"
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
            elif "model" in data:
                role = "assistant"
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
            if len(content_parts) == 1 and isinstance(content_parts[0], ContentText):
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

    def _extract_metadata_events_from_span(self, span: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract metadata-related events from a span."""
        metadata_events: List[Dict[str, Any]] = []
        for event in span.get("events", []):
            name = event.get("name")
            if name not in {
                "agent_run_metadata",
                "transcript_metadata",
                "transcript_group_metadata",
            }:
                continue

            event_attrs = event.get("attributes", {})
            metadata_from_json: Dict[str, Any] = {}
            metadata_attrs: Dict[str, Any] = {}
            non_metadata_attrs: Dict[str, Any] = {}

            metadata_json_raw = event_attrs.get("metadata_json")
            if isinstance(metadata_json_raw, str):
                try:
                    parsed_metadata = json.loads(metadata_json_raw)
                    if isinstance(parsed_metadata, dict):
                        metadata_from_json = cast(Dict[str, Any], parsed_metadata)
                    else:
                        logger.warning(
                            "metadata_json payload on event %s is not a dict; ignoring.", name
                        )
                except json.JSONDecodeError:
                    logger.warning("Failed to decode metadata_json on event %s.", name)

            for key, value in event_attrs.items():
                if key == "metadata_json":
                    continue
                if key.startswith("metadata."):
                    metadata_key = key[len("metadata.") :]
                    metadata_attrs[metadata_key] = value
                else:
                    non_metadata_attrs[key] = value

            event_metadata: Dict[str, Any] = {}
            if metadata_from_json:
                event_metadata = dict(metadata_from_json)
            if metadata_attrs:
                unflattened_metadata = self._unflatten_metadata(metadata_attrs)
                if event_metadata:
                    deep_merge_dicts(event_metadata, unflattened_metadata)
                else:
                    event_metadata = unflattened_metadata

            raw_span_id = span.get("raw_span_id")
            telemetry_accumulation_id = span.get("telemetry_accumulation_id")
            metadata_events.append(
                {
                    "name": name,
                    "timestamp": event.get("timestamp"),
                    "span_id": (
                        raw_span_id if isinstance(raw_span_id, str) and raw_span_id else None
                    ),
                    "telemetry_log_id": span.get("telemetry_log_id"),
                    "telemetry_accumulation_id": (
                        telemetry_accumulation_id
                        if isinstance(telemetry_accumulation_id, str)
                        else None
                    ),
                    "raw_transcript_id": span.get("attributes", {}).get("transcript_id"),
                    "attributes": non_metadata_attrs,
                    "metadata": event_metadata,
                }
            )

        return metadata_events

    def _apply_agent_run_metadata_events(
        self, metadata_events: List[Dict[str, Any]], target: Dict[str, Any]
    ) -> None:
        """Deep merge metadata events onto the target dictionary in timestamp order."""
        sorted_events = sorted(metadata_events, key=lambda ev: ev.get("timestamp") or "")
        for event in sorted_events:
            event_metadata = cast(Dict[str, Any], event.get("metadata") or {})
            if event_metadata:
                deep_merge_dicts(target, event_metadata)

    def _transcript_group_events_to_metadata_map(
        self, transcript_group_events: dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, Dict[str, Any]]:
        """Convert transcript group metadata events into the accumulation metadata format."""
        metadata_map: Dict[str, Dict[str, Any]] = {}
        for group_id, events in transcript_group_events.items():
            merged_entry: Dict[str, Any] = {}
            sorted_events = sorted(events, key=lambda ev: ev.get("timestamp") or "")
            for event in sorted_events:
                attrs = event.get("attributes", {})
                for key in (
                    "collection_id",
                    "agent_run_id",
                    "transcript_group_id",
                    "name",
                    "description",
                    "parent_transcript_group_id",
                ):
                    value = attrs.get(key)
                    if value is not None:
                        merged_entry[key] = value

                event_metadata = cast(Dict[str, Any], event.get("metadata") or {})
                if event_metadata:
                    merged_metadata = merged_entry.setdefault("metadata", {})
                    deep_merge_dicts(merged_metadata, event_metadata)

            if "transcript_group_id" not in merged_entry:
                merged_entry["transcript_group_id"] = group_id

            metadata_map[group_id] = merged_entry

        return metadata_map

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
