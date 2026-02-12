from __future__ import annotations

import hashlib
import json
from collections import Counter
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import (
    Any,
    AsyncIterator,
    Iterator,
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
    Select,
    Text,
    and_,
    column,
    delete,
    distinct,
    exists,
    func,
    literal,
    literal_column,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, noload, selectinload
from sqlalchemy.sql import FromClause, lateral, text
from sqlalchemy.types import Numeric

from docent._log_util import get_logger
from docent.data_models.agent_run import (
    AgentRun,
    FieldValueSample,
    FilterableFieldType,
    FilterableFieldWithSamples,
)
from docent.data_models.transcript import Transcript, TranscriptGroup
from docent.data_models.util import clone_agent_run_with_random_ids
from docent.judges import ResultType
from docent.sdk.llm_context import LLMContextSpec
from docent_core._db_service.db import DocentDB
from docent_core._server._broker.redis_client import (
    clear_arq_job_key,
    enqueue_job,
    get_redis_client,
)
from docent_core._worker.constants import WorkerFunction, get_queue_name_for_job_type
from docent_core.docent.db.contexts import TelemetryContext, ViewContext
from docent_core.docent.db.dql import JsonFieldInfo
from docent_core.docent.db.filters import (
    CollectionFilter,
    ComplexFilter,
    FilterSQLContext,
    build_judge_result_filter_clause,
    collect_label_set_ids,
    filter_uses_labels,
    filter_uses_tags,
    parse_filter_dict,
)
from docent_core.docent.db.schemas.auth_models import (
    PERMISSION_LEVELS,
    OrganizationMember,
    OrganizationRole,
    OrganizationWithRole,
    Permission,
    ResourceType,
    SubjectType,
    User,
)
from docent_core.docent.db.schemas.chart import SQLAChart
from docent_core.docent.db.schemas.chat import SQLAChatSession
from docent_core.docent.db.schemas.data_table import SQLADataTable
from docent_core.docent.db.schemas.label import SQLALabel, SQLALabelSet, SQLATag
from docent_core.docent.db.schemas.refinement import SQLARefinementAgentSession
from docent_core.docent.db.schemas.rubric import SQLAJudgeResult, SQLARubric
from docent_core.docent.db.schemas.tables import (
    JobStatus,
    SQLAAccessControlEntry,
    SQLAAgentRun,
    SQLAAnalyticsEvent,
    SQLAApiKey,
    SQLACollection,
    SQLAFilter,
    SQLAIngestionPayload,
    SQLAJob,
    SQLAMetadataObservation,
    SQLAModelApiKey,
    SQLAOrganization,
    SQLASearchCluster,
    SQLASearchQuery,
    SQLASearchResult,
    SQLASearchResultCluster,
    SQLASession,
    SQLATelemetryAgentRunStatus,
    SQLATelemetryLineage,
    SQLATelemetryLog,
    SQLATranscript,
    SQLATranscriptEmbedding,
    SQLATranscriptGroup,
    SQLAUser,
    SQLAUserOrganization,
    SQLAView,
)
from docent_core.docent.exceptions import BadRequestError, ConflictError, NotFoundError
from docent_core.docent.services.data_tables import DEFAULT_DATA_TABLE_DQL, DEFAULT_DATA_TABLE_NAME
from docent_core.docent.services.telemetry_accumulation import deep_merge_dicts

logger = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

EMPTY_TEXT_ARRAY = literal_column("'{}'::text[]")  # type: ignore[reportUnknownVariableType]


def _infer_filter_type_from_types(
    value_types: str,
) -> FilterableFieldType | None:
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


_JSON_SCHEMA_TYPE_MAP: dict[str, FilterableFieldType] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}


def _extract_schema_fields(
    schema: dict[str, Any],
    prefix: str = "",
) -> Iterator[tuple[str, FilterableFieldType]]:
    """Extract field paths and types from a JSON Schema."""
    if "properties" in schema:
        for key, subschema in schema["properties"].items():
            new_prefix = f"{prefix}.{key}" if prefix else key
            yield from _extract_schema_fields(subschema, new_prefix)
    elif (schema_type := schema.get("type")) in _JSON_SCHEMA_TYPE_MAP:
        yield (prefix, _JSON_SCHEMA_TYPE_MAP[schema_type])


def _get_json_path_value(payload: Any, path: Sequence[str]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current_dict = cast(dict[str, Any], current)
        if key not in current_dict:
            return None
        current = current_dict[key]
    return current


def _serialize_modal_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _modal_value_key(value: Any) -> tuple[str, str]:
    if value is None:
        return ("none", "")
    if isinstance(value, (str, int, float, bool)):
        return (type(value).__name__, str(value))
    try:
        return (type(value).__name__, json.dumps(value, sort_keys=True))
    except TypeError:
        return (type(value).__name__, str(value))


def _pick_modal_value(values: Sequence[Any]) -> tuple[Any, int]:
    if not values:
        return None, 0

    counts: Counter[tuple[str, str]] = Counter()
    representatives: dict[tuple[str, str], Any] = {}
    for value in values:
        key = _modal_value_key(value)
        counts[key] += 1
        representatives.setdefault(key, value)

    modal_key, modal_count = sorted(
        counts.items(),
        key=lambda item: (-item[1], _serialize_modal_value(representatives[item[0]])),
    )[0]
    return representatives[modal_key], modal_count


def _log_compiled_query(label: str, query: Any) -> None:
    try:
        compiled = query.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    except Exception as exc:  # pragma: no cover - debug-only
        logger.info("agent_run_table_sql label=%s error=%s", label, exc)
        return
    logger.info("agent_run_table_sql label=%s sql=%s", label, compiled)


def _python_type_to_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return "string"


def _serialize_observation_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    return json.dumps(value, sort_keys=True)


def extract_metadata_observations(
    sq_agent_run: SQLAAgentRun, collection_id: str
) -> list[SQLAMetadataObservation]:
    metadata = sq_agent_run.metadata_json
    if not isinstance(metadata, dict):
        return []

    observed_at = sq_agent_run.created_at or datetime.now(UTC).replace(tzinfo=None)
    observations: list[SQLAMetadataObservation] = []

    def _walk(obj: Any, path_parts: list[str]) -> None:
        if not path_parts:
            return

        json_path = "metadata." + ".".join(path_parts)
        value_type = _python_type_to_value_type(obj)
        value_text = _serialize_observation_value(obj)
        value_hash = hashlib.md5(value_text.encode()).hexdigest()
        value_numeric: float | None = None
        if value_type == "number":
            try:
                value_numeric = float(obj)
            except (TypeError, ValueError):
                pass

        observations.append(
            SQLAMetadataObservation(
                agent_run_id=sq_agent_run.id,
                collection_id=collection_id,
                json_path=json_path,
                value_text=value_text,
                value_hash=value_hash,
                value_type=value_type,
                value_numeric=value_numeric,
                observed_at=observed_at,
            )
        )

        # Recurse into dicts
        if isinstance(obj, dict):
            obj_dict = cast(dict[str, Any], obj)
            for key, child_value in obj_dict.items():
                _walk(child_value, path_parts + [key])

    metadata_dict = cast(dict[str, Any], metadata)
    for key, value in metadata_dict.items():
        _walk(value, [key])

    return observations


def extract_metadata_observations_bulk(
    sq_agent_runs: Sequence[SQLAAgentRun], collection_id: str
) -> list[SQLAMetadataObservation]:
    result: list[SQLAMetadataObservation] = []
    for sq_agent_run in sq_agent_runs:
        result.extend(extract_metadata_observations(sq_agent_run, collection_id))
    return result


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

    _metadata_refresh_pending = False

    async def schedule_metadata_view_refresh(self) -> None:
        """Refresh the metadata_value_stats materialized view concurrently.

        Uses a PostgreSQL advisory lock to prevent concurrent refreshes from piling up.
        If a refresh is already running, marks a pending flag so the holder does one
        trailing refresh before releasing the lock (avoids permanently stale views).
        Errors are logged but not raised (best-effort background operation).
        """
        ADVISORY_LOCK_ID = 8675309  # arbitrary fixed lock ID
        # Signal intent before any await so the lock holder sees it
        # even if this coroutine yields before setting the flag.
        MonoService._metadata_refresh_pending = True
        try:
            async with self.db.engine.connect() as raw_conn:
                conn = await raw_conn.execution_options(isolation_level="AUTOCOMMIT")
                # Try to acquire a session-level advisory lock (non-blocking)
                lock_result = await conn.execute(
                    text(f"SELECT pg_try_advisory_lock({ADVISORY_LOCK_ID})")
                )
                acquired = lock_result.scalar()
                if not acquired:
                    logger.info(
                        "Metadata view refresh already in progress — flagged for re-refresh"
                    )
                    return
                try:
                    # Loop until no new writes arrive during a refresh.
                    # Clear the flag before each refresh so writes that land
                    # during the await re-set it for the next iteration.
                    while True:
                        MonoService._metadata_refresh_pending = False
                        await conn.execute(
                            text("REFRESH MATERIALIZED VIEW CONCURRENTLY metadata_value_stats")
                        )
                        logger.info("Successfully refreshed metadata_value_stats materialized view")
                        if not MonoService._metadata_refresh_pending:
                            break
                        logger.info("Writes arrived during refresh — performing trailing refresh")
                finally:
                    await conn.execute(text(f"SELECT pg_advisory_unlock({ADVISORY_LOCK_ID})"))
        except Exception:
            logger.exception("Failed to refresh metadata_value_stats materialized view")

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
        additional_where: ColumnElement[bool] | None = None,
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

            if additional_where is not None:
                where_clause = and_(where_clause, additional_where)

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
            session.add(
                SQLADataTable(
                    id=str(uuid4()),
                    collection_id=collection_id,
                    created_by=user.id,
                    name=DEFAULT_DATA_TABLE_NAME,
                    dql=DEFAULT_DATA_TABLE_DQL,
                    state_json=None,
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

    async def clone_collection(
        self,
        source_collection_id: str,
        user: User,
        new_name: str | None = None,
        new_description: str | None = None,
    ) -> tuple[str, int]:
        """
        Deep copy a collection with all its agent runs.

        This creates a new collection and copies all agent runs from the source collection,
        generating new IDs for all entities while preserving relationships.

        Args:
            source_collection_id: ID of the collection to clone
            user: User performing the clone operation
            new_name: Name for the new collection (defaults to "{source name} (Copy)")
            new_description: Description for the new collection (defaults to source description)

        Returns:
            Tuple of (new_collection_id, number_of_agent_runs_cloned)

        Raises:
            ValueError: If source collection doesn't exist
        """
        # Fetch source collection metadata
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLACollection).where(SQLACollection.id == source_collection_id)
            )
            source_collection = result.scalar_one_or_none()
            if not source_collection:
                raise ValueError(f"Source collection {source_collection_id} not found")

        # Determine new collection name and description
        final_name = new_name or (
            f"{source_collection.name} (Copy)" if source_collection.name else None
        )
        final_description = new_description or source_collection.description

        # Create the new collection
        new_collection_id = await self.create_collection(
            user=user,
            name=final_name,
            description=final_description,
        )

        # Mark it as a clone
        async with self.db.session() as session:
            await session.execute(
                update(SQLACollection)
                .where(SQLACollection.id == new_collection_id)
                .values(is_clone=True)
            )

        # Set up contexts for source and target collections
        source_ctx = ViewContext(
            collection_id=source_collection_id,
            view_id="default",
            user=user,
            base_filter=None,
        )
        target_ctx = ViewContext(
            collection_id=new_collection_id,
            view_id="default",
            user=user,
            base_filter=None,
        )

        # Get all agent run IDs from source collection (IDs are lightweight)
        agent_run_ids = await self.get_agent_run_ids(ctx=source_ctx)

        if not agent_run_ids:
            logger.info(
                f"Cloned collection {source_collection_id} to {new_collection_id} with 0 agent runs"
            )
            return new_collection_id, 0

        # Process agent runs in batches to avoid loading everything into memory
        batch_size = 100
        total_cloned = 0
        total_batches = (len(agent_run_ids) + batch_size - 1) // batch_size

        for batch_num, i in enumerate(range(0, len(agent_run_ids), batch_size), start=1):
            # Fetch this batch of agent runs with full data
            batch_ids = agent_run_ids[i : i + batch_size]
            source_agent_runs = await self.get_agent_runs(ctx=source_ctx, agent_run_ids=batch_ids)

            # Clone each agent run with new IDs
            cloned_agent_runs = [
                clone_agent_run_with_random_ids(agent_run) for agent_run in source_agent_runs
            ]

            # Insert the cloned batch
            await self.add_agent_runs(ctx=target_ctx, agent_runs=cloned_agent_runs)

            total_cloned += len(cloned_agent_runs)
            logger.info(
                f"Cloned batch {batch_num}/{total_batches} "
                f"({len(cloned_agent_runs)} agent runs) for collection {new_collection_id}"
            )

        logger.info(
            f"Cloned collection {source_collection_id} to {new_collection_id} "
            f"with {total_cloned} agent runs"
        )
        return new_collection_id, total_cloned

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

        # Delete data tables
        async with self.db.session() as session:
            await session.execute(
                delete(SQLADataTable).where(SQLADataTable.collection_id == collection_id)
            )

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

    async def batch_count_collection_agent_runs(
        self, collection_ids: list[str]
    ) -> dict[str, int | None]:
        """Count agent runs for multiple collections in a single query."""
        if not collection_ids:
            return {}

        async with self.db.session() as session:
            query = (
                select(SQLAAgentRun.collection_id, func.count().label("count"))
                .where(SQLAAgentRun.collection_id.in_(collection_ids))
                .group_by(SQLAAgentRun.collection_id)
            )
            result = await session.execute(query)
            counts = {row.collection_id: cast(int, row.count) for row in result}
            return {cid: counts.get(cid) if cid in counts else 0 for cid in collection_ids}

    async def batch_count_collection_rubrics(
        self, collection_ids: list[str]
    ) -> dict[str, int | None]:
        """Count rubrics for multiple collections in a single query."""
        if not collection_ids:
            return {}

        async with self.db.session() as session:
            query = (
                select(SQLARubric.collection_id, func.count(distinct(SQLARubric.id)).label("count"))
                .where(SQLARubric.collection_id.in_(collection_ids))
                .group_by(SQLARubric.collection_id)
            )
            result = await session.execute(query)
            counts = {row.collection_id: cast(int, row.count) for row in result}
            # Fill in zero counts for collections with no rubrics
            return {cid: counts.get(cid) if cid in counts else 0 for cid in collection_ids}

    async def batch_count_collection_label_sets(
        self, collection_ids: list[str]
    ) -> dict[str, int | None]:
        """Count label sets for multiple collections in a single query."""
        if not collection_ids:
            return {}

        async with self.db.session() as session:
            query = (
                select(SQLALabelSet.collection_id, func.count().label("count"))
                .where(SQLALabelSet.collection_id.in_(collection_ids))
                .group_by(SQLALabelSet.collection_id)
            )
            result = await session.execute(query)
            counts = {row.collection_id: cast(int, row.count) for row in result}
            # Fill in zero counts for collections with no label sets
            return {cid: counts.get(cid) if cid in counts else 0 for cid in collection_ids}

    async def dont_actually_check_space_for_runs(self, ctx: ViewContext, new_runs: int):
        # NOTE(mengk): temporarily disabled to avoid silently "dropping" runs, hence confusing users
        # TODO(mengk): figure out a longer term solution for this

        # existing_runs = await self.count_collection_agent_runs(ctx.collection_id)
        # agent_run_limit = 1_000_000
        # if existing_runs + new_runs > agent_run_limit:
        #     raise ValueError(
        #         f"Number of agent runs in the current collection is too large. Current limit: {agent_run_limit}, Current count: {existing_runs}, New runs: {new_runs}"
        #     )

        return

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

        # Extract metadata observations
        metadata_observations = extract_metadata_observations_bulk(
            agent_run_data, ctx.collection_id
        )

        # Insert all rows in a single transaction using add_all
        async with self.db.session() as session:
            session.add_all(agent_run_data)
            session.add_all(transcript_group_data)
            await (
                session.flush()
            )  # (mengk) seems necessary to avoid FK violations, for some strange reason
            session.add_all(transcript_data)
            session.add_all(metadata_observations)

        logger.info(
            f"Added {len(agent_runs)} agent runs, {len(transcript_data)} transcripts, "
            f"{len(transcript_group_data)} transcript groups, and {len(metadata_observations)} metadata observations"
        )

        await self.schedule_metadata_view_refresh()

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
            f"(transcripts, transcript groups, and metadata observations deleted via CASCADE)"
        )

        await self.schedule_metadata_view_refresh()

        return deleted_count

    async def update_agent_run_metadata(
        self,
        collection_id: str,
        agent_run_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge the provided metadata into an agent run's existing metadata.

        Uses the same deep-merge strategy as tracing: nested dicts are merged
        recursively so existing keys are preserved, while non-dict values are
        overwritten.

        Returns the full merged metadata dict.
        """
        async with self.db.session() as session:
            row = (
                await session.execute(
                    select(SQLAAgentRun.metadata_json)
                    .where(
                        SQLAAgentRun.id == agent_run_id,
                        SQLAAgentRun.collection_id == collection_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()

            if row is None:
                raise NotFoundError(
                    f"Agent run {agent_run_id} not found in collection {collection_id}"
                )

            existing: dict[str, Any] = row[0] or {}
            deep_merge_dicts(existing, metadata)
            merged = existing

            await session.execute(
                update(SQLAAgentRun)
                .where(
                    SQLAAgentRun.id == agent_run_id,
                    SQLAAgentRun.collection_id == collection_id,
                )
                .values(metadata_json=merged)
            )
            await session.commit()

        logger.info(f"Updated metadata for agent run {agent_run_id} in collection {collection_id}")
        return merged

    async def delete_agent_run_metadata_keys(
        self,
        collection_id: str,
        agent_run_id: str,
        keys: list[str],
    ) -> tuple[dict[str, Any], list[str]]:
        """Remove keys from an agent run's metadata.

        Supports dot-delimited paths for nested deletion (e.g.
        ``"experimental_config.baseline_forecast"`` removes just that nested
        key).  Plain keys delete at the top level.

        Returns a tuple of (metadata after deletion, keys that were not found).
        """
        if not keys:
            raise BadRequestError("keys must not be empty")

        async with self.db.session() as session:
            row = (
                await session.execute(
                    select(SQLAAgentRun.metadata_json)
                    .where(
                        SQLAAgentRun.id == agent_run_id,
                        SQLAAgentRun.collection_id == collection_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()

            if row is None:
                raise NotFoundError(
                    f"Agent run {agent_run_id} not found in collection {collection_id}"
                )

            existing: dict[str, Any] = row[0] or {}
            not_found: list[str] = []

            for key in keys:
                parts = key.split(".")
                target: dict[str, Any] = existing
                found = True
                for part in parts[:-1]:
                    nested = target.get(part)
                    if not isinstance(nested, dict):
                        found = False
                        break
                    target = nested
                else:
                    if parts[-1] not in target:
                        found = False

                if found:
                    target.pop(parts[-1], None)
                else:
                    not_found.append(key)

            await session.execute(
                update(SQLAAgentRun)
                .where(
                    SQLAAgentRun.id == agent_run_id,
                    SQLAAgentRun.collection_id == collection_id,
                )
                .values(metadata_json=existing)
            )
            await session.commit()

        logger.info(
            f"Deleted metadata keys {keys} from agent run {agent_run_id} "
            f"in collection {collection_id} (not found: {not_found})"
        )
        return existing, not_found

    async def move_agent_run(
        self,
        agent_run_id: str,
        source_collection_id: str,
        destination_collection_id: str,
    ) -> None:
        """
        Move an agent run from one collection to another.

        This updates the collection_id in agent_runs, transcripts, and transcript_groups.
        It will fail if there are any related rows in other tables (labels, tags, search results,
        judge results, etc.) that would become orphaned or inconsistent.

        Args:
            agent_run_id: The ID of the agent run to move
            source_collection_id: The collection the agent run currently belongs to
            destination_collection_id: The collection to move the agent run to

        Raises:
            ValueError: If agent run not found, or has related data in other tables
        """
        from docent_core.docent.db.schemas.label import SQLAComment, SQLALabel, SQLATag
        from docent_core.docent.db.schemas.rubric import (
            SQLAJudgeReflection,
            SQLAJudgeResult,
            SQLAJudgeRunLabel,
        )

        async with self.db.session() as session:
            # 1. Verify agent run exists in source collection
            agent_run_result = await session.execute(
                select(SQLAAgentRun).where(
                    SQLAAgentRun.id == agent_run_id,
                    SQLAAgentRun.collection_id == source_collection_id,
                )
            )
            sq_agent_run = agent_run_result.scalar_one_or_none()
            if sq_agent_run is None:
                raise NotFoundError(
                    f"Agent run {agent_run_id} not found in collection {source_collection_id}"
                )

            # 2. Check for blocking rows in related tables
            # These tables have agent_run_id and would become inconsistent if we just moved the agent run
            blocking_tables: list[tuple[str, type]] = [
                ("telemetry_agent_run_status", SQLATelemetryAgentRunStatus),
                ("transcript_embeddings", SQLATranscriptEmbedding),
                ("search_results", SQLASearchResult),
                ("telemetry_lineage", SQLATelemetryLineage),
                ("labels", SQLALabel),
                ("annotations", SQLAComment),
                ("tags", SQLATag),
                ("judge_run_labels", SQLAJudgeRunLabel),
                ("judge_results", SQLAJudgeResult),
                ("judge_reflections", SQLAJudgeReflection),
                ("chat_sessions", SQLAChatSession),
            ]

            # Build a single query with EXISTS subqueries for each table (1 round trip instead of 11)
            exists_checks = [
                exists(
                    select(literal(1)).where(
                        table_class.agent_run_id == agent_run_id  # type: ignore[attr-defined]
                    )
                ).label(table_name)
                for table_name, table_class in blocking_tables
            ]

            result = await session.execute(select(*exists_checks))
            row = result.one()

            blocking_found = [
                table_name for table_name, _ in blocking_tables if getattr(row, table_name)
            ]

            if blocking_found:
                raise ConflictError(
                    f"Cannot move agent run {agent_run_id} because it has related data in: "
                    f"{', '.join(blocking_found)}. "
                    "Delete or move the related data first."
                )

            # 3. Update collection_id in agent_runs, transcripts, transcript_groups
            await session.execute(
                update(SQLAAgentRun)
                .where(SQLAAgentRun.id == agent_run_id)
                .values(collection_id=destination_collection_id)
            )

            await session.execute(
                update(SQLATranscript)
                .where(SQLATranscript.agent_run_id == agent_run_id)
                .values(collection_id=destination_collection_id)
            )

            await session.execute(
                update(SQLATranscriptGroup)
                .where(SQLATranscriptGroup.agent_run_id == agent_run_id)
                .values(collection_id=destination_collection_id)
            )

            await session.execute(
                update(SQLAMetadataObservation)
                .where(SQLAMetadataObservation.agent_run_id == agent_run_id)
                .values(collection_id=destination_collection_id)
            )

            await session.commit()

        await self.schedule_metadata_view_refresh()

        logger.info(
            f"Moved agent run {agent_run_id} from collection {source_collection_id} "
            f"to collection {destination_collection_id}"
        )

    async def get_agent_run_ids(
        self,
        ctx: ViewContext,
        sort_field: str | None = None,
        sort_direction: Literal["asc", "desc"] = "asc",
        limit: int | None = None,
        offset: int = 0,
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
            query = select(SQLAAgentRun.id)
            query = ctx.apply_base_filter(query)

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
                elif sort_field == "tag":
                    tag_subquery = (
                        select(
                            SQLATag.agent_run_id.label("agent_run_id"),
                            func.string_agg(
                                aggregate_order_by(SQLATag.value, SQLATag.value),
                                literal(","),
                            ).label("tag_sort"),
                        )
                        .where(SQLATag.collection_id == ctx.collection_id)
                        .group_by(SQLATag.agent_run_id)
                        .subquery()
                    )
                    query = query.outerjoin(
                        tag_subquery, tag_subquery.c.agent_run_id == SQLAAgentRun.id
                    )
                    sort_expr = tag_subquery.c.tag_sort
                elif sort_field.startswith("label."):
                    parts = sort_field.split(".")
                    if len(parts) < 3:
                        raise ValueError("Label sort fields must include a JSON field path.")
                    label_set_id = parts[1]
                    json_path_parts = parts[2:]
                    for part in json_path_parts:
                        if not part.replace("_", "").replace("-", "").isalnum():
                            raise ValueError("Invalid label field path")

                    label_expr = SQLALabel.label_value
                    for part in json_path_parts[:-1]:
                        label_expr = label_expr.op("->")(part)
                    label_expr = label_expr.op("->>")(json_path_parts[-1])

                    label_subquery = (
                        select(
                            SQLALabel.agent_run_id.label("agent_run_id"),
                            label_expr.label("label_sort"),
                        )
                        .where(SQLALabel.label_set_id == label_set_id)
                        .subquery()
                    )
                    query = query.outerjoin(
                        label_subquery, label_subquery.c.agent_run_id == SQLAAgentRun.id
                    )
                    sort_expr = label_subquery.c.label_sort
                elif sort_field.startswith("rubric."):
                    parts = sort_field.split(".")
                    if len(parts) < 3:
                        raise ValueError("Rubric sort fields must include a JSON field path.")
                    rubric_id = parts[1]
                    json_path_parts = parts[2:]
                    for part in json_path_parts:
                        if not part.replace("_", "").replace("-", "").isalnum():
                            raise ValueError("Invalid rubric field path")

                    rubric_expr = SQLAJudgeResult.output
                    for part in json_path_parts[:-1]:
                        rubric_expr = rubric_expr.op("->")(part)
                    rubric_expr = rubric_expr.op("->>")(json_path_parts[-1])

                    latest_version_subquery = (
                        select(func.max(SQLARubric.version))
                        .where(
                            SQLARubric.id == rubric_id,
                            SQLARubric.collection_id == ctx.collection_id,
                        )
                        .scalar_subquery()
                    )

                    rubric_counts = (
                        select(
                            SQLAJudgeResult.agent_run_id.label("agent_run_id"),
                            rubric_expr.label("value"),
                            func.count().label("value_count"),
                        )
                        .where(
                            SQLAJudgeResult.rubric_id == rubric_id,
                            SQLAJudgeResult.rubric_version == latest_version_subquery,
                            SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
                        )
                        .group_by(SQLAJudgeResult.agent_run_id, rubric_expr)
                        .subquery()
                    )
                    rubric_ranked = select(
                        rubric_counts.c.agent_run_id,
                        rubric_counts.c.value.label("rubric_sort"),
                        func.row_number()
                        .over(
                            partition_by=rubric_counts.c.agent_run_id,
                            order_by=(
                                rubric_counts.c.value_count.desc(),
                                rubric_counts.c.value.asc().nulls_last(),
                            ),
                        )
                        .label("value_rank"),
                    ).subquery()
                    rubric_modal = (
                        select(
                            rubric_ranked.c.agent_run_id,
                            rubric_ranked.c.rubric_sort,
                        )
                        .where(rubric_ranked.c.value_rank == 1)
                        .subquery()
                    )
                    query = query.outerjoin(
                        rubric_modal, rubric_modal.c.agent_run_id == SQLAAgentRun.id
                    )
                    sort_expr = rubric_modal.c.rubric_sort
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

            # Apply offset and limit if specified
            if offset > 0:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)

            _log_compiled_query("agent_run_ids", query)
            result = await session.execute(query)
            agent_run_ids = result.scalars().all()
            return list(agent_run_ids)

    async def get_agent_runs(
        self,
        ctx: ViewContext | None = None,
        agent_run_ids: list[str] | None = None,
        limit: int | None = None,
        batch_size: int = 10_000,
    ) -> list[AgentRun]:
        """
        Get all agent runs for a given Collection ID.
        TODO(ryan, mengk): ctx is optional because multi-run chat could have items from
            different collections. We should figure out a way to make this more explicit.
        """
        async with self.db.session() as session:
            # If we don't have the agent run ids, get them first
            if agent_run_ids is None:
                assert ctx is not None  # Already checked above, but helps type checker
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

                query = select(SQLAAgentRun)
                if ctx is not None:
                    query = query.where(SQLAAgentRun.collection_id == ctx.collection_id)
                # TODO(mengk): use LIMIT and OFFSET instead of the IDs
                query = query.where(SQLAAgentRun.id.in_(batch_ids))

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

    async def get_transcripts_by_ids(
        self, transcript_ids: Sequence[str] | None, batch_size: int = 10_000
    ) -> list[Transcript]:
        """Fetch transcripts by their IDs without loading parent agent runs."""
        if not transcript_ids:
            return []

        unique_ids = list(dict.fromkeys(transcript_ids))
        transcripts_raw: list[SQLATranscript] = []

        async with self.db.session() as session:
            for i in range(0, len(unique_ids), batch_size):
                batch_ids = unique_ids[i : i + batch_size]
                result = await session.execute(
                    select(SQLATranscript).where(SQLATranscript.id.in_(batch_ids))
                )
                transcripts_raw.extend(result.scalars().all())

        return [t_raw.to_transcript() for t_raw in transcripts_raw]

    async def get_otel_message_ids_by_transcript_ids(
        self, *, collection_id: str, transcript_ids: Sequence[str]
    ) -> dict[str, list[str]]:
        """
        Return a mapping of transcript_id -> message_ids that have linked OpenTelemetry span payloads.

        The mapping is derived from telemetry lineage entries created during telemetry processing and
        is used by the UI to hide telemetry affordances for messages without available data.
        """
        unique_transcript_ids = [tid for tid in dict.fromkeys(transcript_ids) if tid]
        if not unique_transcript_ids:
            return {}

        async with self.db.session() as session:
            stmt = (
                select(SQLATelemetryLineage.derived_id, SQLATelemetryLineage.derived_key)
                .where(
                    SQLATelemetryLineage.collection_id == collection_id,
                    SQLATelemetryLineage.derived_type == "transcript_message",
                    SQLATelemetryLineage.derived_id.in_(unique_transcript_ids),
                    SQLATelemetryLineage.derived_key != "",
                    SQLATelemetryLineage.telemetry_accumulation_id.is_not(None),
                )
                .distinct()
                .order_by(
                    SQLATelemetryLineage.derived_id.asc(),
                    SQLATelemetryLineage.derived_key.asc(),
                )
            )
            result = await session.execute(stmt)

        otel_message_ids_by_transcript_id: dict[str, list[str]] = {}
        for transcript_id, message_id in result.all():
            if not transcript_id or not message_id:
                continue
            otel_message_ids_by_transcript_id.setdefault(transcript_id, []).append(message_id)

        return otel_message_ids_by_transcript_id

    async def get_metadata_for_agent_runs(
        self,
        ctx: ViewContext,
        agent_run_ids: list[str],
        apply_base_filter: bool = True,
        fields: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Efficiently fetch only metadata for the specified agent run IDs.

        This avoids loading transcripts and transcript groups, which can be expensive.

        Args:
            ctx: View context used to apply base filters and permissions.
            agent_run_ids: List of agent run IDs to fetch metadata for.
            apply_base_where_clause: Whether to apply the base where clause.
            fields: Optional list of additional fields to include.

        Returns:
            Mapping of agent_run_id -> structured metadata dict with:
            - metadata: actual JSON metadata from the database
            - created_at: timestamp as direct key
            - agent_run_id: the run ID as direct key
        """
        if not agent_run_ids:
            return {}

        requested_fields = set(fields or [])
        include_tags = "tag" in requested_fields
        label_fields: dict[str, list[list[str]]] = {}
        rubric_fields: dict[str, list[list[str]]] = {}

        for field_name in requested_fields:
            parts = field_name.split(".")
            if parts[0] == "label" and len(parts) >= 3:
                label_fields.setdefault(parts[1], []).append(parts[2:])
            elif parts[0] == "rubric" and len(parts) >= 3:
                rubric_fields.setdefault(parts[1], []).append(parts[2:])

        metadata_map: dict[str, dict[str, Any]] = {}

        async with self.db.session() as session:
            latest_rubric_versions: dict[str, int] = {}
            if rubric_fields:
                rubric_result = await session.execute(
                    select(SQLARubric.id, func.max(SQLARubric.version))
                    .where(
                        SQLARubric.collection_id == ctx.collection_id,
                        SQLARubric.id.in_(list(rubric_fields.keys())),
                    )
                    .group_by(SQLARubric.id)
                )
                latest_rubric_versions = {
                    rubric_id: version
                    for rubric_id, version in rubric_result.all()
                    if version is not None
                }

            # Use batching to avoid exceeding database parameter limits
            batch_size = 10_000
            for i in range(0, len(agent_run_ids), batch_size):
                batch_ids = agent_run_ids[i : i + batch_size]
                batch_index = i // batch_size

                query = select(SQLAAgentRun.id, SQLAAgentRun.metadata_json, SQLAAgentRun.created_at)
                if apply_base_filter:
                    query = ctx.apply_base_filter(query)
                else:
                    query = query.where(SQLAAgentRun.collection_id == ctx.collection_id)
                # TODO(mengk): use LIMIT and OFFSET instead of the IDs
                query = query.where(SQLAAgentRun.id.in_(batch_ids))

                _log_compiled_query(f"agent_run_metadata:{batch_index}", query)
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

                if include_tags:
                    tag_query = (
                        select(
                            SQLATag.agent_run_id,
                            func.array_agg(aggregate_order_by(SQLATag.value, SQLATag.value)).label(
                                "tag_values"
                            ),
                        )
                        .where(
                            SQLATag.collection_id == ctx.collection_id,
                            SQLATag.agent_run_id.in_(batch_ids),
                        )
                        .group_by(SQLATag.agent_run_id)
                    )
                    _log_compiled_query(f"agent_run_metadata_tags:{batch_index}", tag_query)
                    tag_result = await session.execute(tag_query)
                    for run_id, tag_values in tag_result.all():
                        if not tag_values:
                            continue
                        structured_metadata = metadata_map.setdefault(
                            run_id, {"agent_run_id": run_id, "metadata": {}}
                        )
                        structured_metadata["tag"] = list(tag_values)

                for label_set_id, paths in label_fields.items():
                    label_query = select(SQLALabel.agent_run_id, SQLALabel.label_value).where(
                        SQLALabel.label_set_id == label_set_id,
                        SQLALabel.agent_run_id.in_(batch_ids),
                    )
                    _log_compiled_query(
                        f"agent_run_metadata_labels:{label_set_id}:{batch_index}",
                        label_query,
                    )
                    label_result = await session.execute(label_query)
                    for run_id, label_value in label_result.all():
                        structured_metadata = metadata_map.setdefault(
                            run_id, {"agent_run_id": run_id, "metadata": {}}
                        )
                        for path in paths:
                            field_key = f"label.{label_set_id}." + ".".join(path)
                            structured_metadata[field_key] = _get_json_path_value(
                                label_value or {}, path
                            )

                if rubric_fields and latest_rubric_versions:
                    rubric_pairs = [
                        (rubric_id, latest_version)
                        for rubric_id, latest_version in latest_rubric_versions.items()
                    ]
                    rubric_query = select(
                        SQLAJudgeResult.agent_run_id,
                        SQLAJudgeResult.rubric_id,
                        SQLAJudgeResult.output,
                    ).where(
                        SQLAJudgeResult.agent_run_id.in_(batch_ids),
                        SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
                        tuple_(
                            SQLAJudgeResult.rubric_id,
                            SQLAJudgeResult.rubric_version,
                        ).in_(rubric_pairs),
                    )
                    _log_compiled_query(f"agent_run_metadata_rubric:{batch_index}", rubric_query)
                    rubric_result = await session.execute(rubric_query)
                    outputs_by_run: dict[tuple[str, str], list[dict[str, Any]]] = {}
                    for run_id, rubric_id, output in rubric_result.all():
                        outputs_by_run.setdefault((run_id, rubric_id), []).append(output)

                    for (run_id, rubric_id), outputs in outputs_by_run.items():
                        paths = rubric_fields.get(rubric_id)
                        if not paths or not outputs:
                            continue
                        structured_metadata = metadata_map.setdefault(
                            run_id, {"agent_run_id": run_id, "metadata": {}}
                        )
                        rubric_counts = structured_metadata.setdefault("_rubric_counts", {})
                        total_rollouts = len(outputs)
                        for path in paths:
                            field_key = f"rubric.{rubric_id}." + ".".join(path)
                            values = [_get_json_path_value(output, path) for output in outputs]
                            modal_value, modal_count = _pick_modal_value(values)
                            structured_metadata[field_key] = modal_value
                            rubric_counts[field_key] = {
                                "matched": modal_count,
                                "total": total_rollouts,
                            }

        return metadata_map

    async def resync_metadata(self, collection_id: str) -> int:
        """Delete all existing metadata observations for a collection and re-extract from agent runs."""
        async with self.db.session() as session:
            # Delete existing observations for this collection
            await session.execute(
                delete(SQLAMetadataObservation).where(
                    SQLAMetadataObservation.collection_id == collection_id
                )
            )
            await session.flush()

            # Fetch all agent runs for this collection
            result = await session.execute(
                select(SQLAAgentRun).where(SQLAAgentRun.collection_id == collection_id)
            )
            sq_agent_runs = list(result.scalars().all())

            # Re-extract observations
            observations = extract_metadata_observations_bulk(sq_agent_runs, collection_id)
            session.add_all(observations)

        logger.info(
            f"Resynced metadata for collection {collection_id}: "
            f"{len(sq_agent_runs)} agent runs, {len(observations)} observations"
        )

        return len(observations)

    async def backfill_metadata(
        self,
        collection_id: str | None = None,
        agent_run_cursor: str | None = None,
        batch_size: int = 500,
    ) -> dict[str, str | int | None]:
        """Backfill metadata observations for one batch of agent runs.

        Processes up to `batch_size` agent runs within a collection, using
        INSERT ON CONFLICT DO NOTHING to avoid duplicates. Returns cursors
        so the caller can paginate through all runs and collections.
        """
        async with self.db.session() as session:
            if collection_id is None:
                result = await session.execute(
                    select(SQLACollection.id).order_by(SQLACollection.id.asc()).limit(1)
                )
                collection_id = result.scalar_one_or_none()
                if collection_id is None:
                    return {
                        "collection_id": None,
                        "observations_created": 0,
                        "next_agent_run_cursor": None,
                        "next_collection_id": None,
                    }

            # Fetch a batch of agent runs, ordered by ID for stable cursor pagination
            query = (
                select(SQLAAgentRun)
                .where(SQLAAgentRun.collection_id == collection_id)
                .order_by(SQLAAgentRun.id.asc())
                .limit(batch_size)
            )
            if agent_run_cursor is not None:
                query = query.where(SQLAAgentRun.id > agent_run_cursor)

            result = await session.execute(query)
            sq_agent_runs = list(result.scalars().all())

            # Extract and upsert observations in chunks to stay under asyncpg's
            # 32767 bind-parameter limit (8 columns per row → ~3500 rows per chunk).
            observations = extract_metadata_observations_bulk(sq_agent_runs, collection_id)
            chunk_size = 3500
            for i in range(0, len(observations), chunk_size):
                chunk = observations[i : i + chunk_size]
                stmt = (
                    pg_insert(SQLAMetadataObservation)
                    .values(
                        [
                            {
                                "agent_run_id": o.agent_run_id,
                                "json_path": o.json_path,
                                "value_hash": o.value_hash,
                                "value_type": o.value_type,
                                "collection_id": o.collection_id,
                                "value_text": o.value_text,
                                "value_numeric": o.value_numeric,
                                "observed_at": o.observed_at,
                            }
                            for o in chunk
                        ]
                    )
                    .on_conflict_do_nothing()
                )
                await session.execute(stmt)

        # Determine next cursor
        next_agent_run_cursor: str | None = None
        next_collection_id: str | None = None

        if len(sq_agent_runs) == batch_size:
            # More runs in this collection
            next_agent_run_cursor = sq_agent_runs[-1].id
            next_collection_id = collection_id
        else:
            # Done with this collection, find the next one
            async with self.db.session() as session:
                result = await session.execute(
                    select(SQLACollection.id)
                    .where(SQLACollection.id > collection_id)
                    .order_by(SQLACollection.id.asc())
                    .limit(1)
                )
                next_collection_id = result.scalar_one_or_none()

        logger.info(
            f"Backfilled metadata for collection {collection_id}: "
            f"{len(sq_agent_runs)} agent runs, {len(observations)} observations"
        )

        return {
            "collection_id": collection_id,
            "observations_created": len(observations),
            "next_agent_run_cursor": next_agent_run_cursor,
            "next_collection_id": next_collection_id,
        }

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

    async def check_agent_run_in_collection(self, collection_id: str, agent_run_id: str) -> None:
        """Verify that an agent run belongs to the specified collection.

        Args:
            collection_id: The collection ID to verify against
            agent_run_id: The agent run ID to check

        Raises:
            ValueError: If the agent run doesn't exist or belongs to another collection
        """
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAAgentRun.collection_id).where(SQLAAgentRun.id == agent_run_id)
            )
            agent_run_collection_id = result.scalar_one_or_none()
            if agent_run_collection_id is None or agent_run_collection_id != collection_id:
                raise ValueError(
                    f"Agent run {agent_run_id} not found in collection {collection_id}"
                )

    async def get_agent_run(self, ctx: ViewContext, agent_run_id: str) -> AgentRun | None:
        """
        Get an AgentRun from the database by its ID.

        Args:
            ctx: The ViewContext to use for the query.
            agent_run_id: The ID of the agent run to get.

        Returns:
            The agent run.
        """
        agent_runs = await self.get_agent_runs(ctx, agent_run_ids=[agent_run_id])
        assert len(agent_runs) <= 1, f"Found {len(agent_runs)} AgentRuns with ID {agent_run_id}"
        return agent_runs[0] if agent_runs else None

    async def get_unique_field_values(
        self,
        ctx: ViewContext,
        field_name: str,
        search: str | None = None,
        limit: int = 100,
        filter_obj: CollectionFilter | None = None,
    ) -> list[str]:
        """
        Get unique values for a specific metadata field from agent runs in the collection.

        Args:
            ctx: The ViewContext to use for the query.
            field_name: The field name (e.g., "metadata.task_id")
            search: Optional search term to filter values (case-insensitive substring match)
            limit: Maximum number of unique values to return (default 100)
            filter_obj: Optional filter to scope the available values

        Returns:
            List of unique string values for the field
        """
        async with self.db.session() as session:
            field_parts = field_name.split(".")

            def apply_agent_run_filter(query: Select[Any]) -> Select[Any]:
                if filter_obj is None:
                    return query

                filter_ctx = FilterSQLContext(SQLAAgentRun)
                filter_clause = filter_obj.to_sqla_where_clause(
                    SQLAAgentRun,
                    context=filter_ctx,
                )
                for join_spec in filter_ctx.required_joins():
                    query = query.outerjoin(join_spec.alias, join_spec.onclause)
                if filter_clause is not None:
                    query = query.where(filter_clause)
                return query

            # Metadata
            if field_parts[0] == "metadata" and len(field_parts) > 1:
                json_path_parts = field_parts[1:]
                for part in json_path_parts:
                    if not part.replace("_", "").replace("-", "").isalnum():
                        return []

                field_expr = SQLAAgentRun.metadata_json
                for part in json_path_parts[:-1]:
                    field_expr = field_expr.op("->")(part)
                field_expr = field_expr.op("->>")(json_path_parts[-1])

                query = select(func.distinct(field_expr)).where(
                    SQLAAgentRun.collection_id == ctx.collection_id,
                    field_expr.isnot(None),
                )
                query = apply_agent_run_filter(query)

                if search:
                    query = query.where(field_expr.ilike(func.concat("%", search, "%")))

                # Limit number of results to prevent excessive output
                query = query.limit(limit)

                result = await session.execute(query)
                values = [row[0] for row in result.fetchall() if row[0] is not None]
                return sorted(values)

            # Tags
            elif field_parts[0] == "tag" and len(field_parts) == 1:
                tag_value_expr = SQLATag.value
                query = (
                    select(func.distinct(tag_value_expr))
                    .select_from(SQLATag)
                    .join(SQLAAgentRun, SQLAAgentRun.id == SQLATag.agent_run_id)
                    .where(
                        SQLATag.collection_id == ctx.collection_id,
                        SQLAAgentRun.collection_id == ctx.collection_id,
                        tag_value_expr.isnot(None),
                    )
                )
                query = apply_agent_run_filter(query)

                if search:
                    query = query.where(tag_value_expr.ilike(func.concat("%", search, "%")))

                query = query.limit(limit)

                result = await session.execute(query)
                values = [row[0] for row in result.fetchall() if row[0] is not None]
                return sorted(values)

            # Labels
            elif field_parts[0] == "label" and len(field_parts) >= 3:
                label_set_id = field_parts[1]
                json_path_parts = field_parts[2:]
                for part in json_path_parts:
                    if not part.replace("_", "").replace("-", "").isalnum():
                        return []

                field_expr = SQLALabel.label_value
                for part in json_path_parts[:-1]:
                    field_expr = field_expr.op("->")(part)
                field_expr = field_expr.op("->>")(json_path_parts[-1])

                query = (
                    select(func.distinct(field_expr))
                    .select_from(SQLALabel)
                    .join(SQLAAgentRun, SQLAAgentRun.id == SQLALabel.agent_run_id)
                    .where(
                        SQLALabel.label_set_id == label_set_id,
                        SQLAAgentRun.collection_id == ctx.collection_id,
                        field_expr.isnot(None),
                    )
                )
                query = apply_agent_run_filter(query)

                if search:
                    query = query.where(field_expr.ilike(func.concat("%", search, "%")))

                query = query.limit(limit)

                result = await session.execute(query)
                values = [row[0] for row in result.fetchall() if row[0] is not None]
                return sorted(values)

            # Rubrics
            elif field_parts[0] == "rubric" and len(field_parts) >= 3:
                rubric_id = field_parts[1]
                json_path_parts = field_parts[2:]
                for part in json_path_parts:
                    if not part.replace("_", "").replace("-", "").isalnum():
                        return []

                field_expr = SQLAJudgeResult.output
                for part in json_path_parts[:-1]:
                    field_expr = field_expr.op("->")(part)
                field_expr = field_expr.op("->>")(json_path_parts[-1])

                latest_version_subquery = (
                    select(func.max(SQLARubric.version))
                    .where(
                        SQLARubric.id == rubric_id,
                        SQLARubric.collection_id == ctx.collection_id,
                    )
                    .scalar_subquery()
                )

                query = (
                    select(func.distinct(field_expr))
                    .select_from(SQLAJudgeResult)
                    .join(SQLAAgentRun, SQLAAgentRun.id == SQLAJudgeResult.agent_run_id)
                    .where(
                        SQLAJudgeResult.rubric_id == rubric_id,
                        SQLAJudgeResult.rubric_version == latest_version_subquery,
                        SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
                        field_expr.isnot(None),
                        SQLAAgentRun.collection_id == ctx.collection_id,
                    )
                )

                if filter_obj is not None:
                    uses_tags = filter_uses_tags(filter_obj)
                    uses_labels = filter_uses_labels(filter_obj)
                    label_set_ids: set[str] = (
                        collect_label_set_ids(filter_obj) if uses_labels else set()
                    )

                    tag_table = None
                    if uses_tags:
                        query = query.outerjoin(SQLATag, SQLATag.agent_run_id == SQLAAgentRun.id)
                        tag_table = SQLATag

                    label_tables: dict[str, Any] | None = None
                    if uses_labels:
                        label_tables = {}
                        for idx, label_set_id in enumerate(sorted(label_set_ids)):
                            label_alias = aliased(SQLALabel, name=f"label_filter_{idx}")
                            query = query.outerjoin(
                                label_alias,
                                and_(
                                    label_alias.agent_run_id == SQLAAgentRun.id,
                                    label_alias.label_set_id == label_set_id,
                                ),
                            )
                            label_tables[label_set_id] = label_alias

                    filter_clause = build_judge_result_filter_clause(
                        filter_obj,
                        rubric_id=rubric_id,
                        judge_result_table=SQLAJudgeResult,
                        agent_run_table=SQLAAgentRun,
                        tag_table=tag_table,
                        label_tables=label_tables,
                    )
                    if filter_clause is not None:
                        query = query.where(filter_clause)

                if search:
                    query = query.where(field_expr.ilike(func.concat("%", search, "%")))

                query = query.limit(limit)

                result = await session.execute(query)
                values = [row[0] for row in result.fetchall() if row[0] is not None]
                return sorted(values)

            else:
                return []

    async def get_field_value_samples(
        self,
        ctx: ViewContext,
        field_name: str,
        *,
        sample_limit: int = 10,
    ) -> tuple[list[FieldValueSample], int]:
        async with self.db.session() as session:
            field_parts = field_name.split(".")

            if field_parts[0] == "metadata" and len(field_parts) > 1:
                json_path_parts = field_parts[1:]
                for part in json_path_parts:
                    if not part.replace("_", "").replace("-", "").isalnum():
                        return ([], 0)

                field_expr = SQLAAgentRun.metadata_json
                for part in json_path_parts[:-1]:
                    field_expr = field_expr.op("->")(part)
                value_expr = field_expr.op("->>")(json_path_parts[-1])

                total_stmt = select(func.count(distinct(value_expr))).where(value_expr.isnot(None))
                total_stmt = ctx.apply_base_filter(total_stmt)

                samples_stmt = (
                    select(
                        value_expr.label("value"),
                        func.count(distinct(SQLAAgentRun.id)).label("count"),
                    )
                    .where(value_expr.isnot(None))
                    .group_by(value_expr)
                    .order_by(
                        func.count(distinct(SQLAAgentRun.id)).desc(),
                        value_expr.asc(),
                    )
                    .limit(sample_limit)
                )
                samples_stmt = ctx.apply_base_filter(samples_stmt)

                total_result = await session.execute(total_stmt)
                total_unique_values = int(total_result.scalar_one() or 0)

                sample_result = await session.execute(samples_stmt)
                sample_rows = sample_result.mappings().all()
                samples: list[FieldValueSample] = [
                    {"value": str(row["value"]), "count": int(row["count"])}
                    for row in sample_rows
                    if row["value"] is not None
                ]
                return (samples, total_unique_values)

            if field_parts[0] == "tag" and len(field_parts) == 1:
                value_expr = SQLATag.value
                total_stmt = (
                    select(func.count(distinct(value_expr)))
                    .select_from(SQLATag)
                    .join(SQLAAgentRun, SQLAAgentRun.id == SQLATag.agent_run_id)
                )
                total_stmt = total_stmt.where(
                    SQLATag.collection_id == ctx.collection_id,
                    value_expr.isnot(None),
                )
                total_stmt = ctx.apply_base_filter(total_stmt)

                samples_stmt = (
                    select(
                        value_expr.label("value"),
                        func.count(distinct(SQLATag.agent_run_id)).label("count"),
                    )
                    .select_from(SQLATag)
                    .join(SQLAAgentRun, SQLAAgentRun.id == SQLATag.agent_run_id)
                    .where(
                        SQLATag.collection_id == ctx.collection_id,
                        value_expr.isnot(None),
                    )
                    .group_by(value_expr)
                    .order_by(
                        func.count(distinct(SQLATag.agent_run_id)).desc(),
                        value_expr.asc(),
                    )
                    .limit(sample_limit)
                )
                samples_stmt = ctx.apply_base_filter(samples_stmt)

                total_result = await session.execute(total_stmt)
                total_unique_values = int(total_result.scalar_one() or 0)

                sample_result = await session.execute(samples_stmt)
                sample_rows = sample_result.mappings().all()
                samples = [
                    {"value": str(row["value"]), "count": int(row["count"])}
                    for row in sample_rows
                    if row["value"] is not None
                ]
                return (samples, total_unique_values)

            return ([], 0)

    async def count_base_agent_runs(self, ctx: ViewContext) -> int:
        async with self.db.session() as session:
            query = select(func.count()).select_from(SQLAAgentRun)
            query = ctx.apply_base_filter(query)

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
                assert isinstance(view.base_filter, ComplexFilter), (
                    "Base filter must be a ComplexFilter"
                )

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
            assert isinstance(view.base_filter, ComplexFilter), (
                f"Base filter must be a ComplexFilter, found {type(view.base_filter)}"
            )

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

    ###########
    # Filters #
    ###########

    async def create_filter_entry(
        self,
        *,
        collection_id: str,
        filter_payload: CollectionFilter,
        user: User,
        name: str | None = None,
        description: str | None = None,
    ) -> SQLAFilter:
        """Persist a filter definition for later reuse."""
        filter_dict = filter_payload.model_dump()
        # Validate payload before storing
        parse_filter_dict(deepcopy(filter_dict))
        filter_id = str(uuid4())

        async with self.db.session() as session:
            sqla_filter = SQLAFilter(
                id=filter_id,
                collection_id=collection_id,
                name=name,
                description=description,
                filter_dict=filter_dict,
                created_by=user.id,
            )
            session.add(sqla_filter)
            await session.flush()
            await session.refresh(sqla_filter)
            return sqla_filter

    async def get_filter_entry(self, *, collection_id: str, filter_id: str) -> SQLAFilter | None:
        """Fetch a stored filter."""
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAFilter).where(
                    SQLAFilter.collection_id == collection_id, SQLAFilter.id == filter_id
                )
            )
            return result.scalar_one_or_none()

    async def list_filter_entries(self, *, collection_id: str) -> list[SQLAFilter]:
        """Return all stored filters for a collection ordered by creation time."""
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAFilter)
                .where(SQLAFilter.collection_id == collection_id)
                .order_by(SQLAFilter.updated_at.desc())
            )
            return list(result.scalars().all())

    async def delete_filter_entry(self, *, collection_id: str, filter_id: str) -> bool:
        """Delete a stored filter."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(SQLAFilter).where(
                    SQLAFilter.collection_id == collection_id, SQLAFilter.id == filter_id
                )
            )
            return bool(result.rowcount)

    async def update_filter_entry(
        self,
        *,
        collection_id: str,
        filter_id: str,
        filter_payload: CollectionFilter | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> SQLAFilter | None:
        """Update an existing filter entry."""
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAFilter).where(
                    SQLAFilter.collection_id == collection_id,
                    SQLAFilter.id == filter_id,
                )
            )
            sqla_filter = result.scalar_one_or_none()
            if sqla_filter is None:
                return None

            # Update fields if provided
            if filter_payload is not None:
                filter_dict = filter_payload.model_dump()
                # Validate payload before storing
                parse_filter_dict(deepcopy(filter_dict))
                sqla_filter.filter_dict = filter_dict

            if name is not None:
                sqla_filter.name = name

            if description is not None:
                sqla_filter.description = description

            await session.flush()
            await session.refresh(sqla_filter)
            return sqla_filter

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

    async def add_telemetry_processing_job(
        self,
        collection_id: str,
        user: User,
        *,
        agent_run_id: str | None = None,
        force: bool = False,
    ) -> str | None:
        """
        Adds a telemetry processing job for the given collection (or specific agent run).
        Only adds the job if there isn't already a pending job for the same scope.

        Args:
            collection_id: The collection ID to process
            agent_run_id: Optional agent run ID to scope the job
            user: The user who initiated the processing
            force: When True, permit creating a new job even if an existing one is running

        Returns:
            The job ID if created, None if job already exists
        """
        async with self.db.session() as session:
            # Check if there's already a pending job for this collection
            statuses_to_block: list[JobStatus] = [JobStatus.PENDING]
            if not force:
                statuses_to_block.append(JobStatus.RUNNING)

            existing_job_query = select(SQLAJob).where(
                SQLAJob.type == "telemetry_processing_job",
                SQLAJob.status.in_(statuses_to_block),
                SQLAJob.job_json["collection_id"].astext == collection_id,
            )
            if agent_run_id is None:
                existing_job_query = existing_job_query.where(
                    SQLAJob.job_json["agent_run_id"].is_(None)
                )
            else:
                existing_job_query = existing_job_query.where(
                    SQLAJob.job_json["agent_run_id"].astext == agent_run_id
                )

            existing_job_result = await session.execute(existing_job_query)
            existing_jobs = existing_job_result.scalars().all()

            if existing_jobs:
                # Log all existing jobs for debugging
                job_ids = [job.id for job in existing_jobs]
                logger.debug(
                    "Telemetry processing job(s) already exist for collection %s%s: %s (statuses: %s)",
                    collection_id,
                    f" agent_run_id={agent_run_id}" if agent_run_id else "",
                    job_ids,
                    [job.status for job in existing_jobs],
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
                        "agent_run_id": agent_run_id,
                        "user_id": user.id,
                        "user_email": user.email,
                        "user_organization_ids": user.organization_ids,
                    },
                )
            )
            logger.info(
                "Added telemetry processing job %s for collection %s%s",
                job_id,
                collection_id,
                f" agent_run_id={agent_run_id}" if agent_run_id else "",
            )

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
        await enqueue_job(ctx, job_id, job_type=WorkerFunction.TELEMETRY_INGEST_JOB)  # type: ignore
        logger.info(
            "Enqueued telemetry ingest job %s for telemetry_log_id %s (request_id=%s)",
            job_id,
            telemetry_log_id,
            request_id,
        )
        return job_id

    async def add_and_enqueue_telemetry_processing_job(
        self,
        collection_id: str,
        user: User,
        *,
        agent_run_id: str | None = None,
        force: bool = False,
    ) -> str | None:
        """
        Adds a telemetry processing job for the given collection and enqueues it to Redis.
        Only adds the job if there isn't already a pending job for this collection.

        Args:
            collection_id: The collection ID to process
            agent_run_id: Optional agent run ID to scope the job
            user: The user who initiated the processing
            force: When True, allow scheduling another job even if one is currently running

        Returns:
            The job ID if created and enqueued, None if job already exists
        """
        # Create or reuse a job in the database
        job_id = await self.add_telemetry_processing_job(
            collection_id, user, agent_run_id=agent_run_id, force=force
        )
        if job_id is None:
            # Verify if an existing pending job is already enqueued; if not, enqueue it
            async with self.db.session() as session:
                pending_job_query = (
                    select(SQLAJob)
                    .where(
                        SQLAJob.type == "telemetry_processing_job",
                        SQLAJob.job_json["collection_id"].astext == collection_id,
                        (
                            SQLAJob.job_json["agent_run_id"].astext == agent_run_id
                            if agent_run_id is not None
                            else SQLAJob.job_json["agent_run_id"].is_(None)
                        ),
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
                    queue_name = get_queue_name_for_job_type(
                        WorkerFunction.TELEMETRY_PROCESSING_JOB
                    )
                    if await redis_client.zscore(queue_name, job_id) is not None:  # type: ignore[arg-type]
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
            await enqueue_job(ctx, job_id, job_type=WorkerFunction.TELEMETRY_PROCESSING_JOB)  # type: ignore
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

    async def get_jobs(self, job_ids: list[str]) -> list[SQLAJob]:
        """
        Retrieve multiple jobs by their IDs.

        Args:
            job_ids: List of job IDs to retrieve.

        Returns:
            List of jobs found (may be fewer than requested if some don't exist).
        """
        if not job_ids:
            return []
        async with self.db.session() as session:
            result = await session.execute(select(SQLAJob).where(SQLAJob.id.in_(job_ids)))
            return list(result.scalars().all())

    async def get_agent_run_ingest_jobs(
        self, collection_id: str, limit: int = 100
    ) -> list[SQLAJob]:
        """
        Retrieve agent run ingestion jobs for a collection.

        Args:
            collection_id: The collection ID to filter jobs by.
            limit: Maximum number of jobs to return (default 100).

        Returns:
            List of agent run ingest jobs for the collection, ordered by creation time (newest first).
        """
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAJob)
                .where(
                    SQLAJob.type == WorkerFunction.AGENT_RUN_INGEST_JOB.value,
                    SQLAJob.job_json["collection_id"].astext == collection_id,
                )
                .order_by(SQLAJob.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def set_job_status(self, job_id: str, status: JobStatus):
        async with self.db.session() as session:
            await session.execute(
                update(SQLAJob).filter(SQLAJob.id == job_id).values(status=status)
            )

    async def set_job_runtime_info(self, job_id: str, runtime_info: dict[str, Any]):
        async with self.db.session() as session:
            await session.execute(
                update(SQLAJob).filter(SQLAJob.id == job_id).values(runtime_info=runtime_info)
            )

    async def set_job_json(self, job_id: str, job_json: dict[str, Any]):
        async with self.db.session() as session:
            await session.execute(
                update(SQLAJob).filter(SQLAJob.id == job_id).values(job_json=job_json)
            )

    async def enqueue_agent_run_ingest(
        self,
        collection_id: str,
        raw_body: bytes,
        content_encoding: str,
        ctx: ViewContext,
    ) -> str:
        """
        Create a job and payload for agent run ingestion, enqueue it for background processing.

        Args:
            collection_id: The collection to ingest agent runs into.
            raw_body: The raw request body (possibly compressed).
            content_encoding: The content encoding (e.g., "gzip" or "").
            ctx: The view context for enqueueing.

        Returns:
            The job_id for tracking the ingestion.
        """
        job_id = str(uuid4())
        payload_id = str(uuid4())

        job = SQLAJob(
            id=job_id,
            type=WorkerFunction.AGENT_RUN_INGEST_JOB.value,
            status=JobStatus.PENDING,
            job_json={
                "collection_id": collection_id,
                "payload_id": payload_id,
            },
        )
        payload = SQLAIngestionPayload(
            id=payload_id,
            job_id=job_id,
            payload=raw_body,
            content_encoding=content_encoding,
        )

        async with self.db.session() as session:
            session.add(job)
            await session.flush()  # Ensure the FK is available
            session.add(payload)
            await session.commit()

        # Enqueue the job for background processing
        await enqueue_job(ctx, job_id, job_type=WorkerFunction.AGENT_RUN_INGEST_JOB)

        logger.info(
            "Enqueued agent run ingest job %s for collection %s",
            job_id,
            collection_id,
        )

        return job_id

    async def retry_agent_run_ingest_job(
        self, job_id: str, collection_id: str, ctx: ViewContext
    ) -> None:
        """
        Retry a canceled agent run ingest job by resetting its status and re-enqueueing it.

        Args:
            job_id: The ID of the job to retry.
            collection_id: The collection ID the job should belong to.
            ctx: The view context for enqueueing.

        Raises:
            ValueError: If validation fails (job not found, wrong collection, wrong type,
                wrong status, or missing payload).
        """
        job = await self.get_job(job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")

        job_collection_id = job.job_json.get("collection_id") if job.job_json else None
        if job_collection_id != collection_id:
            raise NotFoundError(f"Job {job_id} not found in collection {collection_id}")

        if job.type != WorkerFunction.AGENT_RUN_INGEST_JOB.value:
            raise BadRequestError(f"Job {job_id} is not an agent run ingest job")

        if job.status != JobStatus.CANCELED:
            raise BadRequestError(
                f"Job {job_id} cannot be retried: status is {job.status.value}, expected CANCELED"
            )

        # Verify the payload still exists
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAIngestionPayload).where(SQLAIngestionPayload.job_id == job_id)
            )
            payload = result.scalar_one_or_none()
            if payload is None:
                raise BadRequestError(f"Job {job_id} cannot be retried: payload no longer exists")

            # Reset status to PENDING
            await session.execute(
                update(SQLAJob).where(SQLAJob.id == job_id).values(status=JobStatus.PENDING)
            )
            await session.commit()

        # Clear any existing arq job key to allow re-enqueueing with the same job ID
        await clear_arq_job_key(job_id)

        # Re-enqueue the job
        await enqueue_job(ctx, job_id, job_type=WorkerFunction.AGENT_RUN_INGEST_JOB)

        logger.info("Re-enqueued agent run ingest job %s for retry", job_id)

    #########
    # Users #
    #########

    async def get_users(self) -> list[User]:
        async with self.db.session() as session:
            # Get all users
            users_result = await session.execute(select(SQLAUser))
            sqla_users = users_result.scalars().all()

            return [user.to_user() for user in sqla_users]

    async def get_organizations_for_user(self, user_id: str) -> list[OrganizationWithRole]:
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAOrganization, SQLAUserOrganization.role)
                .join(
                    SQLAUserOrganization,
                    SQLAUserOrganization.organization_id == SQLAOrganization.id,
                )
                .where(SQLAUserOrganization.user_id == user_id)
                .order_by(SQLAOrganization.name.asc())
            )
            rows = result.all()

        return [
            OrganizationWithRole(
                id=org.id,
                name=org.name,
                description=org.description,
                my_role=OrganizationRole(role),
            )
            for org, role in rows
        ]

    async def get_users_in_organization(self, organization_id: str) -> list[User]:
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAOrganization)
                .options(selectinload(SQLAOrganization.users))
                .where(SQLAOrganization.id == organization_id)
            )
            org = result.scalar_one_or_none()
            if org is None:
                return []
            return [u.to_user() for u in org.users if not u.is_anonymous]

    async def get_organization_role(
        self, *, organization_id: str, user_id: str
    ) -> OrganizationRole | None:
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAUserOrganization.role).where(
                    SQLAUserOrganization.organization_id == organization_id,
                    SQLAUserOrganization.user_id == user_id,
                )
            )
            role = result.scalar_one_or_none()
            if role is None:
                return None
            return OrganizationRole(role)

    async def get_organization_members(self, organization_id: str) -> list[OrganizationMember]:
        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAUser, SQLAUserOrganization.role)
                .join(SQLAUserOrganization, SQLAUserOrganization.user_id == SQLAUser.id)
                .where(SQLAUserOrganization.organization_id == organization_id)
                .options(selectinload(SQLAUser.organizations))
                .order_by(SQLAUser.email.asc())
            )
            rows = result.all()

        members: list[OrganizationMember] = []
        for sqla_user, role in rows:
            if sqla_user.is_anonymous:
                continue
            members.append(
                OrganizationMember(
                    organization_id=organization_id,
                    user=sqla_user.to_user(),
                    role=OrganizationRole(role),
                )
            )
        return members

    async def create_organization(
        self,
        *,
        name: str,
        description: str | None,
        creator_user_id: str,
    ) -> OrganizationWithRole:
        org_id = str(uuid4())
        async with self.db.session() as session:
            session.add(
                SQLAOrganization(
                    id=org_id,
                    name=name,
                    description=description,
                )
            )
            # Ensure the org row exists before inserting the membership row (FK constraint).
            await session.flush()
            stmt = pg_insert(SQLAUserOrganization).values(
                organization_id=org_id,
                user_id=creator_user_id,
                role=OrganizationRole.ADMIN.value,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    SQLAUserOrganization.user_id,
                    SQLAUserOrganization.organization_id,
                ],
                set_={"role": OrganizationRole.ADMIN.value},
            )
            await session.execute(stmt)

        return OrganizationWithRole(
            id=org_id,
            name=name,
            description=description,
            my_role=OrganizationRole.ADMIN,
        )

    async def _count_organization_admins(self, organization_id: str) -> int:
        async with self.db.session() as session:
            result = await session.execute(
                select(func.count())
                .select_from(SQLAUserOrganization)
                .where(
                    SQLAUserOrganization.organization_id == organization_id,
                    SQLAUserOrganization.role == OrganizationRole.ADMIN.value,
                )
            )
            return int(result.scalar_one())

    async def ensure_not_last_org_admin(
        self,
        *,
        organization_id: str,
        target_user_id: str,
        target_role: OrganizationRole | None = None,
    ) -> None:
        role = target_role or await self.get_organization_role(
            organization_id=organization_id, user_id=target_user_id
        )
        if role != OrganizationRole.ADMIN:
            return
        admin_count = await self._count_organization_admins(organization_id)
        if admin_count <= 1:
            raise ValueError("Organization must have at least one admin")

    async def add_user_to_organization(
        self, *, organization_id: str, user_id: str, role: OrganizationRole
    ) -> None:
        async with self.db.session() as session:
            stmt = pg_insert(SQLAUserOrganization).values(
                organization_id=organization_id,
                user_id=user_id,
                role=role.value,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    SQLAUserOrganization.user_id,
                    SQLAUserOrganization.organization_id,
                ],
                set_={"role": role.value},
            )
            await session.execute(stmt)

    async def set_organization_member_role(
        self, *, organization_id: str, user_id: str, role: OrganizationRole
    ) -> None:
        async with self.db.session() as session:
            result = await session.execute(
                update(SQLAUserOrganization)
                .where(
                    SQLAUserOrganization.organization_id == organization_id,
                    SQLAUserOrganization.user_id == user_id,
                )
                .values(role=role.value)
            )
            if (result.rowcount or 0) <= 0:
                raise ValueError("User is not a member of the organization")

    async def remove_user_from_organization(self, *, organization_id: str, user_id: str) -> int:
        async with self.db.session() as session:
            result = await session.execute(
                delete(SQLAUserOrganization).where(
                    SQLAUserOrganization.organization_id == organization_id,
                    SQLAUserOrganization.user_id == user_id,
                )
            )
            return int(result.rowcount or 0)

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

    async def get_user_by_session_id(
        self, session_id: str, *, load_organizations: bool = True
    ) -> User | None:
        """
        Retrieve a user by their session ID.

        Args:
            session_id: The session ID to look up
            load_organizations: Whether to load the user's organizations. Set to False
                for endpoints like /rest/me that don't need organization data.

        Returns:
            The User object if the session is valid and active, None otherwise
        """
        async with self.db.session() as session:
            # Join session and user tables, check if session is active and not expired
            stmt = (
                select(SQLAUser)
                .join(SQLASession, SQLAUser.id == SQLASession.user_id)
                .where(
                    SQLASession.id == session_id,
                    SQLASession.is_active,
                    SQLASession.expires_at > datetime.now(UTC).replace(tzinfo=None),
                )
            )
            if not load_organizations:
                stmt = stmt.options(noload(SQLAUser.organizations))

            result = await session.execute(stmt)
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

    async def get_readable_collection_ids(
        self,
        user: User,
        collection_ids: set[str],
    ) -> set[str]:
        """Return the subset of collection_ids the user can READ.

        Uses a single query to check permissions on multiple collections at once.
        """
        if not collection_ids:
            return set()

        async with self.db.session() as session:
            result = await session.execute(
                select(SQLAAccessControlEntry.collection_id)
                .where(SQLAAccessControlEntry.collection_id.in_(collection_ids))
                .where(
                    or_(
                        SQLAAccessControlEntry.is_public,
                        SQLAAccessControlEntry.user_id == user.id,
                        SQLAAccessControlEntry.organization_id.in_(user.organization_ids or []),
                    )
                )
                .where(
                    SQLAAccessControlEntry.permission.in_(
                        [Permission.READ.value, Permission.WRITE.value, Permission.ADMIN.value]
                    )
                )
                .distinct()
            )
            return set(result.scalars().all())

    async def verify_context_access(
        self,
        user: User,
        spec: LLMContextSpec,
    ) -> None:
        """Verify user can access all items in a context spec.

        1. Batch query actual collection_ids for all referenced items
        2. Verify claimed collection_ids match actual
        3. Check user has READ permission on all collections

        Raises PermissionError if any check fails.
        """
        from docent.sdk.llm_context import AgentRunRef, ResultRef, TranscriptRef

        agent_run_refs: list[AgentRunRef] = []
        transcript_refs: list[TranscriptRef] = []
        result_refs: list[ResultRef] = []

        for ref in spec.items.values():
            if isinstance(ref, AgentRunRef):
                agent_run_refs.append(ref)
            elif isinstance(ref, TranscriptRef):
                transcript_refs.append(ref)
            else:
                result_refs.append(ref)

        actual_collections: dict[str, str] = {}

        async with self.db.session() as session:
            if agent_run_refs:
                agent_run_ids = [ref.id for ref in agent_run_refs]
                result = await session.execute(
                    select(SQLAAgentRun.id, SQLAAgentRun.collection_id).where(
                        SQLAAgentRun.id.in_(agent_run_ids)
                    )
                )
                for row in result.all():
                    actual_collections[row[0]] = row[1]

            if transcript_refs:
                transcript_ids = [ref.id for ref in transcript_refs]
                result = await session.execute(
                    select(SQLATranscript.id, SQLATranscript.collection_id).where(
                        SQLATranscript.id.in_(transcript_ids)
                    )
                )
                for row in result.all():
                    actual_collections[row[0]] = row[1]

            if result_refs:
                from docent_core.docent.db.schemas.result_tables import (
                    SQLAResult,
                    SQLAResultSet,
                )

                result_ids = [ref.id for ref in result_refs]
                result = await session.execute(
                    select(SQLAResult.id, SQLAResultSet.collection_id)
                    .join(SQLAResultSet, SQLAResult.result_set_id == SQLAResultSet.id)
                    .where(SQLAResult.id.in_(result_ids))
                )
                for row in result.all():
                    actual_collections[row[0]] = row[1]

        all_refs = [*agent_run_refs, *transcript_refs, *result_refs]
        claimed_collections: set[str] = set()

        for ref in all_refs:
            actual = actual_collections.get(ref.id)
            if actual is None:
                raise PermissionError(f"Item {ref.id} not found")
            if actual != ref.collection_id:
                raise PermissionError(
                    f"Item {ref.id} does not belong to claimed collection {ref.collection_id}"
                )
            claimed_collections.add(ref.collection_id)

        if not claimed_collections:
            return

        readable = await self.get_readable_collection_ids(user, claimed_collections)
        unauthorized = claimed_collections - readable
        if unauthorized:
            raise PermissionError(
                f"User lacks READ permission on collections: {', '.join(sorted(unauthorized))}"
            )

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

    def _should_update_last_used_at(self, last_used_at: datetime | None) -> bool:
        """
        Check if last_used_at should be updated (minute-level granularity).

        We use minute-level granularity to reduce write load on the database,
        since API keys can be used very frequently.
        """
        if last_used_at is None:
            return True
        now = datetime.now(UTC).replace(tzinfo=None)
        # Compare at minute granularity by truncating seconds and microseconds
        return now.replace(second=0, microsecond=0) != last_used_at.replace(second=0, microsecond=0)

    async def get_user_by_api_key(self, raw_api_key: str) -> User | None:
        """
        Validate an API key and return the associated user.
        Updates last_used_at timestamp if key is valid (at minute-level granularity).

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
                    if self._should_update_last_used_at(api_key_data.last_used_at):
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
                    update_values: dict[str, datetime | str] = {"fingerprint": fingerprint}
                    if self._should_update_last_used_at(api_key_data.last_used_at):
                        update_values["last_used_at"] = datetime.now(UTC).replace(tzinfo=None)
                    await session.execute(
                        update(SQLAApiKey)
                        .where(SQLAApiKey.id == api_key_data.id)
                        .values(**update_values)
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

    async def get_agent_run_metadata_fields(
        self,
        ctx: ViewContext,
        rubric_id: str | None = None,
        rubric_version: int | None = None,
        include_judge_result_metadata: bool = True,
        include_sample_values: bool = False,
        sample_limit: int = 10,
    ) -> list[FilterableFieldWithSamples]:
        """Expose agent run filter fields derived from JSON metadata and related tables.

        Args:
            ctx: The view context containing collection_id
            rubric_id: If provided, only return rubric output fields for this rubric
            rubric_version: If provided (along with rubric_id), only return fields from this version
            include_judge_result_metadata: If False, skip discovering result_metadata fields
        """

        all_fields: dict[str, FilterableFieldWithSamples] = {}

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
            all_fields[field_name] = FilterableFieldWithSamples(
                name=field_name, type=info.value_type
            )

        async with self.db.session() as session:
            if rubric_id is not None:
                if rubric_version is not None:
                    rubric_query = select(SQLARubric).where(
                        SQLARubric.collection_id == ctx.collection_id,
                        SQLARubric.id == rubric_id,
                        SQLARubric.version == rubric_version,
                    )
                else:
                    rubric_query = (
                        select(SQLARubric)
                        .where(
                            SQLARubric.collection_id == ctx.collection_id,
                            SQLARubric.id == rubric_id,
                        )
                        .order_by(SQLARubric.version.desc())
                        .limit(1)
                    )
                result = await session.execute(rubric_query)
                rubrics = list(result.scalars().all())
            else:
                result = await session.execute(
                    select(SQLARubric).where(SQLARubric.collection_id == ctx.collection_id)
                )
                all_rubrics = list(result.scalars().all())
                latest_by_id: dict[str, SQLARubric] = {}
                for r in all_rubrics:
                    existing = latest_by_id.get(r.id)
                    if existing is None or r.version > existing.version:
                        latest_by_id[r.id] = r
                rubrics = list(latest_by_id.values())

        for rubric in rubrics:
            for path, field_type in _extract_schema_fields(rubric.output_schema):
                field_name = f"rubric.{rubric.id}.{path}"
                all_fields[field_name] = FilterableFieldWithSamples(
                    name=field_name, type=field_type
                )

        # Query label sets for the collection and extract fields from their schemas
        async with self.db.session() as session:
            label_set_result = await session.execute(
                select(SQLALabelSet).where(SQLALabelSet.collection_id == ctx.collection_id)
            )
            label_sets = list(label_set_result.scalars().all())

        for label_set in label_sets:
            for path, field_type in _extract_schema_fields(label_set.label_schema):
                field_name = f"label.{label_set.id}.{path}"
                all_fields[field_name] = FilterableFieldWithSamples(
                    name=field_name, type=field_type
                )

        judge_where: ColumnElement[bool] | None = None
        if rubric_id is not None:
            judge_where = SQLAJudgeResult.rubric_id == rubric_id
            if rubric_version is not None:
                judge_where = and_(judge_where, SQLAJudgeResult.rubric_version == rubric_version)

        if include_judge_result_metadata:
            judge_metadata_infos = await self.get_json_metadata_fields_for_column(
                ctx.collection_id,
                table=SQLAJudgeResult.__table__,
                json_column=cast(ColumnElement[Any], SQLAJudgeResult.result_metadata),
                column_name="result_metadata",
                join_condition=SQLAJudgeResult.agent_run_id == SQLAAgentRun.id,
                group_specs=(("rubric_id", cast(ColumnElement[Any], SQLAJudgeResult.rubric_id)),),
                additional_where=judge_where,
            )
            for info in judge_metadata_infos:
                info_rubric_id = info.labels.get("rubric_id")
                if not info_rubric_id or info.value_type is None or not info.path:
                    continue
                field_name = f"rubric.{info_rubric_id}." + ".".join(info.path)
                all_fields[field_name] = FilterableFieldWithSamples(
                    name=field_name, type=info.value_type
                )

        all_fields["agent_run_id"] = FilterableFieldWithSamples(name="agent_run_id", type="str")
        all_fields["tag"] = FilterableFieldWithSamples(name="tag", type="str")

        fields = sorted(all_fields.values(), key=lambda f: f["name"])
        if include_sample_values:
            for field in fields:
                if field["type"] != "str":
                    continue
                name = field["name"]
                if not (name.startswith("metadata.") or name == "tag"):
                    continue
                samples, total_unique_values = await self.get_field_value_samples(
                    ctx, name, sample_limit=sample_limit
                )
                if total_unique_values <= 0:
                    continue
                field["sample_values"] = samples
                field["total_unique_values"] = total_unique_values

        return fields


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
