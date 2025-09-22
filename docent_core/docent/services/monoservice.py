from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import (
    Any,
    AsyncIterator,
    Literal,
    ParamSpec,
    Sequence,
    TypeVar,
)
from uuid import uuid4

from passlib.context import CryptContext
from sqlalchemy import (
    ColumnElement,
    bindparam,
    delete,
    exists,
    func,
    literal,
    select,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import lateral, text

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun, FilterableField
from docent.data_models.transcript import Transcript, TranscriptGroup
from docent_core._db_service.db import DocentDB
from docent_core._llm_util.data_models.llm_output import AsyncEmbeddingStreamingCallback
from docent_core._llm_util.providers.openai import get_chunked_openai_embeddings_async
from docent_core._server._broker.redis_client import enqueue_job
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.filters import ComplexFilter
from docent_core.docent.db.schemas.auth_models import (
    PERMISSION_LEVELS,
    Permission,
    ResourceType,
    SubjectType,
    User,
)
from docent_core.docent.db.schemas.chart import SQLAChart
from docent_core.docent.db.schemas.chat import SQLAChatSession
from docent_core.docent.db.schemas.refinement import SQLARefinementAgentSession
from docent_core.docent.db.schemas.rubric import SQLAJudgeResult, SQLARubric
from docent_core.docent.db.schemas.tables import (
    EMBEDDING_DIM,
    TABLE_TRANSCRIPT_EMBEDDING,
    JobStatus,
    SQLAAccessControlEntry,
    SQLAAgentRun,
    SQLAAnalyticsEvent,
    SQLAApiKey,
    SQLACollection,
    SQLAJob,
    SQLAModelApiKey,
    SQLASearchCluster,
    SQLASearchQuery,
    SQLASearchResult,
    SQLASearchResultCluster,
    SQLASession,
    SQLATelemetryAgentRunStatus,
    SQLATelemetryLog,
    SQLATranscript,
    SQLATranscriptEmbedding,
    SQLATranscriptGroup,
    SQLAUser,
    SQLAView,
)

logger = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class _NotGiven:
    """Sentinel class for detecting when a parameter was not provided."""

    def __repr__(self):
        return "NOT_GIVEN"


NOT_GIVEN = _NotGiven()


class MonoService:
    def __init__(self, db: DocentDB):
        self.db = db

    @classmethod
    async def init(cls):
        db = await DocentDB.init()
        return cls(db)

    #############
    # Collection #
    #############

    async def create_collection(
        self,
        user: User,
        collection_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ):
        # Create FG
        collection_id = collection_id or str(uuid4())
        async with self.db.session() as session:
            session.add(
                SQLACollection(
                    id=collection_id, name=name, description=description, created_by=user.id
                )
            )

        # Create ACL entry for the user
        await self.set_acl_permission(
            SubjectType.USER,
            subject_id=user.id,
            resource_type=ResourceType.COLLECTION,
            resource_id=collection_id,
            permission=Permission.ADMIN,
        )

        logger.info(f"Created Collection with ID: {collection_id}")
        return collection_id

    async def update_collection(
        self,
        collection_id: str,
        name: str | None | _NotGiven = NOT_GIVEN,
        description: str | None | _NotGiven = NOT_GIVEN,
    ):
        """
        Update the name and/or description of a Collection.
        Fields set to `None` will be nulled in the database.
        Fields not provided (i.e., left as NOT_GIVEN) will be unchanged.
        """
        values_to_update = {}
        if name is not NOT_GIVEN:
            values_to_update["name"] = name
        if description is not NOT_GIVEN:
            values_to_update["description"] = description

        if not values_to_update:
            logger.info(f"No values provided to update Collection {collection_id}")
            return

        async with self.db.session() as session:
            await session.execute(
                update(SQLACollection)
                .where(SQLACollection.id == collection_id)
                .values(**values_to_update)
            )
        logger.info(f"Updated Collection {collection_id} with values: {values_to_update}")

    async def collection_exists(self, collection_id: str) -> bool:
        async with self.db.session() as session:
            result = await session.execute(
                select(exists().where(SQLACollection.id == collection_id))
            )
            return result.scalar_one()

    async def delete_collection(self, collection_id: str) -> None:
        # Remove all references from views to other dimensions and filters
        async with self.db.session() as session:
            await session.execute(
                update(SQLAView)
                .where(SQLAView.collection_id == collection_id)
                .values(outer_bin_key=None, inner_bin_key=None, base_filter_dict=None)
            )

        # Delete telemetry logs
        async with self.db.session() as session:
            await session.execute(
                delete(SQLATelemetryLog).where(SQLATelemetryLog.collection_id == collection_id)
            )

        # Delete telemetry accumulation data for the collection
        async with self.db.session() as session:
            from docent_core.docent.services.telemetry_accumulation import (
                TelemetryAccumulationService,
            )

            accumulation_service = TelemetryAccumulationService(session)
            await accumulation_service.delete_accumulation_data(collection_id)

        # delete all search result clusters joining on search result id to get collection_id
        async with self.db.session() as session:
            await session.execute(
                delete(SQLASearchResultCluster).where(
                    SQLASearchResultCluster.cluster_id.in_(
                        select(SQLASearchCluster.id).where(
                            SQLASearchCluster.collection_id == collection_id
                        )
                    )
                )
            )

        # delete all search results
        async with self.db.session() as session:
            await session.execute(
                delete(SQLASearchResult).where(SQLASearchResult.collection_id == collection_id)
            )

        # delete all search clusters
        async with self.db.session() as session:
            await session.execute(
                delete(SQLASearchCluster).where(SQLASearchCluster.collection_id == collection_id)
            )

        # delete all search queries
        async with self.db.session() as session:
            await session.execute(
                delete(SQLASearchQuery).where(SQLASearchQuery.collection_id == collection_id)
            )

        # Delete all attributes
        async with self.db.session() as session:
            await session.execute(
                delete(SQLASearchResult).where(SQLASearchResult.collection_id == collection_id)
            )

        # Delete all embeddings
        async with self.db.session() as session:
            await session.execute(
                delete(SQLATranscriptEmbedding).where(
                    SQLATranscriptEmbedding.collection_id == collection_id
                )
            )

        # Delete all analytics events
        async with self.db.session() as session:
            await session.execute(
                delete(SQLAAnalyticsEvent).where(SQLAAnalyticsEvent.collection_id == collection_id)
            )

        # Delete all transcripts
        async with self.db.session() as session:
            await session.execute(
                delete(SQLATranscript).where(SQLATranscript.collection_id == collection_id)
            )

        # Delete all transcript groups
        async with self.db.session() as session:
            await session.execute(
                delete(SQLATranscriptGroup).where(
                    SQLATranscriptGroup.collection_id == collection_id
                )
            )

        # delete all chat_sessions for agent runs in this collection
        async with self.db.session() as session:
            await session.execute(
                delete(SQLAChatSession).where(
                    SQLAChatSession.agent_run_id.in_(
                        select(SQLAAgentRun.id).where(SQLAAgentRun.collection_id == collection_id)
                    )
                )
            )

        # delete judge_results for agent runs in this collection
        async with self.db.session() as session:
            await session.execute(
                delete(SQLAJudgeResult).where(
                    SQLAJudgeResult.agent_run_id.in_(
                        select(SQLAAgentRun.id).where(SQLAAgentRun.collection_id == collection_id)
                    )
                )
            )

        # Delete all agent runs
        async with self.db.session() as session:
            await session.execute(
                delete(SQLAAgentRun).where(SQLAAgentRun.collection_id == collection_id)
            )

        # Delete all telemetry agent run status records
        async with self.db.session() as session:
            await session.execute(
                delete(SQLATelemetryAgentRunStatus).where(
                    SQLATelemetryAgentRunStatus.collection_id == collection_id
                )
            )

        # Delete all Access Control Entries
        async with self.db.session() as session:
            view_ids = await session.execute(
                select(SQLAView.id).where(SQLAView.collection_id == collection_id)
            )
            view_ids = view_ids.scalars().all()
            await session.execute(
                delete(SQLAAccessControlEntry).where(SQLAAccessControlEntry.view_id.in_(view_ids))
            )
            await session.execute(
                delete(SQLAAccessControlEntry).where(
                    SQLAAccessControlEntry.collection_id == collection_id
                )
            )

        # Delete views
        async with self.db.session() as session:
            await session.execute(delete(SQLAView).where(SQLAView.collection_id == collection_id))

        # Delete charts
        async with self.db.session() as session:
            await session.execute(delete(SQLAChart).where(SQLAChart.collection_id == collection_id))

        # Delete all refinement agent sessions for rubrics in this collection
        async with self.db.session() as session:
            await session.execute(
                delete(SQLARefinementAgentSession).where(
                    SQLARefinementAgentSession.rubric_id.in_(
                        select(SQLARubric.id).where(SQLARubric.collection_id == collection_id)
                    )
                )
            )

        # Delete all rubrics for this collection
        async with self.db.session() as session:
            await session.execute(
                delete(SQLARubric).where(SQLARubric.collection_id == collection_id)
            )

        # Finally delete the collection
        async with self.db.session() as session:
            await session.execute(delete(SQLACollection).where(SQLACollection.id == collection_id))
            logger.info(f"Deleted collection {collection_id}")

    async def get_collections(self, user: User | None = None) -> Sequence[SQLACollection]:
        """
        List Collections that the user has access to.
        If no user provided, returns all collections (for backward compatibility).
        """
        async with self.db.session() as session:
            query = select(SQLACollection).order_by(SQLACollection.created_at.desc())

            if user is not None:
                query = (
                    query.join(
                        SQLAAccessControlEntry,
                        SQLACollection.id == SQLAAccessControlEntry.collection_id,
                    )
                    .where(
                        # User has direct permission
                        (SQLAAccessControlEntry.user_id == user.id)
                        |
                        # User's organization has permission (if user has organizations)
                        (
                            SQLAAccessControlEntry.organization_id.in_(user.organization_ids)
                            if user.organization_ids
                            else False
                        )
                        # Notably, we don't make public collections discoverable.
                    )
                    .distinct()  # Avoid duplicates from multiple ACL entries
                )

            result = await session.execute(query)
            return result.scalars().all()

    async def get_collection(self, collection_id: str) -> SQLACollection | None:
        """
        Get a single collection by ID.

        Args:
            collection_id: The collection ID to retrieve

        Returns:
            The collection if found, None otherwise
        """
        async with self.db.session() as session:
            query = select(SQLACollection).where(SQLACollection.id == collection_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    ##############
    # Agent Runs #
    ##############

    async def count_collection_agent_runs(self, collection_id: str) -> int:
        """Count all agent runs for a collection (ignores base filters)."""
        async with self.db.session() as session:
            query = select(func.count()).where(SQLAAgentRun.collection_id == collection_id)
            result = await session.execute(query)
            return result.scalar_one()

    async def check_space_for_runs(self, ctx: ViewContext, new_runs: int):
        existing_runs = await self.count_collection_agent_runs(ctx.collection_id)
        if existing_runs + new_runs > 100_000:
            raise ValueError("Number of agent runs in the current collection is too large")

    async def add_agent_runs(
        self,
        ctx: ViewContext,
        agent_runs: Sequence[AgentRun],
    ):
        # Convert AgentRun objects to SQLAlchemy objects using existing conversion functions
        agent_run_data: list[SQLAAgentRun] = []
        transcript_data: list[SQLATranscript] = []
        transcript_group_data: list[SQLATranscriptGroup] = []

        # Process all agent runs, transcripts, and transcript groups first
        for ar in agent_runs:
            sqla_agent_run = SQLAAgentRun.from_agent_run(ar, ctx.collection_id)
            agent_run_data.append(sqla_agent_run)

            # Process transcripts for this agent run
            for t in ar.transcripts:
                sqla_transcript = SQLATranscript.from_transcript(t, t.id, ctx.collection_id, ar.id)
                transcript_data.append(sqla_transcript)

            # Process transcript groups for this agent run
            if hasattr(ar, "transcript_groups") and ar.transcript_groups:
                for tg in ar.transcript_groups:
                    # Use the existing from_transcript_group method to get all fields properly
                    sqla_transcript_group = SQLATranscriptGroup.from_transcript_group(
                        tg, ctx.collection_id
                    )
                    transcript_group_data.append(sqla_transcript_group)

        # Sort transcript groups so they don't violate foreign key constraints when inserted at once
        transcript_group_data = sort_transcript_groups_by_parent_order(transcript_group_data)

        # Insert all rows in a single transaction using add_all
        async with self.db.session() as session:
            session.add_all(agent_run_data)
            session.add_all(transcript_group_data)
            await session.flush()  # (mengk) seems necessary to avoid FK violations, for some strange reason
            session.add_all(transcript_data)

        logger.info(
            f"Added {len(agent_runs)} agent runs, {len(transcript_data)} transcripts, and {len(transcript_group_data)} transcript groups"
        )

    async def delete_agent_runs(self, collection_id: str, agent_run_ids: list[str]) -> int:
        """
        Delete specific agent runs from a collection.

        This method deletes agent runs and their associated data.

        Args:
            collection_id: The collection ID
            agent_run_ids: List of agent run IDs to delete

        Returns:
            Number of agent runs deleted
        """
        if not agent_run_ids:
            return 0

        async with self.db.session() as session:
            # Delete telemetry agent run status records first
            # (These don't have CASCADE delete since they intentionally don't have FK constraint)
            telemetry_result = await session.execute(
                delete(SQLATelemetryAgentRunStatus).where(
                    SQLATelemetryAgentRunStatus.agent_run_id.in_(agent_run_ids),
                    SQLATelemetryAgentRunStatus.collection_id == collection_id,
                )
            )
            telemetry_count = telemetry_result.rowcount or 0

            # Delete telemetry accumulation data for these agent runs
            from docent_core.docent.services.telemetry_accumulation import (
                TelemetryAccumulationService,
            )

            accumulation_service = TelemetryAccumulationService(session)
            accumulation_count = 0
            for agent_run_id in agent_run_ids:
                count = 0
                if agent_run_id:
                    count = await accumulation_service.delete_accumulation_data(
                        collection_id, agent_run_id=agent_run_id
                    )
                accumulation_count += count

            agent_run_result = await session.execute(
                delete(SQLAAgentRun).where(
                    SQLAAgentRun.id.in_(agent_run_ids), SQLAAgentRun.collection_id == collection_id
                )
            )
            deleted_count = agent_run_result.rowcount or 0

            await session.commit()

        logger.info(
            f"Deleted {deleted_count} agent runs, {telemetry_count} telemetry records, "
            f"and {accumulation_count} accumulation records from collection {collection_id} "
            f"(transcripts and transcript groups deleted via CASCADE)"
        )

        return deleted_count

    async def add_and_enqueue_embedding_job(self, ctx: ViewContext):
        collection_id = ctx.collection_id
        pending_count = await self.get_embedding_job_count(
            collection_id, SQLAJob.status == JobStatus.PENDING
        )
        running_count = await self.get_embedding_job_count(
            collection_id, SQLAJob.status == JobStatus.RUNNING
        )

        # Only start if there's at most one running job and no pending jobs
        if running_count <= 1 and pending_count == 0:
            # Determine whether to index the new agent runs
            total_runs = await self.count_base_agent_runs(ctx)
            should_index = total_runs >= 5_000

            # Enqueue a job in pg and start a redis worker
            job_id = await self.add_embedding_job(collection_id, should_index)
            await enqueue_job(ctx, job_id)  # type: ignore

            logger.info(f"Enqueued embedding job {job_id} for collection {collection_id}")

    async def get_agent_run_ids(
        self,
        ctx: ViewContext,
        sort_field: str | None = None,
        sort_direction: Literal["asc", "desc"] = "asc",
    ) -> list[str]:
        """
        Get agent run IDs for a given Collection ID without fetching transcripts.
        This is more efficient than get_agent_runs when you only need the IDs.

        Args:
            ctx: View context
            sort_field: Field to sort by (e.g., "metadata.model", "metadata.score")
            sort_direction: Sort direction ("asc" or "desc")
        """
        async with self.db.session() as session:
            query = select(SQLAAgentRun.id).where(ctx.get_base_where_clause(SQLAAgentRun))

            # Add sorting if specified
            if sort_field:
                if sort_field.startswith("metadata."):
                    # Extract the JSON path from metadata.field.subfield
                    path_parts = sort_field.split(".")
                    path_parts = path_parts[1:]  # Remove "metadata." prefix

                    # Build the JSON path expression for PostgreSQL
                    # Convert "field.subfield" to ->'field'->'subfield'
                    sort_expr = SQLAAgentRun.metadata_json
                    for part in path_parts:
                        sort_expr = sort_expr[part]
                else:
                    if sort_field == "agent_run_id":
                        sort_expr = SQLAAgentRun.id
                    elif sort_field == "created_at":
                        sort_expr = SQLAAgentRun.created_at
                    else:
                        raise ValueError(f"Invalid sort field: {sort_field}")

                # Apply sorting
                if sort_direction == "desc":
                    query = query.order_by(sort_expr.desc())
                else:
                    query = query.order_by(sort_expr.asc())

            result = await session.execute(query)
            agent_run_ids = result.scalars().all()
            logger.info(f"get_agent_run_ids: Found {len(agent_run_ids)} agent run IDs")
            return list(agent_run_ids)

    async def get_agent_runs(
        self,
        # ctx: ViewContext | None = None,
        ctx: ViewContext,
        agent_run_ids: list[str] | None = None,
        _where_clause: ColumnElement[bool] | None = None,
        _limit: int | None = None,
        apply_base_where_clause: bool = True,
    ) -> list[AgentRun]:
        """
        Get all agent runs for a given Collection ID.
        """
        async with self.db.session() as session:
            if agent_run_ids is not None and len(agent_run_ids) > 10_000:
                agent_runs_raw: list[SQLAAgentRun] = []
                batch_size = 10_000

                for i in range(0, len(agent_run_ids), batch_size):
                    batch_ids = agent_run_ids[i : i + batch_size]
                    query = select(SQLAAgentRun).where(SQLAAgentRun.id.in_(batch_ids))
                    if apply_base_where_clause:
                        query = query.where(ctx.get_base_where_clause(SQLAAgentRun))
                    if _where_clause is not None:
                        query = query.where(_where_clause)
                    if _limit is not None:
                        # Apply limit to the entire result set, not per batch
                        remaining_limit = _limit - len(agent_runs_raw)
                        if remaining_limit <= 0:
                            break
                        query = query.limit(remaining_limit)

                    result = await session.execute(query)
                    batch_agent_runs = result.scalars().all()
                    agent_runs_raw.extend(batch_agent_runs)

            else:
                query = select(SQLAAgentRun)
                if apply_base_where_clause:
                    query = query.where(ctx.get_base_where_clause(SQLAAgentRun))
                if agent_run_ids is not None:
                    query = query.where(SQLAAgentRun.id.in_(agent_run_ids))
                if _where_clause is not None:
                    query = query.where(_where_clause)
                if _limit is not None:
                    query = query.limit(_limit)

                result = await session.execute(query)
                agent_runs_raw = list(result.scalars().all())

            # Get transcripts for those runs
            agent_run_ids = [ar.id for ar in agent_runs_raw]
            if agent_run_ids:
                # Use batch processing to avoid PostgreSQL parameter limits
                transcripts_raw: list[SQLATranscript] = []
                batch_size = 10_000

                for i in range(0, len(agent_run_ids), batch_size):
                    batch_ids = agent_run_ids[i : i + batch_size]
                    result = await session.execute(
                        select(SQLATranscript).where(SQLATranscript.agent_run_id.in_(batch_ids))
                    )
                    batch_transcripts = result.scalars().all()
                    transcripts_raw.extend(batch_transcripts)
            else:
                transcripts_raw = []

            # Get transcript groups for the agent runs
            transcript_groups_raw: list[SQLATranscriptGroup] = []
            if agent_run_ids:
                # Use batch processing to avoid PostgreSQL parameter limits
                batch_size = 10_000

                for i in range(0, len(agent_run_ids), batch_size):
                    batch_ids = agent_run_ids[i : i + batch_size]
                    result = await session.execute(
                        select(SQLATranscriptGroup).where(
                            SQLATranscriptGroup.agent_run_id.in_(batch_ids)
                        )
                    )
                    batch_transcript_groups = result.scalars().all()
                    transcript_groups_raw.extend(batch_transcript_groups)

        # Collate run_id -> transcripts
        agent_run_transcripts: dict[str, list[Transcript]] = {}
        for t_raw in transcripts_raw:
            agent_run_transcripts.setdefault(t_raw.agent_run_id, []).append(t_raw.to_transcript())

        # Collate run_id -> transcript groups
        agent_run_transcript_groups: dict[str, list[TranscriptGroup]] = {}
        for tg_raw in transcript_groups_raw:
            agent_run_transcript_groups.setdefault(tg_raw.agent_run_id, []).append(
                tg_raw.to_transcript_group()
            )

        final_result = [
            ar_raw.to_agent_run(
                transcripts=agent_run_transcripts.get(ar_raw.id, []),
                transcript_groups=agent_run_transcript_groups.get(ar_raw.id, []),
            )
            for ar_raw in agent_runs_raw
        ]

        return final_result

    async def get_metadata_for_agent_runs(
        self,
        ctx: ViewContext,
        agent_run_ids: list[str],
        apply_base_where_clause: bool = True,
    ) -> dict[str, dict[str, Any]]:
        """
        Efficiently fetch only metadata for the specified agent run IDs.

        This avoids loading transcripts and transcript groups, which can be expensive.

        Args:
            ctx: View context used to apply base filters and permissions.
            agent_run_ids: List of agent run IDs to fetch metadata for.
            apply_base_where_clause: Whether to apply the base where clause.

        Returns:
            Mapping of agent_run_id -> structured metadata dict with:
            - metadata: actual JSON metadata from the database
            - created_at: timestamp as direct key
            - agent_run_id: the run ID as direct key
        """
        if not agent_run_ids:
            return {}

        metadata_map: dict[str, dict[str, Any]] = {}

        async with self.db.session() as session:
            # Use batching to avoid exceeding database parameter limits
            batch_size = 10_000
            for i in range(0, len(agent_run_ids), batch_size):
                batch_ids = agent_run_ids[i : i + batch_size]

                query = select(
                    SQLAAgentRun.id, SQLAAgentRun.metadata_json, SQLAAgentRun.created_at
                ).where(SQLAAgentRun.id.in_(batch_ids))
                if apply_base_where_clause:
                    query = query.where(ctx.get_base_where_clause(SQLAAgentRun))

                result = await session.execute(query)
                for run_id, metadata, created_at in result.all():
                    # Structure the response with metadata in a separate key
                    # and non-JSON fields as direct keys
                    structured_metadata: dict[str, Any] = {
                        "agent_run_id": run_id,
                        "metadata": metadata or {},
                    }

                    # Add created_at as a direct key
                    if created_at:
                        structured_metadata["created_at"] = created_at.isoformat()

                    metadata_map[run_id] = structured_metadata

        return metadata_map

    async def get_agent_run(
        self, ctx: ViewContext, agent_run_id: str, apply_base_where_clause: bool = True
    ) -> AgentRun | None:
        """
        Get an AgentRun from the database by its ID.

        Args:
            ctx: The ViewContext to use for the query.
            agent_run_id: The ID of the agent run to get.
            apply_base_where_clause: Whether to apply the base where clause to the query.

        Returns:
            The agent run.
        """
        agent_runs = await self.get_agent_runs(
            ctx,
            _where_clause=SQLAAgentRun.id.in_([agent_run_id]),
            apply_base_where_clause=apply_base_where_clause,
        )
        assert len(agent_runs) <= 1, f"Found {len(agent_runs)} AgentRuns with ID {agent_run_id}"
        return agent_runs[0] if agent_runs else None

    async def get_unique_field_values(
        self, ctx: ViewContext, field_name: str, search: str | None = None, limit: int = 100
    ) -> list[str]:
        """
        Get unique values for a specific metadata field from agent runs in the collection.

        Args:
            ctx: The ViewContext to use for the query.
            field_name: The field name (e.g., "metadata.task_id")
            search: Optional search term to filter values (case-insensitive substring match)
            limit: Maximum number of unique values to return (default 100)

        Returns:
            List of unique string values for the field
        """
        async with self.db.session() as session:
            field_parts = field_name.split(".")

            if field_parts[0] == "metadata" and len(field_parts) > 1:
                json_path_parts = field_parts[1:]
                for part in json_path_parts:
                    if not part.replace("_", "").replace("-", "").isalnum():
                        return []

                field_expr = SQLAAgentRun.metadata_json
                for part in json_path_parts[:-1]:
                    field_expr = field_expr.op("->")(part)
                field_expr = field_expr.op("->>")(json_path_parts[-1])

                where_conditions = [
                    ctx.get_base_where_clause(SQLAAgentRun),
                    field_expr.isnot(None),
                ]

                # Add search filter if provided
                if search:
                    where_conditions.append(field_expr.ilike(func.concat("%", search, "%")))

                query = select(func.distinct(field_expr)).where(*where_conditions).limit(limit)

                result = await session.execute(query)
                values = [row[0] for row in result.fetchall() if row[0] is not None]
                return sorted(values)
            else:
                return []

    async def count_base_agent_runs(self, ctx: ViewContext) -> int:

        async with self.db.session() as session:
            query = (
                select(func.count())
                .select_from(SQLAAgentRun)
                .where(ctx.get_base_where_clause(SQLAAgentRun))
            )

            result = await session.execute(query)
            count = result.scalar_one()
            return count

    #########
    # Views #
    #########

    async def get_all_view_ctxs(self, collection_id: str) -> list[ViewContext]:
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAView.id).where(SQLAView.collection_id == collection_id)
            )
            view_ids = result.scalars().all()
            return [await self.get_view_ctx(view_id) for view_id in view_ids]

    async def get_view_ctx(self, view_id: str) -> ViewContext:
        async with self.db.session() as session:
            # Get the view
            result = await session.execute(
                select(SQLAView).options(selectinload(SQLAView.user)).where(SQLAView.id == view_id)
            )
            view = result.scalar_one_or_none()
            if view is None:
                raise ValueError(f"View with ID {view_id} not found")

            # Check that the base filter is a ComplexFilter
            if view.base_filter is not None:
                assert isinstance(
                    view.base_filter, ComplexFilter
                ), "Base filter must be a ComplexFilter"

            return ViewContext(
                collection_id=view.collection_id,
                view_id=view.id,
                base_filter=view.base_filter,
                user=view.user.to_user(),
            )

    async def get_default_view_ctx(self, collection_id: str, user: User) -> ViewContext:
        # TODO(mengk): assert that collection_id exists

        # Check if a default view exists for this fg
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAView).where(
                    SQLAView.collection_id == collection_id,
                    SQLAView.user_id == user.id,
                    SQLAView.for_sharing.is_(False),
                )
            )
            view = result.scalar_one_or_none()

        # If not, create a new view that clones the FG creator's default view
        if view is None:
            # Who is the creator of the FG?
            async with self.db.session() as session:
                result = await session.execute(
                    select(SQLACollection.created_by).where(SQLACollection.id == collection_id)
                )
                creator_id = result.scalar_one()

            # Get the creator's default view
            async with self.db.session() as session:
                result = await session.execute(
                    select(SQLAView).where(
                        SQLAView.collection_id == collection_id,
                        SQLAView.user_id == creator_id,
                        SQLAView.for_sharing.is_(False),
                    )
                )
                creator_default_view = result.scalar_one_or_none()

            # Create new view and insert
            if creator_default_view is not None:
                view = SQLAView(
                    id=str(uuid4()),
                    collection_id=collection_id,
                    user_id=user.id,
                    base_filter_dict=creator_default_view.base_filter_dict,
                    inner_bin_key=creator_default_view.inner_bin_key,
                    outer_bin_key=creator_default_view.outer_bin_key,
                )
            else:
                view = SQLAView(
                    id=str(uuid4()),
                    collection_id=collection_id,
                    user_id=user.id,
                )
            async with self.db.session() as session:
                session.add(view)

            # Create ACL entry for the user
            await self.set_acl_permission(
                SubjectType.USER,
                subject_id=user.id,
                resource_type=ResourceType.VIEW,
                resource_id=view.id,
                permission=Permission.ADMIN,
            )

        if view.base_filter is not None:
            assert isinstance(
                view.base_filter, ComplexFilter
            ), f"Base filter must be a ComplexFilter, found {type(view.base_filter)}"

        return ViewContext(
            collection_id=collection_id, view_id=view.id, base_filter=view.base_filter, user=user
        )

    async def set_view_base_filter(self, ctx: ViewContext, filter: ComplexFilter | None):
        # Clear the old base filter
        await self.clear_view_base_filter(ctx)

        # Add the new filter
        if filter is not None:
            async with self.db.session() as session:
                await session.execute(
                    update(SQLAView)
                    .where(SQLAView.id == ctx.view_id)
                    .values(base_filter_dict=filter.model_dump())
                )

        new_ctx = ViewContext(
            collection_id=ctx.collection_id, view_id=ctx.view_id, base_filter=filter, user=ctx.user
        )
        return new_ctx

    async def clear_view_base_filter(self, ctx: ViewContext):
        if ctx.base_filter is not None:
            # Unset the base filter
            async with self.db.session() as session:
                await session.execute(
                    update(SQLAView).where(SQLAView.id == ctx.view_id).values(base_filter_dict=None)
                )

        new_ctx = ViewContext(
            collection_id=ctx.collection_id, view_id=ctx.view_id, base_filter=None, user=ctx.user
        )
        return new_ctx

    ##############
    # Embeddings #
    ##############

    async def _rerank_agent_runs_by_embeddings(
        self,
        ctx: ViewContext,
        agent_runs: list[AgentRun],
        search_query_id: str,
    ) -> list[AgentRun]:
        """
        Rerank agent runs using pgvector cosine distance search if embeddings are available.
        Returns the original agent runs if reranking fails or embeddings are loading.
        """
        return agent_runs

        try:
            search_query = await self.get_search_query(search_query_id)
            query_embeddings, _ = await get_chunked_openai_embeddings_async(
                [search_query.search_query]
            )
        except Exception as e:
            logger.warning(f"Failed to compute embeddings: {e}")
            return agent_runs

        query_embedding = query_embeddings[0]
        async with self.db.session() as session:
            count_query = (
                select(func.count(SQLATranscriptEmbedding.id))
                .join(SQLAAgentRun, SQLATranscriptEmbedding.agent_run_id == SQLAAgentRun.id)
                .where(
                    SQLATranscriptEmbedding.collection_id == ctx.collection_id,
                    ctx.get_base_where_clause(SQLAAgentRun),
                    ~exists().where(
                        SQLASearchResult.agent_run_id == SQLAAgentRun.id,
                        SQLASearchResult.search_query_id == search_query_id,
                    ),
                )
            )

            # Execute count query to get the actual number of embeddings to process
            count_result = await session.execute(count_query)
            embedding_count = count_result.scalar_one()

            query = (
                select(
                    SQLATranscriptEmbedding.agent_run_id,
                )
                .join(SQLAAgentRun, SQLATranscriptEmbedding.agent_run_id == SQLAAgentRun.id)
                .where(
                    SQLATranscriptEmbedding.collection_id == ctx.collection_id,
                    ctx.get_base_where_clause(SQLAAgentRun),
                    ~exists().where(
                        SQLASearchResult.agent_run_id == SQLAAgentRun.id,
                        SQLASearchResult.search_query_id == search_query_id,
                    ),
                )
                .order_by(SQLATranscriptEmbedding.embedding.cosine_distance(query_embedding))
                .limit(embedding_count)
            )

            # Execute the actual query
            result = await session.execute(query)
            ordered_results = result.all()
            ordered_agent_run_ids = [row.agent_run_id for row in ordered_results]

        # Create a mapping of ID to AgentRun for quick lookup
        id_to_agent_run = {ar.id: ar for ar in agent_runs}
        ordered_agent_run_ids = list(dict.fromkeys(ordered_agent_run_ids))
        reranked_agent_runs = [id_to_agent_run[ar_id] for ar_id in ordered_agent_run_ids]

        if len(reranked_agent_runs) != len(agent_runs):
            logger.error(
                f"Reranked to {len(reranked_agent_runs)} agent runs, but expected {len(agent_runs)}"
            )

        logger.info(f"Reranked to {len(reranked_agent_runs)}")

        return reranked_agent_runs

    async def fg_has_embeddings(self, collection_id: str) -> bool:
        """Check if all runs in the current context have embeddings."""
        async with self.db.session() as session:
            # Check if there exists any run without embeddings
            subquery = select(1).where(
                SQLAAgentRun.collection_id == collection_id,
                ~exists().where(SQLATranscriptEmbedding.agent_run_id == SQLAAgentRun.id),
            )

            query = select(~exists(subquery))
            result = await session.execute(query)
            return result.scalar_one()

    async def get_indexing_progress(self, collection_id: str) -> tuple[str | None, int | None]:
        index_name = f"ivfflat_embedding_view_{collection_id.replace('-', '_')}"

        # Filter for a specific index by name
        query = text(
            """
            SELECT
                pci.phase,
                round(100.0 * pci.tuples_done / nullif(pci.tuples_total, 0), 1) AS percent
            FROM pg_stat_progress_create_index pci
            JOIN pg_class pc ON pci.index_relid = pc.oid
            WHERE pc.relname = :index_name
            """
        )

        async with self.db.session() as session:
            result = await session.execute(query, {"index_name": index_name})
            row = result.fetchone()

        if row is None:
            return None, None

        # Handle case where percent is None (can happen when tuples_total is 0)
        percent = row[1]
        return row[0], int(percent) if percent is not None else None

    async def compute_embeddings(
        self, ctx: ViewContext, progress_callback: AsyncEmbeddingStreamingCallback
    ):
        async with self.db.session() as session:
            # Get all agent runs that don't have embeddings in this collection
            query = (
                select(SQLAAgentRun.id)
                .outerjoin(
                    SQLATranscriptEmbedding,
                    (SQLAAgentRun.id == SQLATranscriptEmbedding.agent_run_id)
                    & (SQLATranscriptEmbedding.collection_id == ctx.collection_id),
                )
                .where(SQLATranscriptEmbedding.agent_run_id.is_(None))
            )
            result = await session.execute(query)
            agent_run_ids_without_embeddings = result.scalars().all()

        if len(agent_run_ids_without_embeddings) == 0:
            logger.info("All agent runs already have embeddings")
            return False

        # Use existing get_agent_runs method to fetch full AgentRun objects with transcripts
        agent_runs = await self.get_agent_runs(
            ctx, agent_run_ids=list(agent_run_ids_without_embeddings)
        )

        logger.info(f"Computing embeddings for {len(agent_runs)} agent runs")

        text = [run.text for run in agent_runs]
        try:
            embeddings, chunk_to_doc = await get_chunked_openai_embeddings_async(
                text, dimensions=EMBEDDING_DIM, callback=progress_callback
            )
        except Exception as e:
            # Just skip
            logger.warning(f"Failed to compute embeddings: {e}")
            return False
        embedding_ids = [agent_runs[doc_idx].id for doc_idx in chunk_to_doc]

        async with self.db.session() as session:
            session.add_all(
                [
                    SQLATranscriptEmbedding(
                        id=str(uuid4()),
                        collection_id=ctx.collection_id,
                        agent_run_id=id,
                        embedding=embedding,
                    )
                    for id, embedding in zip(embedding_ids, embeddings)
                ]
            )

        logger.info(f"Pushed {len(embeddings)} embeddings")

        return True

    async def compute_ivfflat_index(
        self,
        ctx: ViewContext,
    ) -> str:
        """Create an IVFFlat index for embeddings of agent runs in the given view context."""
        # Check if embeddings exist for agent runs in this collection
        async with self.db.session() as session:
            count_query = (
                select(func.count(SQLATranscriptEmbedding.id))
                .join(SQLAAgentRun, SQLATranscriptEmbedding.agent_run_id == SQLAAgentRun.id)
                .where(SQLAAgentRun.collection_id == ctx.collection_id)
            )
            result = await session.execute(count_query)
            embedding_count = result.scalar_one()

        if embedding_count == 0:
            raise ValueError(f"No embeddings found for agent runs in view {ctx.view_id}.")

        lists = min(max(100, int(embedding_count**0.5)), 1_000)

        index_name = f"ivfflat_embedding_view_{ctx.collection_id.replace('-', '_')}"

        # Drop existing index within a transaction
        async with self.db.session() as session:
            try:
                await session.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
                logger.info(f"Dropped existing index {index_name}")
            except Exception as e:
                logger.warning(f"Failed to drop existing index {index_name}: {e}")

        # Create index CONCURRENTLY outside of transaction using engine connection
        # CONCURRENTLY cannot be run within a transaction block
        async with self.db.engine.connect() as conn:
            # Set autocommit mode for the connection
            await conn.execution_options(isolation_level="AUTOCOMMIT")

            # Create the IVFFlat index
            # Using cosine distance operator for semantic similarity
            create_index_query = text(
                f"""
                CREATE INDEX CONCURRENTLY {index_name} ON {TABLE_TRANSCRIPT_EMBEDDING}
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = {lists})
                WHERE collection_id = '{ctx.collection_id}'
                """
            )

            logger.info(f"Creating IVFFlat index {index_name} with {lists} lists...")
            await conn.execute(create_index_query)
            logger.info(f"Successfully created IVFFlat index {index_name}")

        return index_name

    async def get_embedding_job_count(
        self, collection_id: str, _where_clause: ColumnElement[bool] | None = None
    ) -> int:
        """
        Count the number of embedding jobs for a collection.

        Args:
            collection_id: The collection ID
            _where_clause: Optional additional filter clause

        Returns:
            The number of embedding jobs matching the criteria
        """
        async with self.db.session() as session:
            query = (
                select(func.count(SQLAJob.id))
                .filter(SQLAJob.type == "compute_embeddings")
                .filter(SQLAJob.job_json["collection_id"].astext == collection_id)
            )
            if _where_clause is not None:
                query = query.filter(_where_clause)

            result = await session.execute(query)
            return result.scalar() or 0

    async def get_oldest_active_embedding_job(self, collection_id: str) -> SQLAJob | None:
        async with self.db.session() as session:
            query = (
                select(SQLAJob)
                .where(
                    SQLAJob.type == "compute_embeddings",
                    SQLAJob.job_json["collection_id"].astext == collection_id,
                    SQLAJob.status == JobStatus.RUNNING,
                )
                .order_by(SQLAJob.created_at.asc())
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    ########
    # Jobs #
    ########

    async def add_job(self, type: str, job_json: dict[str, Any], job_id: str | None = None) -> str:
        """
        Save a job specification to the database.

        Args:
            job_json: The job specification to save.
            job_id: Optional job ID. If None, a new UUID will be generated.

        Returns:
            The job ID.
        """
        job_id = job_id or str(uuid4())
        async with self.db.session() as session:
            session.add(SQLAJob(id=job_id, type=type, created_at=datetime.now(), job_json=job_json))
            logger.info(f"Added job with ID: {job_id}")
        return job_id

    async def add_embedding_job(self, collection_id: str, should_index: bool) -> str:
        """
        Adds or finds an embedding job for the given collection.

        Args:
            should_index: Whether to index the new agent runs
        """
        async with self.db.session() as session:
            job_id = str(uuid4())
            session.add(
                SQLAJob(
                    id=job_id,
                    type="compute_embeddings",
                    job_json={
                        "should_index": should_index,
                        "collection_id": collection_id,
                    },
                )
            )
            logger.info(f"Added embedding job {job_id}")

            return job_id

    async def add_telemetry_processing_job(self, collection_id: str, user: User) -> str | None:
        """
        Adds a telemetry processing job for the given collection.
        Only adds the job if there isn't already a pending job for this collection.

        Args:
            collection_id: The collection ID to process
            user: The user who initiated the processing

        Returns:
            The job ID if created, None if job already exists
        """
        async with self.db.session() as session:
            # Check if there's already a pending job for this collection
            existing_job_query = select(SQLAJob).where(
                SQLAJob.type == "telemetry_processing_job",
                SQLAJob.job_json.contains({"collection_id": collection_id}),
                SQLAJob.status.in_([JobStatus.PENDING]),
            )

            existing_job_result = await session.execute(existing_job_query)
            existing_jobs = existing_job_result.scalars().all()

            if existing_jobs:
                # Log all existing jobs for debugging
                job_ids = [job.id for job in existing_jobs]
                logger.debug(
                    f"Telemetry processing job(s) already exist for collection {collection_id}: {job_ids} (statuses: {[job.status for job in existing_jobs]})"
                )
                return None

            # Create new job with user information
            job_id = str(uuid4())
            session.add(
                SQLAJob(
                    id=job_id,
                    type="telemetry_processing_job",
                    job_json={
                        "collection_id": collection_id,
                        "user_id": user.id,
                        "user_email": user.email,
                        "user_organization_ids": user.organization_ids,
                    },
                )
            )
            logger.info(f"Added telemetry processing job {job_id} for collection {collection_id}")

            return job_id

    async def add_and_enqueue_telemetry_processing_job(
        self, collection_id: str, user: User
    ) -> str | None:
        """
        Adds a telemetry processing job for the given collection and enqueues it to Redis.
        Only adds the job if there isn't already a pending job for this collection.

        Args:
            collection_id: The collection ID to process
            user: The user who initiated the processing

        Returns:
            The job ID if created and enqueued, None if job already exists
        """
        # Create the job in the database
        job_id = await self.add_telemetry_processing_job(collection_id, user)

        if job_id is None:
            return None

        # Create a ViewContext for the collection
        ctx = await self.get_default_view_ctx(collection_id, user)

        # Enqueue the job to Redis
        await enqueue_job(ctx, job_id)  # type: ignore

        logger.info(f"Enqueued telemetry processing job {job_id} for collection {collection_id}")

        return job_id

    async def get_job(self, job_id: str) -> SQLAJob | None:
        """
        Retrieve a job specification from the database.

        Args:
            job_id: The ID of the job to retrieve.

        Returns:
            The job specification as a dictionary, or None if not found.
        """
        async with self.db.session() as session:
            result = await session.execute(select(SQLAJob).where(SQLAJob.id == job_id))
            return result.scalar_one_or_none()

    async def set_job_status(self, job_id: str, status: JobStatus):
        async with self.db.session() as session:
            await session.execute(
                update(SQLAJob).filter(SQLAJob.id == job_id).values(status=status)
            )

    async def set_job_json(self, job_id: str, job_json: dict[str, Any]):
        async with self.db.session() as session:
            await session.execute(
                update(SQLAJob).filter(SQLAJob.id == job_id).values(job_json=job_json)
            )

    #########
    # Users #
    #########

    async def get_users(self) -> list[User]:
        async with self.db.session() as session:
            # Get all users
            users_result = await session.execute(select(SQLAUser))
            sqla_users = users_result.scalars().all()

            return [user.to_user() for user in sqla_users]

    async def create_user(self, email: str, password: str) -> User:
        """
        Create a new user. Raises an error if a user with the given email already exists.

        Args:
            email: The email address of the user
            password: The password for the user

        Returns:
            The User object
        """
        # Check if user already exists
        existing_user = await self.get_user_by_email(email)
        if existing_user:
            raise ValueError("User already exists for {email}")

        user_id = str(uuid4())
        sqla_user = SQLAUser(id=user_id, email=email)
        sqla_user.is_anonymous = False

        sqla_user.password_hash = pwd_context.hash(password)

        async with self.db.session() as session:
            session.add(sqla_user)
            # Call to_user() inside the session context
            user = sqla_user.to_user()

        logger.info(f"Created new user with ID: {sqla_user.id} and email: {sqla_user.email}")
        return user

    async def create_anonymous_user(self) -> User:
        """
        Create an anonymous user that is persisted to the database.

        Returns:
            A User object with anonymous properties
        """
        user_id = str(uuid4())
        email = f"anonymous_{user_id}"

        # Persist anonymous user to database
        async with self.db.session() as session:
            sqla_user = SQLAUser(
                id=user_id, email=email, password_hash="not necessary", is_anonymous=True
            )
            session.add(sqla_user)
            # Call to_user() inside the session context
            user = sqla_user.to_user()

            logger.info(f"Created anonymous user with ID: {user_id}")
            return user

    async def get_user_by_email(self, email: str) -> User | None:
        """
        Retrieve a user by email address.

        Args:
            email: The email address to search for

        Returns:
            The User object if found, None otherwise
        """
        async with self.db.session() as session:
            # Get the user
            result = await session.execute(select(SQLAUser).where(SQLAUser.email == email))
            sqla_user = result.scalar_one_or_none()
            if not sqla_user:
                return None

            return sqla_user.to_user()

    async def verify_user_password(self, email: str, password: str) -> User | None:
        """
        Verify a user's password and return the user if successful.

        Args:
            email: The email address of the user
            password: The password to verify

        Returns:
            The User object if password is correct, None otherwise
        """
        async with self.db.session() as session:
            # Get the user with password fields
            result = await session.execute(select(SQLAUser).where(SQLAUser.email == email))
            sqla_user = result.scalar_one_or_none()
            if not sqla_user:
                return None

            if pwd_context.verify(password, sqla_user.password_hash):
                return sqla_user.to_user()

            return None

    async def create_session(self, user_id: str, expires_in_days: int = 30) -> str:
        """
        Create a new session for a user.

        Args:
            user_id: The user ID to create a session for
            expires_in_days: Number of days until the session expires

        Returns:
            The session ID
        """

        session_id = str(uuid4())
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=expires_in_days)

        async with self.db.session() as session:
            session.add(
                SQLASession(
                    id=session_id,
                    user_id=user_id,
                    expires_at=expires_at,
                    is_active=True,
                )
            )
        logger.info(f"Created session {session_id} for user {user_id}")
        return session_id

    async def get_user_by_session_id(self, session_id: str) -> User | None:
        """
        Retrieve a user by their session ID.

        Args:
            session_id: The session ID to look up

        Returns:
            The User object if the session is valid and active, None otherwise
        """
        async with self.db.session() as session:
            # Join session and user tables, check if session is active and not expired
            result = await session.execute(
                select(SQLAUser)
                .join(SQLASession, SQLAUser.id == SQLASession.user_id)
                .where(
                    SQLASession.id == session_id,
                    SQLASession.is_active,
                    SQLASession.expires_at > datetime.now(UTC).replace(tzinfo=None),
                )
            )
            sqla_user = result.scalar_one_or_none()
            if not sqla_user:
                return None

            return sqla_user.to_user()

    async def invalidate_session(self, session_id: str) -> bool:
        """
        Invalidate a session by marking it as inactive.

        Args:
            session_id: The session ID to invalidate

        Returns:
            True if the session was found and invalidated, False otherwise
        """
        async with self.db.session() as session:
            result = await session.execute(
                update(SQLASession).where(SQLASession.id == session_id).values(is_active=False)
            )
            return result.rowcount > 0

    ###############
    # Permissions #
    ###############

    async def has_permission(
        self,
        user: User,
        resource_type: ResourceType,
        resource_id: str,
        permission: Permission,
    ) -> bool:
        user_permission_level = await self.get_permission_level(user, resource_type, resource_id)
        if user_permission_level is None:
            return False
        return user_permission_level.includes(permission)

    async def get_acl_entries(
        self,
        resource_id: str,
        resource_type: ResourceType,
    ) -> list[SQLAAccessControlEntry]:
        if resource_type == ResourceType.COLLECTION:
            resource_filter = SQLAAccessControlEntry.collection_id == resource_id
        elif resource_type == ResourceType.VIEW:
            resource_filter = SQLAAccessControlEntry.view_id == resource_id
        else:
            raise ValueError(f"Unsupported resource type: {resource_type}")
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAAccessControlEntry)
                .options(selectinload(SQLAAccessControlEntry.user))
                .options(selectinload(SQLAAccessControlEntry.organization))
                .where(resource_filter)
            )
            return [acl for acl in result.scalars().all()]

    async def get_permission_level(
        self,
        user: User,
        resource_type: ResourceType,
        resource_id: str,
    ) -> Permission | None:
        """Get the highest permission level a user has for a resource."""

        # Build the resource filter based on ResourceType
        if resource_type == ResourceType.COLLECTION:
            resource_filter = SQLAAccessControlEntry.collection_id == resource_id
        elif resource_type == ResourceType.VIEW:
            resource_filter = SQLAAccessControlEntry.view_id == resource_id
        else:
            raise ValueError(f"Unsupported resource type: {resource_type}")

        all_perm_strs: list[str] = []

        async with self.db.session() as session:
            # Check public permissions
            public_permission_result = await session.execute(
                select(SQLAAccessControlEntry.permission).where(
                    SQLAAccessControlEntry.is_public,
                    resource_filter,
                )
            )
            all_perm_strs.extend(public_permission_result.scalars().all())

            # Check direct user permissions
            direct_permission_result = await session.execute(
                select(SQLAAccessControlEntry.permission).where(
                    SQLAAccessControlEntry.user_id == user.id,
                    resource_filter,
                )
            )
            all_perm_strs.extend(direct_permission_result.scalars().all())

            # Check organization permissions for all user's organizations
            if user.organization_ids:
                org_permission_result = await session.execute(
                    select(SQLAAccessControlEntry.permission).where(
                        SQLAAccessControlEntry.organization_id.in_(user.organization_ids),
                        resource_filter,
                    )
                )
                all_perm_strs.extend(org_permission_result.scalars().all())

        # Return the highest permission level
        if not all_perm_strs:
            return None
        return Permission(max(all_perm_strs, key=lambda p: PERMISSION_LEVELS[p]))

    async def set_acl_permission(
        self,
        subject_type: SubjectType,
        subject_id: str | None,
        resource_type: ResourceType,
        resource_id: str,
        permission: Permission,
    ):
        async with self.db.session() as session:
            # Build the resource filter based on ResourceType
            if resource_type == ResourceType.COLLECTION:
                resource_filter = SQLAAccessControlEntry.collection_id == resource_id
                resource_fields = {"collection_id": resource_id, "view_id": None}
            elif resource_type == ResourceType.VIEW:
                resource_filter = SQLAAccessControlEntry.view_id == resource_id
                resource_fields = {"collection_id": None, "view_id": resource_id}
            else:
                raise ValueError(f"Unsupported resource type: {resource_type}")

            # Build the subject filter and fields based on SubjectType
            if subject_type == SubjectType.USER:
                subject_filter = SQLAAccessControlEntry.user_id == subject_id
                subject_fields = {
                    "user_id": subject_id,
                    "organization_id": None,
                    "is_public": False,
                }
            elif subject_type == SubjectType.ORGANIZATION:
                subject_filter = SQLAAccessControlEntry.organization_id == subject_id
                subject_fields = {
                    "user_id": None,
                    "organization_id": subject_id,
                    "is_public": False,
                }
            elif subject_type == SubjectType.PUBLIC:
                subject_filter = SQLAAccessControlEntry.is_public
                subject_fields = {"user_id": None, "organization_id": None, "is_public": True}

            # Check if any permission already exists for this subject/resource combination
            result = await session.execute(
                select(SQLAAccessControlEntry).where(
                    subject_filter,
                    resource_filter,
                )
            )
            acl_entry = result.scalar_one_or_none()

            # Permission doesn't exist, create it
            if acl_entry is None:
                acl_entry = SQLAAccessControlEntry(
                    id=str(uuid4()),
                )

                session.add(acl_entry)
            print("SUBJECT_FIELDS", subject_fields)
            print("RESOURCE_FIELDS", resource_fields)
            # Set the fields
            for field, value in subject_fields.items():
                setattr(acl_entry, field, value)
            for field, value in resource_fields.items():
                setattr(acl_entry, field, value)
            acl_entry.permission = permission.value

            logger.info(
                f"Granted {permission.value} permission on {resource_type.value}:{resource_id} "
                f"for {subject_type.value}:{subject_id}"
            )

    async def clear_acl_permission(
        self,
        subject_type: SubjectType,
        subject_id: str,
        resource_type: ResourceType,
        resource_id: str,
    ) -> int:
        async with self.db.session() as session:
            # Build the delete query with the provided filters
            query = delete(SQLAAccessControlEntry)

            # Handle subject filtering based on SubjectType
            if subject_type == SubjectType.USER:
                query = query.where(SQLAAccessControlEntry.user_id == subject_id)
            elif subject_type == SubjectType.ORGANIZATION:
                query = query.where(SQLAAccessControlEntry.organization_id == subject_id)
            elif subject_type == SubjectType.PUBLIC:
                query = query.where(SQLAAccessControlEntry.is_public)
            else:
                raise ValueError(f"Unsupported subject type: {subject_type}")

            # Handle resource filtering based on ResourceType
            if resource_type == ResourceType.COLLECTION:
                query = query.where(SQLAAccessControlEntry.collection_id == resource_id)
            elif resource_type == ResourceType.VIEW:
                query = query.where(SQLAAccessControlEntry.view_id == resource_id)
            else:
                raise ValueError(f"Unsupported resource type: {resource_type}")

            result = await session.execute(query)
            count = result.rowcount or 0

            if count > 0:
                logger.info(
                    f"Cleared {count} ACL permissions with filters: "
                    f"subject_type={subject_type}, subject_id={subject_id}, "
                    f"resource_type={resource_type}, resource_id={resource_id}"
                )
            else:
                logger.info("No ACL permissions matched the provided filters")

            return count

    ###########
    # Locking #
    ###########

    @asynccontextmanager
    async def advisory_lock(self, collection_id: str, action_id: str) -> AsyncIterator[None]:
        """Acquires a PostgreSQL advisory lock for the given Collection ID and action ID.

        This provides a concurrency safety mechanism that can prevent race conditions
        when multiple processes or tasks attempt to modify the same Collection data.

        Args:
            collection_id: The Collection ID to lock
            action_id: An identifier for the action being performed

        Example:
            ```python
            async with db_service.advisory_lock(collection_id, "compute_filter"):
                # This code is protected by the lock
                await db_service.compute_filter(collection_id, filter_id)
            ```
        """
        # Create integer keys from the string IDs using hash functions
        # We use two separate hashing algorithms to minimize collision risk
        fg_hash = int(hashlib.md5(collection_id.encode()).hexdigest(), 16) % (2**31 - 1)
        action_hash = int(hashlib.sha1(action_id.encode()).hexdigest(), 16) % (2**31 - 1)

        async with self.db.engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")

            try:
                # Acquire the advisory lock
                await conn.execute(
                    text("SELECT pg_advisory_lock(:key1, :key2)"),
                    {"key1": fg_hash, "key2": action_hash},
                )
                logger.info(f"Acquired advisory lock for {collection_id}/{action_id}")

                # Yield control back to the caller
                yield
            finally:
                # Always release the lock, even if an exception occurs
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:key1, :key2)"),
                    {"key1": fg_hash, "key2": action_hash},
                )
                logger.info(f"Released advisory lock for {collection_id}/{action_id}")

    def _create_fingerprint(self, raw_api_key: str) -> str:
        """Create a deterministic fingerprint for a key using HMAC-SHA256."""
        import hashlib
        import hmac

        key = b"04142e6e-b7c7-46c6-a1f3-5c044a7c31e4"
        return hmac.new(key, raw_api_key.encode("utf-8"), hashlib.sha256).hexdigest()

    async def create_api_key(self, user_id: str, name: str) -> tuple[str, str]:
        """
        Create a new API key for a user.


        Returns:
            tuple: (api_key_id, raw_api_key) - raw key should be shown to user once
        """
        import secrets
        import string

        alphabet = string.ascii_letters + string.digits
        key_id = "".join(secrets.choice(alphabet) for _ in range(16))
        secret = "".join(secrets.choice(alphabet) for _ in range(46))
        raw_api_key = f"dk_{key_id}_{secret}"

        # Create Argon2 hash for key verification
        key_hash = pwd_context.hash(raw_api_key)
        api_key_id = str(uuid4())

        async with self.db.session() as session:
            api_key = SQLAApiKey(
                id=api_key_id,
                user_id=user_id,
                name=name,
                key_id=key_id,
                key_hash=key_hash,
            )
            session.add(api_key)
            await session.commit()

        logger.info(f"Created API key id:{api_key_id} for user {user_id}")
        return api_key_id, raw_api_key

    async def get_user_api_keys(self, user_id: str) -> list[SQLAApiKey]:
        """Get all API keys for a user."""
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAApiKey)
                .where(SQLAApiKey.user_id == user_id)
                .order_by(SQLAApiKey.created_at.desc())
            )
            return list(result.scalars().all())

    async def disable_api_key(self, api_key_id: str, user_id: str) -> bool:
        """Disable an API key. Returns True if key was found and disabled."""
        async with self.db.session() as session:
            result = await session.execute(
                update(SQLAApiKey)
                .where(SQLAApiKey.id == api_key_id, SQLAApiKey.user_id == user_id)
                .values(disabled_at=datetime.now(UTC).replace(tzinfo=None))
            )
            return result.rowcount > 0

    async def get_user_by_api_key(self, raw_api_key: str) -> User | None:
        """
        Validate an API key and return the associated user.
        Updates last_used_at timestamp if key is valid.

        Supports both new key_id pattern and legacy Argon2 hashes for migration.
        """
        if not raw_api_key.startswith("dk_"):
            return None

        async with self.db.session() as session:
            # Parse key_id from API key format: dk_{key_id}_{secret}
            key_id = None
            api_key_data = None
            parts = raw_api_key.split("_", 2)
            if len(parts) == 3:
                key_id = parts[1]

            if key_id:
                # Try new key_id pattern first
                result = await session.execute(
                    select(SQLAApiKey)
                    .options(selectinload(SQLAApiKey.user))
                    .where(
                        SQLAApiKey.key_id == key_id,
                        SQLAApiKey.disabled_at.is_(None),  # type: ignore
                    )
                )
                api_key_data = result.scalar_one_or_none()

            # If key_id lookup failed, try fingerprint lookup for legacy keys
            if not api_key_data:
                fingerprint = self._create_fingerprint(raw_api_key)
                result = await session.execute(
                    select(SQLAApiKey)
                    .options(selectinload(SQLAApiKey.user))
                    .where(
                        SQLAApiKey.fingerprint == fingerprint,
                        SQLAApiKey.disabled_at.is_(None),  # type: ignore
                    )
                )
                api_key_data = result.scalar_one_or_none()

            # if either key_id or fingerprint is found, we can verify the key
            if api_key_data and api_key_data.key_hash:
                # Verify the raw key against Argon2 hash
                if pwd_context.verify(raw_api_key, api_key_data.key_hash):
                    await session.execute(
                        update(SQLAApiKey)
                        .where(SQLAApiKey.id == api_key_data.id)
                        .values(last_used_at=datetime.now(UTC).replace(tzinfo=None))
                    )
                    return api_key_data.user.to_user()

            # Final fallback: Argon2-only verification for keys without fingerprint (legacy keys)
            result = await session.execute(
                select(SQLAApiKey)
                .options(selectinload(SQLAApiKey.user))
                .where(
                    SQLAApiKey.disabled_at.is_(None),  # type: ignore
                    SQLAApiKey.key_id.is_(None),  # Only keys without key_id
                    SQLAApiKey.fingerprint.is_(None),  # Only keys without fingerprint
                )
            )

            for api_key_data in result.scalars().all():
                if api_key_data.key_hash and pwd_context.verify(raw_api_key, api_key_data.key_hash):
                    # Backfill fingerprint for legacy key on first successful use
                    fingerprint = self._create_fingerprint(raw_api_key)
                    await session.execute(
                        update(SQLAApiKey)
                        .where(SQLAApiKey.id == api_key_data.id)
                        .values(
                            fingerprint=fingerprint,
                            last_used_at=datetime.now(UTC).replace(tzinfo=None),
                        )
                    )
                    logger.info(f"Backfilled fingerprint for legacy API key {api_key_data.id}")
                    return api_key_data.user.to_user()

            return None

    async def get_api_key_overrides(self, user: User | None) -> dict[str, str]:
        """Return a dictionary of API key overrides for a user."""
        if user is None:
            return {}
        if user.is_anonymous:
            return {}

        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAModelApiKey.provider, SQLAModelApiKey.api_key).where(
                    SQLAModelApiKey.user_id == user.id
                )
            )
            return {row[0]: row[1] for row in result.all()}

    async def get_model_api_keys(self, user_id: str) -> list[SQLAModelApiKey]:
        """Get all model API keys for a user."""
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAModelApiKey).where(SQLAModelApiKey.user_id == user_id)
            )
            return list(result.scalars().all())

    async def upsert_model_api_key(
        self, user_id: str, provider: str, api_key: str
    ) -> SQLAModelApiKey:
        """Create or update a model API key for a user and provider."""
        async with self.db.session() as session:
            # Check if key already exists for this user and provider
            result = await session.execute(
                select(SQLAModelApiKey).where(
                    SQLAModelApiKey.user_id == user_id, SQLAModelApiKey.provider == provider
                )
            )
            existing_key = result.scalar_one_or_none()

            if existing_key:
                # Update existing key
                existing_key.api_key = api_key
                await session.commit()
                return existing_key
            else:
                # Create new key
                new_key = SQLAModelApiKey(user_id=user_id, provider=provider, api_key=api_key)
                session.add(new_key)
                await session.commit()
                await session.refresh(new_key)
                return new_key

    async def delete_model_api_key(self, user_id: str, provider: str) -> bool:
        """Delete a model API key for a user and provider. Returns True if deleted, False if not found."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(SQLAModelApiKey).where(
                    SQLAModelApiKey.user_id == user_id, SQLAModelApiKey.provider == provider
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def get_agent_run_metadata_fields(self, ctx: ViewContext) -> list[FilterableField]:
        """
        Get all metadata fields from agent runs that can be used for filtering.

        Args:
            ctx: View context

        Returns:
            List of all filterable fields
        """
        where_clause = ctx.get_base_where_clause(SQLAAgentRun)

        metadata_prefix = array([literal("metadata")])

        base_lateral = lateral(
            func.jsonb_each(SQLAAgentRun.metadata_json).table_valued("key", "value")
        ).alias("metadata_pairs")

        json_paths = (
            select(
                func.array_append(metadata_prefix, base_lateral.c.key).label("path_arr"),
                base_lateral.c.value.label("value"),
                SQLAAgentRun.id.label("agent_run_id"),
                literal(1).label("depth"),
            )
            .select_from(SQLAAgentRun)
            .join(base_lateral, true())
            .where(where_clause)
            .where(func.jsonb_typeof(SQLAAgentRun.metadata_json) == "object")
        ).cte("json_paths", recursive=True)

        nested_lateral = lateral(
            func.jsonb_each(json_paths.c.value).table_valued("key", "value")
        ).alias("nested_pairs")

        json_paths = json_paths.union_all(
            select(
                func.array_append(json_paths.c.path_arr, nested_lateral.c.key).label("path_arr"),
                nested_lateral.c.value.label("value"),
                json_paths.c.agent_run_id,
                (json_paths.c.depth + 1).label("depth"),
            )
            .join(nested_lateral, true())
            .where(func.jsonb_typeof(json_paths.c.value) == "object")
            .where(json_paths.c.depth < bindparam("max_depth"))
        )

        scalar_json_types = ("string", "number", "boolean")

        scalar_leaves = (
            select(
                json_paths.c.path_arr.label("path_arr"),
                json_paths.c.value.label("value"),
                json_paths.c.agent_run_id.label("agent_run_id"),
            ).where(func.jsonb_typeof(json_paths.c.value).in_(scalar_json_types))
        ).subquery()

        metadata_query = (
            select(
                func.array_to_string(scalar_leaves.c.path_arr, ".").label("path"),
                scalar_leaves.c.value,
            )
            .distinct(scalar_leaves.c.path_arr)
            .order_by(scalar_leaves.c.path_arr, scalar_leaves.c.agent_run_id)
        )

        def _infer_filter_type(value: Any) -> Literal["str", "bool", "int", "float"] | None:
            if isinstance(value, bool):
                return "bool"
            if isinstance(value, int):
                return "int"
            if isinstance(value, float):
                return "float"
            if isinstance(value, Decimal):
                if value == value.to_integral_value():
                    return "int"
                return "float"
            if isinstance(value, str):
                return "str"
            return None

        all_fields: dict[str, FilterableField] = {}

        async with self.db.session() as session:
            result = await session.execute(metadata_query, {"max_depth": 2})
            for row in result:
                field_type = _infer_filter_type(row.value)
                if field_type is None:
                    continue
                all_fields[row.path] = {"name": row.path, "type": field_type}

        all_fields["text"] = {"name": "text", "type": "str"}

        return sorted(all_fields.values(), key=lambda f: f["name"])


def sort_transcript_groups_by_parent_order(
    transcript_group_data: list[SQLATranscriptGroup],
) -> list[SQLATranscriptGroup]:
    """
    Sort transcript groups so that parent groups come before their children.
    This ensures that foreign key constraints are satisfied when saving to the database.

    Args:
        transcript_group_data: List of SQLATranscriptGroup objects to sort

    Returns:
        Sorted list of SQLATranscriptGroup objects with parents before children
    """
    # Create a mapping of group ID to group object
    group_map = {group.id: group for group in transcript_group_data}

    # Create a mapping of parent ID to list of child IDs
    parent_to_children: dict[str, list[str]] = {}
    for group in transcript_group_data:
        if group.parent_transcript_group_id:
            if group.parent_transcript_group_id not in parent_to_children:
                parent_to_children[group.parent_transcript_group_id] = []
            parent_to_children[group.parent_transcript_group_id].append(group.id)

    # Topological sort: start with groups that have no parents
    sorted_groups: list[SQLATranscriptGroup] = []
    visited: set[str] = set()

    def visit(group_id: str) -> None:
        if group_id in visited:
            return
        visited.add(group_id)

        # Add this group to the sorted list first (parents before children)
        if group_id in group_map:
            sorted_groups.append(group_map[group_id])

        # Then visit all children
        if group_id in parent_to_children:
            for child_id in parent_to_children[group_id]:
                if child_id in group_map:  # Only visit if child is in our data
                    visit(child_id)

    # Visit all groups that have no parents first
    for group in transcript_group_data:
        if not group.parent_transcript_group_id:
            visit(group.id)

    # Visit any remaining groups (shouldn't happen in a valid tree, but just in case)
    for group in transcript_group_data:
        if group.id not in visited:
            visit(group.id)

    return sorted_groups
