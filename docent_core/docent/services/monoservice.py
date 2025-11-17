from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import (
    Any,
    AsyncIterator,
    Final,
    Literal,
    ParamSpec,
    Sequence,
    TypeVar,
    cast,
)
from uuid import uuid4

from passlib.context import CryptContext
from sqlalchemy import (
    ColumnElement,
    Text,
    column,
    delete,
    distinct,
    exists,
    func,
    literal,
    literal_column,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import FromClause, lateral, text
from sqlalchemy.types import Numeric

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun, FilterableField
from docent.data_models.transcript import Transcript, TranscriptGroup
from docent_core._db_service.db import DocentDB
from docent_core._server._broker.redis_client import enqueue_job, get_redis_client
from docent_core._worker.constants import WORKER_QUEUE_NAME
from docent_core.docent.db.contexts import TelemetryContext, ViewContext
from docent_core.docent.db.dql import (
    DQLExecutionError,
    JsonFieldInfo,
    QueryExpression,
    SelectedColumn,
    apply_limit_cap,
    build_default_registry,
    ensure_dql_collection_access,
    extract_selected_columns,
    get_query_limit_value,
    parameterize_expression,
    parse_dql_query,
)
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

EMPTY_TEXT_ARRAY = literal_column("'{}'::text[]")  # type: ignore[reportUnknownVariableType]
MAX_DQL_RESULT_LIMIT: Final[int] = 10_000


def _infer_filter_type_from_types(
    value_types: str,
) -> Literal["str", "bool", "int", "float"] | None:
    """Infer a filter type from a comma-separated list of detected JSON value types."""

    types = [t.strip() for t in value_types.split(",") if t.strip()]
    if not types:
        return None
    if "number" in types:
        return "float"
    if "string" in types:
        return "str"
    if "boolean" in types:
        return "bool"
    return None


class _NotGiven:
    """Sentinel class for detecting when a parameter was not provided."""

    def __repr__(self):
        return "NOT_GIVEN"


NOT_GIVEN = _NotGiven()


@dataclass(slots=True)
class DQLQueryResult:
    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]]
    selected_columns: list[SelectedColumn]
    truncated: bool
    execution_time_ms: float
    compiled_sql: str
    requested_limit: int | None
    applied_limit: int
    row_count: int


class MonoService:
    def __init__(self, db: DocentDB):
        self.db = db

    @classmethod
    async def init(cls):
        db = await DocentDB.init()
        return cls(db)

    async def _collect_json_field_records(
        self,
        session: AsyncSession,
        *,
        from_clause: FromClause,
        value_expression: ColumnElement[Any],
        value_column_name: str,
        limit_rows: int,
        where_clause: ColumnElement[bool] | None = None,
        group_specs: Sequence[tuple[str, ColumnElement[Any]]] | None = None,
        exclude_null_values: bool = True,
    ) -> list[JsonFieldInfo]:
        """Walk a JSON column and surface nested paths so callers can extend metadata safely."""

        group_specs = list(group_specs or [])
        labeled_groups = [column_expr.label(label) for label, column_expr in group_specs]

        base_stmt = select(*labeled_groups, value_expression.label("value")).select_from(
            from_clause
        )
        if exclude_null_values:
            base_stmt = base_stmt.where(value_expression.isnot(None))
        if where_clause is not None:
            base_stmt = base_stmt.where(where_clause)
        base_stmt = base_stmt.limit(limit_rows)

        base_cte = base_stmt.cte("json_base")
        base_group_columns = [getattr(base_cte.c, label) for label, _ in group_specs]

        seed = select(  # type: ignore
            *base_group_columns,
            base_cte.c.value.label("value"),
            EMPTY_TEXT_ARRAY.label("path"),  # type: ignore[reportUnknownArgumentType]
            func.jsonb_typeof(base_cte.c.value).label("value_type"),
        )

        walk_cte = seed.cte(name="json_walk", recursive=True)

        child = lateral(
            func.jsonb_each(walk_cte.c.value).table_valued(
                column("key", Text),
                column("value", JSONB),
            )
        ).alias("json_child")

        recursive = select(  # type: ignore
            *[getattr(walk_cte.c, label) for label, _ in group_specs],
            child.c.value.label("value"),
            func.array_append(walk_cte.c.path, child.c.key).label("path"),
            func.jsonb_typeof(child.c.value).label("value_type"),
        ).select_from(walk_cte.join(child, walk_cte.c.value_type == literal("object")))

        walk = walk_cte.union_all(recursive)

        path_column = walk.c.path
        value_types_expr = func.string_agg(
            distinct(walk.c.value_type),
            literal(","),
        ).label("value_types")

        stmt = (
            select(
                *[getattr(walk.c, label) for label, _ in group_specs],
                path_column.label("path"),
                value_types_expr,
            )
            .where(func.array_length(path_column, 1) > 0)
            .group_by(*[getattr(walk.c, label) for label, _ in group_specs], path_column)
        )

        result = await session.execute(stmt)
        records: list[JsonFieldInfo] = []
        for row in result:
            raw_path: list[str] = getattr(row, "path", None) or []
            path = tuple(str(segment) for segment in raw_path)
            labels = {
                label: str(getattr(row, label))
                for label, _ in group_specs
                if getattr(row, label) is not None
            }
            value_types = getattr(row, "value_types") or ""
            inferred_type = _infer_filter_type_from_types(value_types) if value_types else None
            records.append(
                JsonFieldInfo(
                    column=value_column_name,
                    path=path,
                    value_type=inferred_type,
                    labels=labels,
                )
            )
        return records

    async def get_json_metadata_fields_for_column(
        self,
        collection_id: str,
        *,
        table: FromClause,
        json_column: ColumnElement[Any],
        column_name: str,
        join_condition: ColumnElement[bool] | None = None,
        group_specs: Sequence[tuple[str, ColumnElement[Any]]] | None = None,
    ) -> list[JsonFieldInfo]:
        """Discover JSON paths for a specific table column scoped to a collection."""

        limit_rows = 5000

        async with self.db.session() as session:
            if join_condition is None:
                collection_column = getattr(table.c, "collection_id", None)
                if collection_column is None:
                    raise ValueError(
                        "Tables without a collection_id column must provide a join_condition."
                    )
                from_clause = table
                where_clause = collection_column == collection_id
            else:
                from_clause = table.join(
                    SQLAAgentRun.__table__,
                    join_condition,
                )
                where_clause = SQLAAgentRun.collection_id == collection_id

            return await self._collect_json_field_records(
                session,
                from_clause=from_clause,
                value_expression=json_column,
                value_column_name=column_name,
                limit_rows=limit_rows,
                where_clause=where_clause,
                group_specs=group_specs,
            )

    async def get_json_metadata_fields_map(
        self,
        collection_id: str,
    ) -> dict[str, list[JsonFieldInfo]]:
        """Gather JSON metadata field infos for all DQL tables within a collection."""

        def _dedupe(infos: list[JsonFieldInfo]) -> list[JsonFieldInfo]:
            seen: set[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]] = set()
            deduped: list[JsonFieldInfo] = []
            for info in infos:
                label_items = tuple(sorted(info.labels.items()))
                key = (info.column.lower(), info.path, label_items)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(info)
            deduped.sort(
                key=lambda info: (
                    info.column,
                    info.path,
                    tuple(sorted(info.labels.items())),
                )
            )
            return deduped

        field_map: dict[str, list[JsonFieldInfo]] = {}

        agent_run_infos = await self.get_json_metadata_fields_for_column(
            collection_id,
            table=SQLAAgentRun.__table__,
            json_column=cast(ColumnElement[Any], SQLAAgentRun.metadata_json),
            column_name="metadata_json",
        )
        field_map[SQLAAgentRun.__tablename__] = _dedupe(agent_run_infos)

        # transcript_infos = await self.get_json_metadata_fields_for_column(
        #     collection_id,
        #     table=SQLATranscript.__table__,
        #     json_column=cast(ColumnElement[Any], SQLATranscript.metadata_json),
        #     column_name="metadata_json",
        #     join_condition=SQLATranscript.agent_run_id == SQLAAgentRun.id,
        # )
        # field_map[SQLATranscript.__tablename__] = _dedupe(transcript_infos)

        transcript_group_infos = await self.get_json_metadata_fields_for_column(
            collection_id,
            table=SQLATranscriptGroup.__table__,
            json_column=cast(ColumnElement[Any], SQLATranscriptGroup.metadata_json),
            column_name="metadata_json",
            join_condition=SQLATranscriptGroup.agent_run_id == SQLAAgentRun.id,
        )
        field_map[SQLATranscriptGroup.__tablename__] = _dedupe(transcript_group_infos)

        judge_output_infos = await self.get_json_metadata_fields_for_column(
            collection_id,
            table=SQLAJudgeResult.__table__,
            json_column=cast(ColumnElement[Any], SQLAJudgeResult.output),
            column_name="output",
            join_condition=SQLAJudgeResult.agent_run_id == SQLAAgentRun.id,
            group_specs=(("rubric_id", cast(ColumnElement[Any], SQLAJudgeResult.rubric_id)),),
        )

        judge_metadata_infos = await self.get_json_metadata_fields_for_column(
            collection_id,
            table=SQLAJudgeResult.__table__,
            json_column=cast(ColumnElement[Any], SQLAJudgeResult.result_metadata),
            column_name="result_metadata",
            join_condition=SQLAJudgeResult.agent_run_id == SQLAAgentRun.id,
            group_specs=(("rubric_id", cast(ColumnElement[Any], SQLAJudgeResult.rubric_id)),),
        )

        field_map[SQLAJudgeResult.__tablename__] = _dedupe(
            judge_output_infos + judge_metadata_infos
        )

        return field_map

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
        agent_run_limit = 1_000_000
        if existing_runs + new_runs > agent_run_limit:
            raise ValueError(
                f"Number of agent runs in the current collection is too large. Current limit: {agent_run_limit}, Current count: {existing_runs}, New runs: {new_runs}"
            )

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
            accumulation_count = await accumulation_service.delete_agent_run_accumulations(
                collection_id, agent_run_ids
            )

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

    async def get_agent_run_ids(
        self,
        ctx: ViewContext,
        sort_field: str | None = None,
        sort_direction: Literal["asc", "desc"] = "asc",
        limit: int | None = None,
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

            # Apply limit if specified
            if limit is not None:
                query = query.limit(limit)

            result = await session.execute(query)
            agent_run_ids = result.scalars().all()
            logger.info(f"get_agent_run_ids: Found {len(agent_run_ids)} agent run IDs")
            return list(agent_run_ids)

    ########
    # DQL  #
    ########

    async def execute_dql_query(
        self,
        *,
        user: User,
        collection_id: str,
        dql: str,
    ) -> DQLQueryResult:

        await ensure_dql_collection_access(
            mono_service=self,
            user=user,
            collection_id=collection_id,
        )

        json_field_map = await self.get_json_metadata_fields_map(collection_id)
        registry = build_default_registry(
            collection_id=collection_id,
            json_fields=json_field_map,
        )
        expression = parse_dql_query(
            dql,
            registry=registry,
            collection_id=collection_id,
        )
        selected_columns = extract_selected_columns(expression)
        query_expression = cast(QueryExpression, expression)
        requested_limit = get_query_limit_value(query_expression)
        server_cap = MAX_DQL_RESULT_LIMIT
        applied_limit = server_cap if requested_limit is None else min(requested_limit, server_cap)

        if requested_limit is None or requested_limit > server_cap:
            fetch_limit = server_cap + 1
        else:
            fetch_limit = requested_limit + 1

        apply_limit_cap(query_expression, fetch_limit)
        compiled_sql = expression.sql(dialect="postgres", pretty=False)  # type: ignore[reportUnknownMemberType]
        parameterized_sql, parameters = parameterize_expression(expression, "postgres")
        statement = text(parameterized_sql)
        logger.info(
            "Executing DQL query for collection_id=%s user_id=%s fetch_limit=%s sql=%s params=%s",
            collection_id,
            user.id,
            fetch_limit,
            parameterized_sql,
            parameters,
        )

        start_time = perf_counter()
        async with self.db.dql_session(collection_id) as session:
            try:
                result = await session.execute(statement, parameters or {})
            except SQLAlchemyError as exc:
                message = str(getattr(exc, "orig", exc)).strip()
                if not message:
                    message = "Failed to execute query."
                raise DQLExecutionError(message) from exc

            columns = tuple(result.keys())
            raw_rows = result.fetchall()
            result.close()
        execution_time_ms = (perf_counter() - start_time) * 1000.0

        has_extra = len(raw_rows) == fetch_limit
        if has_extra:
            raw_rows = raw_rows[:-1]

        rows = [tuple(row) for row in raw_rows]

        row_count = len(rows)
        truncated = has_extra
        logger.debug(
            "DQL query finished for collection_id=%s user_id=%s row_count=%s truncated=%s execution_time_ms=%.2f",
            collection_id,
            user.id,
            row_count,
            truncated,
            execution_time_ms,
        )

        return DQLQueryResult(
            columns=tuple(str(column) for column in columns),
            rows=rows,
            selected_columns=selected_columns,
            truncated=truncated,
            execution_time_ms=execution_time_ms,
            compiled_sql=compiled_sql,
            requested_limit=requested_limit,
            applied_limit=applied_limit,
            row_count=row_count,
        )

    async def get_agent_runs(
        self,
        # ctx: ViewContext | None = None,
        ctx: ViewContext,
        agent_run_ids: list[str] | None = None,
        limit: int | None = None,
        apply_base_where_clause: bool = True,
        batch_size: int = 10_000,
    ) -> list[AgentRun]:
        """
        Get all agent runs for a given Collection ID.
        """
        async with self.db.session() as session:
            # If we don't have the agent run ids, get them first
            if agent_run_ids is None:
                agent_run_ids = await self.get_agent_run_ids(ctx, limit=limit)

            # Limit the agent_run_ids to the limit
            if limit is not None:
                agent_run_ids = agent_run_ids[:limit]

            if not agent_run_ids:
                return []

            # Gather agent runs in batches
            agent_runs_raw: list[SQLAAgentRun] = []
            for i in range(0, len(agent_run_ids), batch_size):
                batch_ids = agent_run_ids[i : i + batch_size]

                query = select(SQLAAgentRun).where(SQLAAgentRun.id.in_(batch_ids))
                if apply_base_where_clause:
                    query = query.where(ctx.get_base_where_clause(SQLAAgentRun))

                result = await session.execute(query)
                agent_runs_raw.extend(result.scalars().all())

            # Gather transcripts in batches
            transcripts_raw: list[SQLATranscript] = []
            for i in range(0, len(agent_run_ids), batch_size):
                batch_ids = agent_run_ids[i : i + batch_size]
                result = await session.execute(
                    select(SQLATranscript).where(SQLATranscript.agent_run_id.in_(batch_ids))
                )
                transcripts_raw.extend(result.scalars().all())

            # Gather transcript groups in batches
            transcript_groups_raw: list[SQLATranscriptGroup] = []
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
                        structured_metadata["created_at"] = created_at.isoformat(sep=" ")

                    metadata_map[run_id] = structured_metadata

        return metadata_map

    async def get_metadata_field_range(
        self, ctx: ViewContext, field_name: str
    ) -> dict[str, float | None]:
        """Return the numeric range for a metadata field across agent runs."""

        field_parts = field_name.split(".")
        if len(field_parts) < 2 or field_parts[0] != "metadata":
            raise ValueError("Metadata ranges are only supported for metadata.* fields")

        json_path_parts = field_parts[1:]
        for part in json_path_parts:
            if not part.replace("_", "").replace("-", "").isalnum():
                raise ValueError("Invalid metadata field path")

        async with self.db.session() as session:
            json_expr = cast(ColumnElement[Any], SQLAAgentRun.metadata_json)
            for part in json_path_parts:
                json_expr = cast(ColumnElement[Any], json_expr.op("->")(part))

            text_expr = cast(ColumnElement[Any], SQLAAgentRun.metadata_json)
            for idx, part in enumerate(json_path_parts):
                if idx == len(json_path_parts) - 1:
                    text_expr = cast(ColumnElement[Any], text_expr.op("->>")(part))
                else:
                    text_expr = cast(ColumnElement[Any], text_expr.op("->")(part))

            numeric_clause = func.jsonb_typeof(json_expr) == "number"
            numeric_expr: ColumnElement[Any] = cast(ColumnElement[Any], text_expr.cast(Numeric))

            query = (
                select(
                    func.min(numeric_expr).label("min_value"),
                    func.max(numeric_expr).label("max_value"),
                )
                .select_from(SQLAAgentRun)
                .where(
                    SQLAAgentRun.collection_id == ctx.collection_id,
                    numeric_clause,
                )
            )

            result = await session.execute(query)
            row = result.one()

        min_value = row.min_value
        max_value = row.max_value

        return {
            "min": float(min_value) if min_value is not None else None,
            "max": float(max_value) if max_value is not None else None,
        }

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
            ctx, agent_run_ids=[agent_run_id], apply_base_where_clause=apply_base_where_clause
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

            # Create new view and insert, handling races where it may already exist
            async with self.db.session() as session:
                try:
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
                    session.add(view)
                    await session.flush()
                except IntegrityError:
                    await session.rollback()
                    result = await session.execute(
                        select(SQLAView).where(
                            SQLAView.collection_id == collection_id,
                            SQLAView.user_id == user.id,
                            SQLAView.for_sharing.is_(False),
                        )
                    )
                    view = result.scalar_one()

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

    async def get_telemetry_ctx_for_user(self, user: User) -> TelemetryContext:
        return TelemetryContext(user=user)

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
                SQLAJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
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

    async def add_telemetry_ingest_job(
        self,
        telemetry_log_id: str,
        user: User,
        *,
        request_id: str | None = None,
        content_type: str | None = None,
        content_encoding: str | None = None,
    ) -> str | None:
        """
        Adds a telemetry ingest job for the given telemetry log.
        Only adds the job if there isn't already a pending job for this telemetry log.
        """
        async with self.db.session() as session:
            existing_job_query = select(SQLAJob).where(
                SQLAJob.type == "telemetry_ingest_job",
                SQLAJob.job_json.contains({"telemetry_log_id": telemetry_log_id}),
                SQLAJob.status.in_([JobStatus.PENDING]),
            )

            existing_job_result = await session.execute(existing_job_query)
            existing_jobs = existing_job_result.scalars().all()

            if existing_jobs:
                job_ids = [job.id for job in existing_jobs]
                logger.debug(
                    "Telemetry ingest job(s) already exist for telemetry_log_id %s: %s (statuses: %s)",
                    telemetry_log_id,
                    job_ids,
                    [job.status for job in existing_jobs],
                )
                return None

            job_id = str(uuid4())
            session.add(
                SQLAJob(
                    id=job_id,
                    type="telemetry_ingest_job",
                    job_json={
                        "telemetry_log_id": telemetry_log_id,
                        "user_id": user.id,
                        "user_email": user.email,
                        "user_organization_ids": user.organization_ids,
                        "request_id": request_id,
                        "content_type": content_type,
                        "content_encoding": content_encoding,
                    },
                )
            )
            logger.info(
                "Added telemetry ingest job %s for telemetry_log_id %s (request_id=%s)",
                job_id,
                telemetry_log_id,
                request_id,
            )

            return job_id

    async def add_and_enqueue_telemetry_ingest_job(
        self,
        telemetry_log_id: str,
        user: User,
        *,
        request_id: str | None = None,
        content_type: str | None = None,
        content_encoding: str | None = None,
    ) -> str | None:
        job_id = await self.add_telemetry_ingest_job(
            telemetry_log_id,
            user,
            request_id=request_id,
            content_type=content_type,
            content_encoding=content_encoding,
        )

        if job_id is None:
            return None

        ctx = await self.get_telemetry_ctx_for_user(user)
        await enqueue_job(ctx, job_id)  # type: ignore
        logger.info(
            "Enqueued telemetry ingest job %s for telemetry_log_id %s (request_id=%s)",
            job_id,
            telemetry_log_id,
            request_id,
        )
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
        # Create or reuse a job in the database
        job_id = await self.add_telemetry_processing_job(collection_id, user)
        if job_id is None:
            # Verify if an existing pending job is already enqueued; if not, enqueue it
            async with self.db.session() as session:
                pending_job_query = (
                    select(SQLAJob)
                    .where(
                        SQLAJob.type == "telemetry_processing_job",
                        SQLAJob.job_json.contains({"collection_id": collection_id}),
                        SQLAJob.status == JobStatus.PENDING,
                    )
                    .order_by(SQLAJob.created_at.desc())
                )
                result = await session.execute(pending_job_query)
                pending_job = result.scalars().first()
                if pending_job is None:
                    return None
                job_id = pending_job.id

                # Check if already enqueued in Redis
                try:
                    redis_client = await get_redis_client()
                    if await redis_client.zscore(WORKER_QUEUE_NAME, job_id) is not None:  # type: ignore[arg-type]
                        logger.info(
                            "Telemetry processing job %s for collection %s is already enqueued",
                            job_id,
                            collection_id,
                        )
                        return job_id
                except Exception as exc:
                    logger.error(
                        "Unable to check redis queue for telemetry processing job %s: %s",
                        job_id,
                        exc,
                    )

        ctx = await self.get_default_view_ctx(collection_id, user)

        try:
            await enqueue_job(ctx, job_id)  # type: ignore
            logger.info(
                f"Enqueued telemetry processing job {job_id} for collection {collection_id}"
            )
            return job_id
        except Exception as exc:
            logger.error(
                "Failed to enqueue telemetry processing job %s for collection %s: %s",
                job_id,
                collection_id,
                exc,
            )
            # If enqueue failed, clear the pending job so future attempts can recreate
            async with self.db.session() as session:
                await session.execute(
                    update(SQLAJob)
                    .where(SQLAJob.id == job_id, SQLAJob.status == JobStatus.PENDING)
                    .values(status=JobStatus.CANCELED)
                )
            return None

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

    async def change_user_password(self, email: str, old_password: str, new_password: str) -> bool:
        """
        Change a user's password if the provided current password is valid.

        Args:
            email: The email address of the user
            old_password: The user's current password
            new_password: The new password to set

        Returns:
            True if the password was changed, False otherwise
        """
        async with self.db.session() as session:
            result = await session.execute(select(SQLAUser).where(SQLAUser.email == email))
            sqla_user = result.scalar_one_or_none()
            if not sqla_user:
                return False

            if not pwd_context.verify(old_password, sqla_user.password_hash):
                return False

            sqla_user.password_hash = pwd_context.hash(new_password)

        logger.info(f"Password updated for user with email: {email}")
        return True

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

    async def get_permissions_for_collections(
        self, user: User, collection_ids: list[str]
    ) -> dict[str, Permission | None]:
        """
        Batch fetch highest permission level for a user across many collections.
        """
        if not collection_ids:
            return {}

        async with self.db.session() as session:
            conditions = [
                SQLAAccessControlEntry.is_public,
                SQLAAccessControlEntry.user_id == user.id,
            ]
            if user.organization_ids:
                conditions.append(SQLAAccessControlEntry.organization_id.in_(user.organization_ids))

            result = await session.execute(
                select(
                    SQLAAccessControlEntry.collection_id,
                    SQLAAccessControlEntry.permission,
                ).where(
                    SQLAAccessControlEntry.collection_id.in_(collection_ids),
                    or_(*conditions),
                )
            )
            rows = result.all()

        perms_by_id: dict[str, list[str]] = {cid: [] for cid in collection_ids}
        for cid, perm in rows:
            if cid is not None and perm is not None:
                perms_by_id[cid].append(perm)

        out: dict[str, Permission | None] = {}
        for cid, perms in perms_by_id.items():
            if not perms:
                out[cid] = None
            else:
                highest = max(perms, key=lambda p: PERMISSION_LEVELS[p])
                out[cid] = Permission(highest)
        return out

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
        """Expose agent run filter fields derived from JSON metadata and related tables."""

        all_fields: dict[str, FilterableField] = {}

        agent_run_infos = await self.get_json_metadata_fields_for_column(
            ctx.collection_id,
            table=SQLAAgentRun.__table__,
            json_column=cast(ColumnElement[Any], SQLAAgentRun.metadata_json),
            column_name="metadata_json",
        )
        for info in agent_run_infos:
            if info.value_type is None or not info.path:
                continue
            field_name = "metadata." + ".".join(info.path)
            all_fields[field_name] = {"name": field_name, "type": info.value_type}

        judge_infos = await self.get_json_metadata_fields_for_column(
            ctx.collection_id,
            table=SQLAJudgeResult.__table__,
            json_column=cast(ColumnElement[Any], SQLAJudgeResult.output),
            column_name="output",
            join_condition=SQLAJudgeResult.agent_run_id == SQLAAgentRun.id,
            group_specs=(("rubric_id", cast(ColumnElement[Any], SQLAJudgeResult.rubric_id)),),
        )
        for info in judge_infos:
            rubric_id = info.labels.get("rubric_id")
            if not rubric_id or info.value_type is None or not info.path:
                continue
            field_name = f"rubric.{rubric_id}." + ".".join(info.path)
            all_fields[field_name] = {"name": field_name, "type": info.value_type}

        judge_metadata_infos = await self.get_json_metadata_fields_for_column(
            ctx.collection_id,
            table=SQLAJudgeResult.__table__,
            json_column=cast(ColumnElement[Any], SQLAJudgeResult.result_metadata),
            column_name="result_metadata",
            join_condition=SQLAJudgeResult.agent_run_id == SQLAAgentRun.id,
            group_specs=(("rubric_id", cast(ColumnElement[Any], SQLAJudgeResult.rubric_id)),),
        )
        for info in judge_metadata_infos:
            rubric_id = info.labels.get("rubric_id")
            if not rubric_id or info.value_type is None or not info.path:
                continue
            field_name = f"rubric.{rubric_id}." + ".".join(info.path)
            all_fields[field_name] = {"name": field_name, "type": info.value_type}

        all_fields["agent_run_id"] = {"name": "agent_run_id", "type": "str"}
        # all_fields["text"] = {"name": "text", "type": "str"}

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
