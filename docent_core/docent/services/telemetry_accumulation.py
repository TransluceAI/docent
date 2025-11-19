"""
Service for managing telemetry accumulation data in the database.

This service replaces Redis storage for spans, scores, metadata, and other telemetry data
that needs to be accumulated before processing.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, cast
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent_core.docent.db.schemas.tables import (
    SQLATelemetryAccumulation,
    SQLATelemetryAgentRunStatus,
    TelemetryAgentRunStatus,
)

logger = get_logger(__name__)


def deep_merge_dicts(destination: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge two dictionaries in-place.

    Later/inner values override earlier ones while preserving unrelated keys,
    which lets telemetry metadata accumulate without losing nested fields.
    """
    for key, value in source.items():
        dest_value = destination.get(key)
        if isinstance(dest_value, dict) and isinstance(value, dict):
            deep_merge_dicts(cast(Dict[str, Any], dest_value), cast(Dict[str, Any], value))
        else:
            destination[key] = value
    return destination


class TelemetryAccumulationService:
    """Service for managing telemetry accumulation data."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _build_key(
        self,
        collection_id: str,
        agent_run_id: Optional[str] = None,
        transcript_group_id: Optional[str] = None,
        transcript_id: Optional[str] = None,
    ) -> str:
        """
        Build a human-readable key for accumulation entries.

        Order: collection_id > agent_run_id > transcript_group_id > transcript_id

        Args:
            collection_id: The collection ID
            agent_run_id: Optional agent run ID
            transcript_group_id: Optional transcript group ID
            transcript_id: Optional transcript ID

        Returns:
            A human-readable key string
        """
        key_parts = [f"collection_id={collection_id}"]

        if agent_run_id:
            key_parts.append(f"agent_run_id={agent_run_id}")

        if transcript_group_id:
            key_parts.append(f"transcript_group_id={transcript_group_id}")

        if transcript_id:
            key_parts.append(f"transcript_id={transcript_id}")

        return ":".join(key_parts)

    def _escape_like_pattern(self, pattern: str) -> str:
        """
        Escape special characters in a LIKE pattern to treat them as literals.

        Escapes underscores and percent signs so they match literally rather than as wildcards.

        Args:
            pattern: The pattern string to escape

        Returns:
            The escaped pattern string
        """
        return pattern.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")

    async def add_ingestion_status(
        self,
        telemetry_log_id: str,
        status: str,
        details: Dict[str, Any] | None = None,
        user_id: Optional[str] = None,
    ) -> None:
        status_payload: Dict[str, Any] = {
            "telemetry_log_id": telemetry_log_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if details:
            status_payload["details"] = details

        entry = SQLATelemetryAccumulation(
            key=f"telemetry_log_id={telemetry_log_id}",
            data_type="ingestion-status",
            data=status_payload,
            user_id=user_id,
        )
        self.session.add(entry)
        await self.session.commit()

    async def get_latest_ingestion_status(
        self, telemetry_log_id: str
    ) -> tuple[str, Dict[str, Any]] | None:
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                SQLATelemetryAccumulation.data_type == "ingestion-status",
                SQLATelemetryAccumulation.key == f"telemetry_log_id={telemetry_log_id}",
            )
            .order_by(SQLATelemetryAccumulation.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        entry = result.scalar_one_or_none()
        if not entry:
            return None
        data: Dict[str, Any] = entry.data or {}
        status = cast(str, data.get("status", ""))
        return status, data

    async def delete_spans_for_telemetry_log(self, telemetry_log_id: str) -> None:
        await self.session.execute(
            delete(SQLATelemetryAccumulation).where(
                SQLATelemetryAccumulation.data_type == "spans",
                SQLATelemetryAccumulation.data["telemetry_log_id"].astext == telemetry_log_id,
            )
        )
        await self.session.commit()

    async def add_spans(
        self,
        collection_id: str,
        spans: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        *,
        telemetry_log_id: str | None = None,
        replace_existing_for_log: bool = False,
    ) -> None:
        """Add spans to accumulation for a collection."""
        agent_run_ids: set[str] = set()

        for span in spans:
            # Extract agent_run_id from span attributes if present
            agent_run_id = span.get("attributes", {}).get("agent_run_id")
            if agent_run_id:
                agent_run_ids.add(agent_run_id)
                key = self._build_key(collection_id, agent_run_id=agent_run_id)
            else:
                logger.warning(
                    f"Span missing agent_run_id: {span.get('span_id')}, collection_id={collection_id}"
                )
                key = self._build_key(collection_id)

            span_payload = dict(span)
            if telemetry_log_id:
                span_payload["telemetry_log_id"] = telemetry_log_id

            accumulation_entry = SQLATelemetryAccumulation(
                key=key,
                data_type="spans",
                data=span_payload,
                user_id=user_id,
            )
            self.session.add(accumulation_entry)

        await self.session.commit()
        logger.info(
            f"Added {len(spans)} spans to accumulation for collection {collection_id}, span_ids={', '.join([span.get('raw_span_id', '') for span in spans])}"
        )

        # Mark agent runs for processing
        if agent_run_ids:
            await self._mark_agent_runs_for_processing(collection_id, agent_run_ids)

    async def get_accumulated_spans(self, collection_id: str) -> List[Dict[str, Any]]:
        """Get all accumulated spans for a collection."""
        # Use pattern matching to find all spans for this collection
        key = self._build_key(collection_id)
        escaped_key = self._escape_like_pattern(key)
        stmt = select(SQLATelemetryAccumulation).where(
            and_(
                SQLATelemetryAccumulation.key.like(f"{escaped_key}%"),
                SQLATelemetryAccumulation.data_type == "spans",
            )
        )

        result = await self.session.execute(stmt)
        entries = sorted(result.scalars().all(), key=lambda entry: entry.created_at)

        spans: List[Dict[str, Any]] = []
        for entry in entries:
            try:
                spans.append(entry.data)
            except Exception as e:
                logger.error(f"Failed to process span data for collection {collection_id}: {e}")
                continue

        return spans

    async def get_agent_run_spans(
        self, collection_id: str, agent_run_id: str
    ) -> List[Dict[str, Any]]:
        """Get accumulated spans for a specific agent run in a collection."""
        # Build key for the agent run
        key = self._build_key(collection_id, agent_run_id=agent_run_id)
        escaped_key = self._escape_like_pattern(key)

        stmt = select(SQLATelemetryAccumulation).where(
            and_(
                SQLATelemetryAccumulation.key.like(f"{escaped_key}%"),
                SQLATelemetryAccumulation.data_type == "spans",
            )
        )

        result = await self.session.execute(stmt)
        entries = sorted(result.scalars().all(), key=lambda entry: entry.created_at)

        spans: List[Dict[str, Any]] = []
        for entry in entries:
            try:
                spans.append(entry.data)
            except Exception as e:
                logger.error(f"Failed to process span data for collection {collection_id}: {e}")
                continue

        return spans

    async def add_score(
        self,
        collection_id: str,
        agent_run_id: str,
        score_name: str,
        score_value: Any,
        timestamp: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Add a score to accumulation for an agent run."""
        key = self._build_key(collection_id, agent_run_id=agent_run_id)
        score_data = {
            "collection_id": collection_id,
            "agent_run_id": agent_run_id,
            "score_name": score_name,
            "score_value": score_value,
            "timestamp": timestamp,
        }

        accumulation_entry = SQLATelemetryAccumulation(
            key=key,
            data_type="scores",
            data=score_data,
            user_id=user_id,
        )
        self.session.add(accumulation_entry)
        await self.session.commit()

        logger.info(
            f"Added score {score_name}={score_value} for agent_run_id {agent_run_id} in collection {collection_id}"
        )

        # Mark agent run for processing
        await self._mark_agent_runs_for_processing(collection_id, {agent_run_id})

    async def get_collection_scores(self, collection_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """Get all scores for a collection, grouped by agent_run_id."""
        # Use pattern matching to find all scores for this collection
        key = self._build_key(collection_id)
        escaped_key = self._escape_like_pattern(key)
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{escaped_key}%"),
                    SQLATelemetryAccumulation.data_type == "scores",
                )
            )
            .order_by(SQLATelemetryAccumulation.data.op("->>")("timestamp").asc())
        )

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

        scores: Dict[str, List[Dict[str, Any]]] = {}
        for entry in entries:
            try:
                agent_run_id = entry.data.get("agent_run_id")
                if agent_run_id not in scores:
                    scores[agent_run_id] = []

                scores[agent_run_id].append(entry.data)
            except Exception as e:
                logger.error(f"Failed to process score data for collection {collection_id}: {e}")
                continue

        return scores

    async def get_agent_run_scores(
        self, collection_id: str, agent_run_id: str
    ) -> List[Dict[str, Any]]:
        """Get scores for a specific agent run in a collection, returning a flat list of score data."""
        # Build key for the agent run to find its scores
        key = self._build_key(collection_id, agent_run_id=agent_run_id)
        escaped_key = self._escape_like_pattern(key)

        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{escaped_key}%"),
                    SQLATelemetryAccumulation.data_type == "scores",
                )
            )
            .order_by(SQLATelemetryAccumulation.data.op("->>")("timestamp").asc())
        )

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

        scores: List[Dict[str, Any]] = []
        for entry in entries:
            try:
                scores.append(entry.data)
            except Exception as e:
                logger.error(f"Failed to process score data for collection {collection_id}: {e}")
                continue

        return scores

    async def add_agent_run_metadata(
        self,
        collection_id: str,
        agent_run_id: str,
        metadata: Dict[str, Any],
        timestamp: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Add agent run metadata to accumulation."""
        key = self._build_key(collection_id, agent_run_id=agent_run_id)
        metadata_data = {
            "collection_id": collection_id,
            "agent_run_id": agent_run_id,
            "metadata": metadata,
            "timestamp": timestamp,
        }

        accumulation_entry = SQLATelemetryAccumulation(
            key=key,
            data_type="metadata",
            data=metadata_data,
            user_id=user_id,
        )
        self.session.add(accumulation_entry)
        await self.session.commit()

        logger.info(
            f"Added agent run metadata for agent_run_id {agent_run_id} in collection {collection_id}"
        )

        # Mark agent run for processing
        await self._mark_agent_runs_for_processing(collection_id, {agent_run_id})

    async def get_collection_agent_run_metadata(
        self, collection_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get all agent run metadata for a collection, grouped by agent_run_id."""
        # Use pattern matching to find all agent run metadata for this collection
        key = self._build_key(collection_id)
        escaped_key = self._escape_like_pattern(key)
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{escaped_key}%"),
                    SQLATelemetryAccumulation.data_type == "metadata",
                )
            )
            .order_by(SQLATelemetryAccumulation.data.op("->>")("timestamp").asc())
        )

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

        metadata: Dict[str, List[Dict[str, Any]]] = {}
        for entry in entries:
            try:
                agent_run_id = entry.data.get("agent_run_id")
                if agent_run_id not in metadata:
                    metadata[agent_run_id] = []

                metadata[agent_run_id].append(entry.data)
            except Exception as e:
                logger.error(
                    f"Failed to process agent run metadata for collection {collection_id}: {e}"
                )
                continue

        return metadata

    async def get_agent_run_metadata(
        self, collection_id: str, agent_run_id: str
    ) -> List[Dict[str, Any]]:
        """Get agent run metadata for a specific agent run in a collection, returning a flat list of metadata."""
        # Build key for the agent run to find its metadata
        key = self._build_key(collection_id, agent_run_id=agent_run_id)
        escaped_key = self._escape_like_pattern(key)

        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{escaped_key}%"),
                    SQLATelemetryAccumulation.data_type == "metadata",
                )
            )
            .order_by(SQLATelemetryAccumulation.data.op("->>")("timestamp").asc())
        )

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

        metadata: List[Dict[str, Any]] = []
        for entry in entries:
            try:
                metadata.append(entry.data)
            except Exception as e:
                logger.error(
                    f"Failed to process agent run metadata for collection {collection_id}: {e}"
                )
                continue

        return metadata

    async def add_transcript_metadata(
        self,
        collection_id: str,
        transcript_id: str,
        name: Optional[str],
        description: Optional[str],
        transcript_group_id: Optional[str],
        metadata: Optional[Dict[str, Any]],
        timestamp: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Add transcript metadata to accumulation."""
        key = self._build_key(
            collection_id, transcript_group_id=transcript_group_id, transcript_id=transcript_id
        )
        accumulation_entry = SQLATelemetryAccumulation(
            key=key,
            data_type="transcript_metadata",
            data={
                "collection_id": collection_id,
                "transcript_id": transcript_id,
                "name": name,
                "description": description,
                "transcript_group_id": transcript_group_id,
                "metadata": metadata,
                "timestamp": timestamp,
            },
            user_id=user_id,
        )
        self.session.add(accumulation_entry)
        await self.session.commit()

        logger.info(
            f"Added transcript metadata for transcript_id {transcript_id} in collection {collection_id}"
        )

    async def add_transcript_group_metadata(
        self,
        collection_id: str,
        agent_run_id: str,
        transcript_group_id: str,
        name: Optional[str],
        description: Optional[str],
        parent_transcript_group_id: Optional[str],
        metadata: Optional[Dict[str, Any]],
        timestamp: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Add transcript group metadata to accumulation."""
        key = self._build_key(
            collection_id, agent_run_id=agent_run_id, transcript_group_id=transcript_group_id
        )
        accumulation_entry = SQLATelemetryAccumulation(
            key=key,
            data_type="transcript_group_metadata",
            data={
                "transcript_group_id": transcript_group_id,
                "collection_id": collection_id,
                "agent_run_id": agent_run_id,
                "name": name,
                "description": description,
                "parent_transcript_group_id": parent_transcript_group_id,
                "metadata": metadata,
                "timestamp": timestamp,
            },
            user_id=user_id,
        )
        self.session.add(accumulation_entry)
        await self.session.commit()

        logger.info(
            f"Added transcript group metadata for transcript_group_id {transcript_group_id} in collection {collection_id}"
        )

        # Mark agent run for processing
        await self._mark_agent_runs_for_processing(collection_id, {agent_run_id})

    async def get_transcript_group_metadata(self, collection_id: str) -> Dict[str, Dict[str, Any]]:
        """Get all transcript group metadata for a collection, merging multiple calls with recent data taking precedence."""
        # Use pattern matching to find all transcript group metadata for this collection
        key = self._build_key(collection_id)
        escaped_key = self._escape_like_pattern(key)
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{escaped_key}%"),
                    SQLATelemetryAccumulation.data_type == "transcript_group_metadata",
                )
            )
            .order_by(SQLATelemetryAccumulation.data.op("->>")("timestamp").asc())
        )

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

        metadata: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            try:
                transcript_group_id = entry.data.get("transcript_group_id")
                if transcript_group_id not in metadata:
                    metadata[transcript_group_id] = {}

                existing_entry = metadata[transcript_group_id]
                for key, value in entry.data.items():
                    if key == "metadata" and isinstance(value, dict):
                        existing_metadata = existing_entry.get("metadata")
                        if isinstance(existing_metadata, dict):
                            deep_merge_dicts(
                                cast(Dict[str, Any], existing_metadata), cast(Dict[str, Any], value)
                            )
                        else:
                            existing_entry["metadata"] = dict(cast(Dict[str, Any], value))
                    else:
                        existing_entry[key] = value
            except Exception as e:
                logger.error(
                    f"Failed to process transcript group metadata for collection {collection_id}: {e}"
                )
                continue

        return metadata

    async def get_agent_run_transcript_group_metadata(
        self, collection_id: str, agent_run_id: str
    ) -> Dict[str, Dict[str, Any]]:
        """Get transcript group metadata for a specific agent run in a collection, merging multiple calls with recent data taking precedence."""
        # Build key for the agent run to find its transcript group metadata
        key = self._build_key(collection_id, agent_run_id=agent_run_id)
        escaped_key = self._escape_like_pattern(key)

        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{escaped_key}%"),
                    SQLATelemetryAccumulation.data_type == "transcript_group_metadata",
                )
            )
            .order_by(SQLATelemetryAccumulation.data.op("->>")("timestamp").asc())
        )

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

        metadata: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            try:
                transcript_group_id = entry.data.get("transcript_group_id")

                if transcript_group_id not in metadata:
                    metadata[transcript_group_id] = {}

                existing_entry = metadata[transcript_group_id]
                for key, value in entry.data.items():
                    if key == "metadata" and isinstance(value, dict):
                        existing_metadata = existing_entry.get("metadata")
                        if isinstance(existing_metadata, dict):
                            deep_merge_dicts(
                                cast(Dict[str, Any], existing_metadata), cast(Dict[str, Any], value)
                            )
                        else:
                            existing_entry["metadata"] = dict(cast(Dict[str, Any], value))
                    else:
                        existing_entry[key] = value
            except Exception as e:
                logger.error(
                    f"Failed to process transcript group metadata for collection {collection_id}: {e}"
                )
                continue

        return metadata

    async def delete_accumulation_data(
        self,
        collection_id: str,
        agent_run_id: Optional[str] = None,
        transcript_group_id: Optional[str] = None,
        transcript_id: Optional[str] = None,
    ) -> int:
        """
        Delete accumulation data matching the specified criteria.

        Args:
            collection_id: The collection ID (required)
            agent_run_id: Optional agent run ID to delete data for
            transcript_group_id: Optional transcript group ID to delete data for
            transcript_id: Optional transcript ID to delete data for

        Returns:
            Number of accumulation records deleted
        """
        # Build the key pattern to match
        key_pattern = self._build_key(
            collection_id=collection_id,
            agent_run_id=agent_run_id,
            transcript_group_id=transcript_group_id,
            transcript_id=transcript_id,
        )
        escaped_key_pattern = self._escape_like_pattern(key_pattern)

        result = await self.session.execute(
            delete(SQLATelemetryAccumulation).where(
                SQLATelemetryAccumulation.key.like(f"{escaped_key_pattern}%")
            )
        )

        deleted_count = result.rowcount or 0
        await self.session.commit()

        logger.info(f"Deleted {deleted_count} accumulation records matching {key_pattern}")
        return deleted_count

    async def delete_agent_run_accumulations(
        self, collection_id: str, agent_run_ids: Sequence[str], *, chunk_size: int = 200
    ) -> int:
        """Delete accumulation records for multiple agent runs in as few statements as possible."""

        unique_ids = [agent_run_id for agent_run_id in dict.fromkeys(agent_run_ids) if agent_run_id]
        if not unique_ids:
            return 0

        deleted_count = 0
        key_prefixes = [
            self._build_key(collection_id, agent_run_id=agent_run_id) for agent_run_id in unique_ids
        ]

        for start in range(0, len(key_prefixes), chunk_size):
            chunk = key_prefixes[start : start + chunk_size]
            if not chunk:
                continue

            # Chunking keeps the generated predicate below common parameter limits when deleting large batches.
            predicate = or_(
                *[
                    SQLATelemetryAccumulation.key.like(f"{self._escape_like_pattern(key_prefix)}%")
                    for key_prefix in chunk
                ]
            )
            result = await self.session.execute(delete(SQLATelemetryAccumulation).where(predicate))
            deleted_count += result.rowcount or 0

        await self.session.commit()

        logger.info(
            f"Deleted {deleted_count} accumulation records for {len(unique_ids)} agent runs in collection {collection_id}"
        )
        return deleted_count

    async def _mark_agent_runs_for_processing(
        self, collection_id: str, agent_run_ids: set[str]
    ) -> None:
        """
        Mark agent runs as needing processing.

        This method handles both existing and new agent runs:
        - For existing agent runs: updates their processing_status to 'needs_processing'
        - For new agent runs: they will be created with processing_status='needs_processing' when processed

        Args:
            collection_id: The collection ID
            agent_run_ids: Set of agent run IDs that need processing
        """
        if not agent_run_ids:
            return

        # Use a single atomic operation to mark all agent runs as pending
        # This prevents race conditions where some agent runs get marked but others don't
        # Create status records for all agent runs atomically
        status_records: list[dict[str, Any]] = []
        for agent_run_id in agent_run_ids:
            status_records.append(
                {
                    "id": str(uuid4()),
                    "collection_id": collection_id,
                    "agent_run_id": agent_run_id,
                    "status": TelemetryAgentRunStatus.NEEDS_PROCESSING.value,
                    "metadata_json": None,
                }
            )

        # Use PostgreSQL's ON CONFLICT to handle upserts atomically
        # Always mark as needs_processing regardless of current status
        # Increment current_version to indicate new data has arrived
        stmt = insert(SQLATelemetryAgentRunStatus).values(status_records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["agent_run_id"],
            set_={
                "status": TelemetryAgentRunStatus.NEEDS_PROCESSING.value,
                "metadata_json": None,  # Clear any retry/error metadata
                "current_version": SQLATelemetryAgentRunStatus.current_version + 1,
            },
        )

        await self.session.execute(stmt)
        await self.session.commit()

        logger.debug(
            f"Marked {len(agent_run_ids)} agent runs for processing in collection {collection_id}"
        )
