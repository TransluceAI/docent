from __future__ import annotations

import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import (
    Any,
    AsyncIterator,
    ParamSpec,
    Sequence,
    TypeVar,
    cast,
)
from uuid import uuid4

import anyio
from passlib.context import CryptContext
from sqlalchemy import (
    ColumnElement,
    delete,
    distinct,
    exists,
    func,
    select,
    text,
    update,
)
from sqlalchemy.orm import selectinload

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.transcript import Transcript
from docent_core._ai_tools.clustering.cluster_assigner import (
    DEFAULT_ASSIGNER,
    assign_with_backend,
)
from docent_core._ai_tools.clustering.cluster_generator import (
    ClusterFeedback,
    propose_clusters,
)
from docent_core._ai_tools.search import (
    SearchResult,
    SearchResultStreamingCallback,
    execute_search,
)
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.db import DocentDB
from docent_core._db_service.filters import ComplexFilter
from docent_core._db_service.schemas.auth_models import (
    PERMISSION_LEVELS,
    Permission,
    ResourceType,
    SubjectType,
    User,
)
from docent_core._db_service.schemas.chart import SQLAChart
from docent_core._db_service.schemas.tables import (
    EMBEDDING_DIM,
    TABLE_TRANSCRIPT_EMBEDDING,
    JobStatus,
    SQLAAccessControlEntry,
    SQLAAgentRun,
    SQLAAnalyticsEvent,
    SQLAApiKey,
    SQLAChatSession,
    SQLACollection,
    SQLAJob,
    SQLASearchCluster,
    SQLASearchQuery,
    SQLASearchResult,
    SQLASearchResultCluster,
    SQLASession,
    SQLATelemetryLog,
    SQLATranscript,
    SQLATranscriptEmbedding,
    SQLAUser,
    SQLAView,
)
from docent_core._llm_util.data_models.llm_output import AsyncEmbeddingStreamingCallback
from docent_core._llm_util.providers.openai import get_chunked_openai_embeddings_async
from docent_core._server._broker.redis_client import enqueue_embedding_job

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

        # Delete all agent runs
        async with self.db.session() as session:
            await session.execute(
                delete(SQLAAgentRun).where(SQLAAgentRun.collection_id == collection_id)
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

    ##############
    # Agent Runs #
    ##############

    async def add_agent_runs(self, ctx: ViewContext, agent_runs: Sequence[AgentRun]):
        # Convert AgentRun objects to SQLAlchemy objects using existing conversion functions
        agent_run_data: list[SQLAAgentRun] = []
        transcript_data: list[SQLATranscript] = []

        # count the number of agent runs in the current collection
        async with self.db.session() as session:
            query = select(func.count()).where(SQLAAgentRun.collection_id == ctx.collection_id)
            result = await session.execute(query)
            num_agent_runs = result.scalar_one()
        if num_agent_runs + len(agent_runs) > 100_000:
            raise ValueError("Number of agent runs in the current collection is too large")

        # Process all agent runs and transcripts first
        for ar in agent_runs:
            # Use the existing from_agent_run method to get all fields properly
            sqla_agent_run = SQLAAgentRun.from_agent_run(ar, ctx.collection_id)
            agent_run_data.append(sqla_agent_run)

            # Process transcripts for this agent run
            for dk, t in ar.transcripts.items():
                # Use the existing from_transcript method to get all fields properly
                sqla_transcript = SQLATranscript.from_transcript(t, dk, ctx.collection_id, ar.id)
                transcript_data.append(sqla_transcript)

        # Insert all agent runs
        async with self.db.session() as session:
            for sqla_agent_run in agent_run_data:
                session.add(sqla_agent_run)

        # Insert all transcripts
        async with self.db.session() as session:
            for sqla_transcript in transcript_data:
                session.add(sqla_transcript)

        logger.info(f"Inserted {len(agent_runs)} agent runs and {len(transcript_data)} transcripts")

    async def update_agent_runs(self, ctx: ViewContext, agent_runs: Sequence[AgentRun]):
        """
        Update agent runs - create if they don't exist, update if they do exist.
        For transcripts, delete existing ones and recreate them.
        """
        # Convert AgentRun objects to SQLAlchemy objects using existing conversion functions
        agent_run_data: list[SQLAAgentRun] = []
        transcript_data: list[SQLATranscript] = []
        agent_run_ids = [ar.id for ar in agent_runs]

        # Check collection size limit
        async with self.db.session() as session:
            query = select(func.count()).where(SQLAAgentRun.collection_id == ctx.collection_id)
            result = await session.execute(query)
            existing_count = result.scalar_one()

            # Count how many new agent runs we'll be adding (not updating)
            existing_agent_run_query = select(SQLAAgentRun.id).where(
                SQLAAgentRun.collection_id == ctx.collection_id, SQLAAgentRun.id.in_(agent_run_ids)
            )
            existing_agent_run_result = await session.execute(existing_agent_run_query)
            existing_agent_run_ids = set(existing_agent_run_result.scalars().all())
            new_agent_run_count = len(agent_run_ids) - len(existing_agent_run_ids)

            if existing_count + new_agent_run_count > 100_000:
                raise ValueError("Number of agent runs in the current collection is too large")

        # Process all agent runs and transcripts first
        for ar in agent_runs:
            # Use the existing from_agent_run method to get all fields properly
            sqla_agent_run = SQLAAgentRun.from_agent_run(ar, ctx.collection_id)
            agent_run_data.append(sqla_agent_run)

            # Process transcripts for this agent run
            for dk, t in ar.transcripts.items():
                # Use the existing from_transcript method to get all fields properly
                sqla_transcript = SQLATranscript.from_transcript(t, dk, ctx.collection_id, ar.id)
                transcript_data.append(sqla_transcript)

        # Handle agent runs - upsert (insert or update)
        async with self.db.session() as session:
            for sqla_agent_run in agent_run_data:
                # Use merge to handle both insert and update
                await session.merge(sqla_agent_run)

        # Handle transcripts - delete existing and recreate
        async with self.db.session() as session:
            # Delete existing transcripts for these agent runs
            delete_transcript_query = delete(SQLATranscript).where(
                SQLATranscript.agent_run_id.in_(agent_run_ids)
            )
            await session.execute(delete_transcript_query)

            # Insert new transcripts
            for sqla_transcript in transcript_data:
                session.add(sqla_transcript)

        logger.info(f"Updated {len(agent_runs)} agent runs and {len(transcript_data)} transcripts")

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
            await enqueue_embedding_job(ctx, job_id)  # type: ignore

            logger.info(f"Enqueued embedding job {job_id} for collection {collection_id}")

    async def get_agent_run_ids(self, ctx: ViewContext) -> list[str]:
        """
        Get agent run IDs for a given Collection ID without fetching transcripts.
        This is more efficient than get_agent_runs when you only need the IDs.
        """
        async with self.db.session() as session:
            query = select(SQLAAgentRun.id).where(ctx.get_base_where_clause(SQLAAgentRun))
            result = await session.execute(query)
            agent_run_ids = result.scalars().all()
            logger.info(f"get_agent_run_ids: Found {len(agent_run_ids)} agent run IDs")
            return list(agent_run_ids)

    async def get_agent_runs(
        self,
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

        # Collate run_id -> transcripts
        agent_run_transcripts: dict[str, list[tuple[str, Transcript]]] = {}
        for t_raw in transcripts_raw:
            agent_run_transcripts.setdefault(t_raw.agent_run_id, []).append(
                t_raw.to_dict_key_and_transcript()
            )

        final_result = [
            ar_raw.to_agent_run(
                transcripts={dk: t for dk, t in agent_run_transcripts.get(ar_raw.id, [])}
            )
            for ar_raw in agent_runs_raw
        ]

        return final_result

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

    async def get_any_agent_run(self, ctx: ViewContext) -> AgentRun | None:
        """
        Get an arbitrary AgentRun from the database for a given Collection ID.
        """
        agent_runs = await self.get_agent_runs(ctx, _limit=1)
        return agent_runs[0] if agent_runs else None

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

    async def clone_view_for_sharing(self, ctx: ViewContext):
        async with self.db.session() as session:
            result = await session.execute(select(SQLAView).where(SQLAView.id == ctx.view_id))
            view = result.scalar_one()
            new_view = SQLAView(
                id=str(uuid4()),
                collection_id=view.collection_id,
                user_id=view.user_id,
                base_filter_dict=view.base_filter_dict,
                inner_bin_key=view.inner_bin_key,
                outer_bin_key=view.outer_bin_key,
                for_sharing=True,
            )
            session.add(new_view)

        return new_view.id

    async def get_view(self, view_id: str) -> SQLAView:
        async with self.db.session() as session:
            result = await session.execute(select(SQLAView).where(SQLAView.id == view_id))
            return result.scalar_one()

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

    ###########
    # Filters #
    ###########

    async def get_search_query_by_query(
        self, collection_id: str, search_query: str
    ) -> SQLASearchQuery | None:
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLASearchQuery).where(
                    SQLASearchQuery.collection_id == collection_id,
                    SQLASearchQuery.search_query == search_query,
                )
            )
            return result.scalar_one_or_none()

    async def get_search_query(self, query_id: str) -> SQLASearchQuery:
        async with self.db.session() as session:
            # Check if the search query already exists for this collection
            result = await session.execute(
                select(SQLASearchQuery).where(SQLASearchQuery.id == query_id)
            )
            return result.scalar_one()

    async def delete_search_query(self, collection_id: str, search_query_id: str):
        """
        Delete a search query from the database.

        Args:
            search_query_id: The ID of the search query to delete

        Returns:
            True if the search query was found and deleted, False otherwise
        """
        async with self.db.session() as session:
            # Get the search query object
            search_query_obj = await session.execute(
                select(SQLASearchQuery).where(SQLASearchQuery.id == search_query_id)
            )
            search_query_obj = search_query_obj.scalar_one_or_none()
            if search_query_obj is None:
                return False

            # Delete all search result cluster assignments that reference search results with this query
            await session.execute(
                delete(SQLASearchResultCluster).where(
                    SQLASearchResultCluster.search_result_id.in_(
                        select(SQLASearchResult.id).where(
                            SQLASearchResult.search_query_id == search_query_id
                        )
                    )
                )
            )

            # Delete all clusters for this search query
            await session.execute(
                delete(SQLASearchCluster).where(
                    SQLASearchCluster.collection_id == collection_id,
                    SQLASearchCluster.search_query_id == search_query_id,
                )
            )

            # Delete search results
            await session.execute(
                delete(SQLASearchResult).where(SQLASearchResult.search_query_id == search_query_id)
            )

            # Delete the search query itself
            await session.execute(
                delete(SQLASearchQuery).where(SQLASearchQuery.id == search_query_id)
            )
            return True

    async def get_searches_with_result_counts(self, ctx: ViewContext) -> list[dict[str, Any]]:
        # Get search result queries
        async with self.db.session() as session:
            query = select(SQLASearchQuery.id, SQLASearchQuery.search_query).where(
                SQLASearchQuery.collection_id == ctx.collection_id
            )
            result = await session.execute(query)
            search_ids_and_queries = result.all()

        # Consolidate set of search queries
        for _, query in search_ids_and_queries:
            assert query is not None, "We filtered out null search queries, this should not happen"
        search_queries = list(set(cast(str, query) for _, query in search_ids_and_queries))

        # Get counts of agent runs that these search queries have been run against
        async with self.db.session() as session:
            query = (
                select(
                    SQLASearchResult.search_query_id,
                    func.count(distinct(SQLASearchResult.agent_run_id)),
                )
                .where(SQLASearchResult.search_query_id.in_(search_queries))
                .join(SQLAAgentRun, SQLASearchResult.agent_run_id == SQLAAgentRun.id)
                .where(
                    ctx.get_base_where_clause(SQLAAgentRun),
                )
                .group_by(SQLASearchResult.search_query_id)
            )
            result = await session.execute(query)

        latest_jobs: dict[str, SQLASearchQuery] = {
            query.id: job for job, query in await self.list_search_jobs_and_queries()
        }

        # Return search queries with judgment counts
        counts = {query: count for query, count in result.all()}
        num_total = await self.count_base_agent_runs(ctx)
        searches = [
            {
                "search_id": search_id,
                "search_query": search_query,
                "num_judgments_computed": counts.get(search_query, 0),
                "num_total": num_total,
                "job": latest_jobs[search_id],
            }
            for search_id, search_query in search_ids_and_queries
        ]
        searches.sort(key=lambda x: cast(SQLASearchQuery, x["job"]).created_at, reverse=True)
        return searches

    async def _get_agent_runs_without_search_results(
        self, ctx: ViewContext, search_query_id: str
    ) -> list[AgentRun]:
        where_clause = ~exists().where(
            SQLASearchResult.agent_run_id == SQLAAgentRun.id,
            SQLASearchResult.search_query_id == search_query_id,
        )
        return await self.get_agent_runs(ctx, _where_clause=where_clause)

    async def get_search_results(
        self,
        ctx: ViewContext,
        search_query_id: str,
    ) -> list[SearchResult]:
        return await self._get_search_results(ctx, search_query_id, ensure_fresh=False)

    async def _get_search_results(
        self,
        ctx: ViewContext,
        search_query_id: str,
        search_result_callback: SearchResultStreamingCallback | None = None,
        ensure_fresh: bool = True,
    ) -> list[SearchResult]:
        # Ensure we have fresh search results
        if ensure_fresh:
            await self.compute_search(
                ctx,
                search_query_id,
                search_result_callback=search_result_callback,
            )

        async with self.db.session() as session:
            query = (
                select(SQLASearchResult)
                .where(SQLASearchResult.search_query_id == search_query_id)
                .join(SQLAAgentRun, SQLASearchResult.agent_run_id == SQLAAgentRun.id)
                .where(ctx.get_base_where_clause(SQLAAgentRun))
            )

            result = await session.execute(query)
            return [a.to_search_result() for a in result.scalars().all()]

    async def compute_search(
        self,
        ctx: ViewContext,
        search_query_id: str,
        search_result_callback: SearchResultStreamingCallback | None = None,
        read_only: bool = False,
    ):
        """If read_only, only return existing results."""

        # If the callback is set, the caller is expecting all results to be streamed back
        # So, retrieve them and send them
        if search_result_callback is not None:
            existing_search_results = await self._get_search_results(
                ctx, search_query_id, ensure_fresh=False
            )
            if existing_search_results:
                await search_result_callback(existing_search_results)

        # Figure out which runs don't have search results computed
        agent_runs = await self._get_agent_runs_without_search_results(ctx, search_query_id)
        if not agent_runs:
            logger.info(f"All agent runs already have results for {search_query_id}")
            return
        else:
            logger.info(f"Computing results for {len(agent_runs)} agent runs")

        if await self.fg_has_embeddings(ctx.collection_id):
            agent_runs = await self._rerank_agent_runs_by_embeddings(
                ctx, agent_runs, search_query_id
            )

        async def _results_callback(search_results: list[SearchResult] | None):
            if search_result_callback:
                await search_result_callback(search_results)

            with anyio.CancelScope(shield=True):
                if search_results is None:
                    return
                to_upload: list[SQLASearchResult] = [
                    SQLASearchResult.from_search_result(
                        search_result=attr,
                        collection_id=ctx.collection_id,
                    )
                    for attr in search_results
                ]
                async with self.db.session() as session:
                    session.add_all(to_upload)

                logger.info(f"Pushed {len(to_upload)} attributes")

        # Early exit if we're not allowed to write
        if read_only:
            return
        # Otherwise, compute the search results
        search_query = await self.get_search_query(search_query_id)
        await execute_search(
            agent_runs,
            search_query_id,
            search_query.search_query,
            search_result_callback=_results_callback,
        )

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

    #########################################
    # Computing filters and clustering dims #
    #########################################

    async def cluster_search_results(
        self,
        ctx: ViewContext,
        search_query_id: str,
        feedback: str | None = None,
        existing_clusters: list[dict[str, Any]] | None = None,
    ):
        """Cluster search results and store cluster information with the search results."""
        search_query = await self.get_search_query(search_query_id)

        # Get all search results for this query
        search_results = await self._get_search_results(ctx, search_query_id)
        # Filter out the search results that have a value of None
        search_results = [sr for sr in search_results if sr.value is not None]
        # Separate the values because clustering just takes the values
        search_result_values = cast(
            list[str], [sr.value for sr in search_results]
        )  # We already filtered out the None values

        guidance = f"Specifically focus on the following attribute: {search_query.search_query}"
        if feedback is not None and feedback != "" and existing_clusters:
            centroids: list[str] = await propose_clusters(
                search_result_values,
                extra_instructions_list=[guidance],
                feedback_list=[
                    ClusterFeedback(
                        clusters=[
                            c["centroid"] for c in existing_clusters if c["centroid"] is not None
                        ],
                        feedback=feedback,
                    )
                ],
            )
        else:
            centroids: list[str] = await propose_clusters(
                search_result_values,
                extra_instructions_list=[guidance],
            )

        logger.info(f"centroids: {centroids}")

        # store clusters in the database
        centroid_to_id: dict[str, str] = {}
        async with self.db.session() as session:
            for centroid in centroids:
                centroid_id = str(uuid4())
                cluster = SQLASearchCluster(
                    id=centroid_id,
                    collection_id=ctx.collection_id,
                    search_query_id=search_query_id,
                    centroid=centroid,
                )
                session.add(cluster)
                centroid_to_id[centroid] = centroid_id
            await session.commit()

        results_to_assign = [
            search_result for search_result in search_result_values for _ in centroids
        ]
        clusters_to_assign = [centroid for _ in search_result_values for centroid in centroids]
        # we need to use search_results for the search_result.id, results_to_assign only has the value
        results_to_record = [search_result for search_result in search_results for _ in centroids]

        async def record_assignment(batch_index: int, assignment: tuple[bool, str] | None):
            if assignment is None:
                return

            async with self.db.session() as session:
                search_result = results_to_record[batch_index]
                centroid = clusters_to_assign[batch_index]
                decision = assignment[0]
                reason = assignment[1]
                search_result_id = search_result.id
                cluster_id = centroid_to_id[centroid]
                search_result_cluster = SQLASearchResultCluster(
                    id=str(uuid4()),
                    search_result_id=search_result_id,
                    cluster_id=cluster_id,
                    decision=decision,
                    reason=reason,
                )
                session.add(search_result_cluster)
                await session.commit()

        await assign_with_backend(
            DEFAULT_ASSIGNER,
            results_to_assign,
            clusters_to_assign,
            assignment_callback=record_assignment,
        )

    async def get_existing_search_clusters(
        self, ctx: ViewContext, search_query_id: str
    ) -> list[dict[str, Any]]:
        """Get existing clusters for a search query."""
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLASearchCluster.centroid, SQLASearchCluster.id).where(
                    SQLASearchCluster.collection_id == ctx.collection_id,
                    SQLASearchCluster.search_query_id == search_query_id,
                )
            )
            clusters = result.all()
            return [{"centroid": c.centroid, "id": c.id} for c in clusters]

    async def get_cluster_matches(self, centroid: str) -> list[dict[str, Any]]:
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLASearchResultCluster)
                .options(selectinload(SQLASearchResultCluster.search_result))
                .join(SQLASearchCluster, SQLASearchResultCluster.cluster_id == SQLASearchCluster.id)
                .where(SQLASearchCluster.centroid == centroid)
            )
            return [r.search_result.to_search_result() for r in result.scalars().all()]

    async def clear_search_result_clusters(self, ctx: ViewContext, search_query_id: str):
        """Clear cluster assignments for search results."""
        async with self.db.session() as session:
            # Delete all cluster assignments for the clusters associated with this search query
            await session.execute(
                delete(SQLASearchResultCluster).where(
                    SQLASearchResultCluster.cluster_id.in_(
                        select(SQLASearchCluster.id).where(
                            SQLASearchCluster.collection_id == ctx.collection_id,
                            SQLASearchCluster.search_query_id == search_query_id,
                        )
                    )
                )
            )

            # Delete all clusters for this search query
            await session.execute(
                delete(SQLASearchCluster).where(
                    SQLASearchCluster.collection_id == ctx.collection_id,
                    SQLASearchCluster.search_query_id == search_query_id,
                )
            )

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

    async def add_search_job(self, query_id: str) -> tuple[bool, str]:
        """
        Adds or finds a search job for the given query. The first return value is whether this
        call added a new job.
        """
        async with self.db.session() as session:
            # Check if an equivalent job already exists
            result = await session.execute(
                select(SQLAJob)
                .filter(SQLAJob.type == "compute_search")
                .filter(SQLAJob.job_json["query_id"].astext == query_id)
                .order_by(SQLAJob.created_at.desc())
                .limit(1)
            )
            existing: SQLAJob | None = result.scalar_one_or_none()
            if existing is not None and existing.status in [JobStatus.PENDING, JobStatus.RUNNING]:
                return False, existing.id

            # Otherwise, create a new job
            job_id = str(uuid4())
            session.add(SQLAJob(id=job_id, type="compute_search", job_json={"query_id": query_id}))
            logger.info(f"Added job with ID: {job_id}")

            return True, job_id

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

    async def list_search_queries(self, collection_id: str) -> list[SQLASearchQuery]:
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLASearchQuery).where(SQLASearchQuery.collection_id == collection_id)
            )

            return list(result.scalars().all())

    async def list_search_jobs_and_queries(self):
        async with self.db.session() as session:
            # Find the latest job creation time corresponding to each query ID.
            sub_q = (
                select(
                    SQLAJob.job_json["query_id"].astext.label("query_id"),
                    func.max(SQLAJob.created_at).label("created_at"),
                )
                .group_by("query_id")
                .filter(SQLAJob.type == "compute_search")
            ).subquery()
            # Find all search queries, along with the latest job corresponding to each one.
            q = (
                select(SQLAJob, SQLASearchQuery)
                .select_from(sub_q)
                .filter(SQLAJob.type == "compute_search")
                .filter(SQLASearchQuery.id == sub_q.c.query_id)
                .filter(SQLAJob.created_at == sub_q.c.created_at)
                .order_by(SQLASearchQuery.created_at.desc())
            )
            result = await session.execute(q)

        return result.all()

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

    async def get_search_job_and_query(
        self, job_id: str
    ) -> tuple[dict[Any, Any], SQLASearchQuery] | None:
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAJob, SQLASearchQuery)
                .filter(SQLAJob.id == job_id)
                .filter(SQLAJob.type == "compute_search")
                .filter(SQLAJob.job_json["query_id"].astext == SQLASearchQuery.id)
            )

        row = result.one_or_none()
        if row is None:
            return None
        job, query = row
        return job.job_json, query

    async def cleanup_old_chat_sessions(self, days_old: int = 7) -> int:
        """
        Delete chat sessions that haven't been updated in the specified number of days.

        Args:
            days_old: Number of days after which sessions are considered old (default: 7)

        Returns:
            Number of sessions deleted
        """
        cutoff_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_old)

        async with self.db.session() as session:
            result = await session.execute(
                delete(SQLAChatSession).where(SQLAChatSession.updated_at < cutoff_date)
            )
            deleted_count = result.rowcount or 0
            return deleted_count

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

    async def add_search_query(self, ctx: ViewContext, search_query: str) -> str:
        """
        Add a search query to the SQLASearchQuery table if it does not already exist.
        Returns the id of the search query.
        """
        async with self.db.session() as session:
            # Check if the search query already exists for this collection
            result = await session.execute(
                select(SQLASearchQuery).where(
                    SQLASearchQuery.collection_id == ctx.collection_id,
                    SQLASearchQuery.search_query == search_query,
                )
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                return existing.id

        # Otherwise, create a new search query
        async with self.db.session() as session:
            new_id = str(uuid4())
            sq = SQLASearchQuery(
                id=new_id,
                collection_id=ctx.collection_id,
                search_query=search_query,
            )
            session.add(sq)

        logger.info(
            f"Added new search query {search_query} with id {new_id} to collection_id {ctx.collection_id}"
        )
        return new_id

    async def create_api_key(self, user_id: str, name: str) -> tuple[str, str]:
        """
        Create a new API key for a user.


        Returns:
            tuple: (api_key_id, raw_api_key) - raw key should be shown to user once
        """

        raw_api_key = f"dk_{secrets.token_urlsafe(32)}"
        key_hash = pwd_context.hash(raw_api_key)
        api_key_id = str(uuid4())

        async with self.db.session() as session:
            api_key = SQLAApiKey(
                id=api_key_id,
                user_id=user_id,
                name=name,
                key_hash=key_hash,
            )
            session.add(api_key)

        logger.info(f"Created API key {api_key_id} for user {user_id}")
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
        """
        if not raw_api_key.startswith("dk_"):
            return None

        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAApiKey)
                .join(SQLAUser, SQLAApiKey.user_id == SQLAUser.id)
                .where(SQLAApiKey.disabled_at.is_(None))  # type: ignore
                .options(selectinload(SQLAApiKey.user))
            )

            for api_key in result.scalars().all():
                if pwd_context.verify(raw_api_key, api_key.key_hash):
                    await session.execute(
                        update(SQLAApiKey)
                        .where(SQLAApiKey.id == api_key.id)
                        .values(last_used_at=datetime.now(UTC).replace(tzinfo=None))
                    )
                    return api_key.user.to_user()

            return None

    ######################
    # Telemetry Log #
    ######################

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
        async with self.db.session() as session:
            session.add(
                SQLATelemetryLog(
                    id=telemetry_id,
                    user_id=user_id,
                    collection_id=collection_id,
                    type=type,
                    version=version,
                    json_data=json_data,
                )
            )
        return telemetry_id

    async def update_telemetry_log_collection_id(self, telemetry_id: str, collection_id: str):
        """Update the collection ID for a telemetry log entry."""
        async with self.db.session() as session:
            await session.execute(
                update(SQLATelemetryLog)
                .where(SQLATelemetryLog.id == telemetry_id)
                .values(collection_id=collection_id)
            )

    async def get_telemetry_log(self, telemetry_id: str) -> SQLATelemetryLog | None:
        """Get a telemetry log entry by ID."""
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLATelemetryLog).where(SQLATelemetryLog.id == telemetry_id)
            )
            return result.scalar_one_or_none()

    async def get_telemetry_logs_by_user(
        self, user_id: str, limit: int = 100
    ) -> list[SQLATelemetryLog]:
        """Get telemetry logs for a user, ordered by creation time (newest first)."""
        async with self.db.session() as session:
            result = await session.execute(
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
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLATelemetryLog)
                .where(SQLATelemetryLog.collection_id == collection_id)
                .order_by(SQLATelemetryLog.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
