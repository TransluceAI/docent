"""
Service for managing telemetry accumulation data in the database.

This service replaces Redis storage for spans, scores, metadata, and other telemetry data
that needs to be accumulated before processing.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent_core.docent.db.schemas.tables import SQLATelemetryAccumulation

logger = get_logger(__name__)


class TelemetryAccumulationService:
    """Service for managing telemetry accumulation data."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_spans(
        self, collection_id: str, spans: List[Dict[str, Any]], user_id: Optional[str] = None
    ) -> None:
        """Add spans to accumulation for a collection."""
        for span in spans:
            accumulation_entry = SQLATelemetryAccumulation(
                key=collection_id,
                data_type="spans",
                data=span,
                user_id=user_id,
            )
            self.session.add(accumulation_entry)

        await self.session.commit()
        logger.info(f"Added {len(spans)} spans to accumulation for collection {collection_id}")

    async def get_accumulated_spans(self, collection_id: str) -> List[Dict[str, Any]]:
        """Get all accumulated spans for a collection."""
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key == collection_id,
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
        accumulation_entry = SQLATelemetryAccumulation(
            key=collection_id,
            data_type="scores",
            data={
                "collection_id": collection_id,
                "agent_run_id": agent_run_id,
                "score_name": score_name,
                "score_value": score_value,
                "timestamp": timestamp,
            },
            user_id=user_id,
        )
        self.session.add(accumulation_entry)
        await self.session.commit()

        logger.info(
            f"Added score {score_name}={score_value} for agent_run_id {agent_run_id} in collection {collection_id}"
        )

    async def get_collection_scores(self, collection_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """Get all scores for a collection, grouped by agent_run_id."""
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key == collection_id,
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

    async def add_metadata(
        self,
        collection_id: str,
        agent_run_id: str,
        metadata: Dict[str, Any],
        timestamp: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Add metadata to accumulation for an agent run."""
        accumulation_entry = SQLATelemetryAccumulation(
            key=collection_id,
            data_type="metadata",
            data={
                "collection_id": collection_id,
                "agent_run_id": agent_run_id,
                "metadata": metadata,
                "timestamp": timestamp,
            },
            user_id=user_id,
        )
        self.session.add(accumulation_entry)
        await self.session.commit()

        logger.info(f"Added metadata for agent_run_id {agent_run_id} in collection {collection_id}")

    async def get_collection_metadata(self, collection_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """Get all metadata for a collection, grouped by agent_run_id."""
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key == collection_id,
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
                logger.error(f"Failed to process metadata for collection {collection_id}: {e}")
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
        accumulation_entry = SQLATelemetryAccumulation(
            key=collection_id,
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
        accumulation_entry = SQLATelemetryAccumulation(
            key=collection_id,
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

    async def get_transcript_group_metadata(self, collection_id: str) -> Dict[str, Dict[str, Any]]:
        """Get all transcript group metadata for a collection, merging multiple calls with recent data taking precedence."""
        stmt = (
            select(SQLATelemetryAccumulation)
            .where(
                and_(
                    SQLATelemetryAccumulation.key == collection_id,
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

    async def cleanup_collection_data(self, collection_id: str) -> None:
        """Clean up all accumulation data for a collection."""
        stmt = select(SQLATelemetryAccumulation).where(
            SQLATelemetryAccumulation.key == collection_id
        )

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

        for entry in entries:
            await self.session.delete(entry)

        await self.session.commit()
        logger.info(f"Cleaned up accumulation data for collection {collection_id}")

    async def get_collection_data_summary(self, collection_id: str) -> Dict[str, int]:
        """Get a summary of accumulation data counts by type for a collection."""
        stmt = select(SQLATelemetryAccumulation.data_type, SQLATelemetryAccumulation.id).where(
            SQLATelemetryAccumulation.key == collection_id
        )

        result = await self.session.execute(stmt)
        entries = result.all()

        summary: Dict[str, int] = {}
        for data_type, _ in entries:
            summary[data_type] = summary.get(data_type, 0) + 1

        return summary
