"""
Service for managing telemetry accumulation data in the database.

This service replaces Redis storage for spans, scores, metadata, and other telemetry data
that needs to be accumulated before processing.
"""

import json
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent_core.docent.db.schemas.tables import (
    SQLATelemetryAccumulation,
    SQLATelemetryAgentRunStatus,
    TelemetryAgentRunStatus,
    sanitize_pg_text,
)

logger = get_logger(__name__)


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

    async def add_spans(
        self, collection_id: str, spans: List[Dict[str, Any]], user_id: Optional[str] = None
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
                key = self._build_key(collection_id)

            # Sanitize the span data to remove null characters and other problematic Unicode sequences
            # Convert to JSON string, sanitize, then parse back to dict
            json_str = json.dumps(span)
            sanitized_json_str = sanitize_pg_text(json_str)
            sanitized_span = json.loads(sanitized_json_str)

            accumulation_entry = SQLATelemetryAccumulation(
                key=key,
                data_type="spans",
                data=sanitized_span,
                user_id=user_id,
            )
            self.session.add(accumulation_entry)

        await self.session.commit()
        logger.info(f"Added {len(spans)} spans to accumulation for collection {collection_id}")

        # Mark agent runs for processing
        if agent_run_ids:
            await self._mark_agent_runs_for_processing(collection_id, agent_run_ids)

    async def get_accumulated_spans(self, collection_id: str) -> List[Dict[str, Any]]:
        """Get all accumulated spans for a collection."""
        # Use pattern matching to find all spans for this collection
        key = self._build_key(collection_id)
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{key}%"),
                    SQLATelemetryAccumulation.data_type == "spans",
                )
            )
            .order_by(SQLATelemetryAccumulation.created_at)
        )

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

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

        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{key}%"),
                    SQLATelemetryAccumulation.data_type == "spans",
                )
            )
            .order_by(SQLATelemetryAccumulation.created_at)
        )

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

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

        # Sanitize the score data to remove null characters and other problematic Unicode sequences
        # Convert to JSON string, sanitize, then parse back to dict
        json_str = json.dumps(score_data)
        sanitized_json_str = sanitize_pg_text(json_str)
        sanitized_score_data = json.loads(sanitized_json_str)

        accumulation_entry = SQLATelemetryAccumulation(
            key=key,
            data_type="scores",
            data=sanitized_score_data,
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
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{key}%"),
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

        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{key}%"),
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

        # Sanitize the metadata data to remove null characters and other problematic Unicode sequences
        # Convert to JSON string, sanitize, then parse back to dict
        json_str = json.dumps(metadata_data)
        sanitized_json_str = sanitize_pg_text(json_str)
        sanitized_metadata_data = json.loads(sanitized_json_str)

        accumulation_entry = SQLATelemetryAccumulation(
            key=key,
            data_type="metadata",
            data=sanitized_metadata_data,
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
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{key}%"),
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

        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{key}%"),
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
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{key}%"),
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

                # Merge metadata, with newer entries taking precedence
                metadata[transcript_group_id].update(entry.data)
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

        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key.like(f"{key}%"),
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

                # Merge metadata, with newer entries taking precedence
                metadata[transcript_group_id].update(entry.data)
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

        from sqlalchemy import delete

        result = await self.session.execute(
            delete(SQLATelemetryAccumulation).where(
                SQLATelemetryAccumulation.key.like(f"{key_pattern}%")
            )
        )

        deleted_count = result.rowcount or 0
        await self.session.commit()

        logger.info(f"Deleted {deleted_count} accumulation records matching {key_pattern}")
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
