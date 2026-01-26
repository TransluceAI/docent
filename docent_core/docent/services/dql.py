from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Final, Literal, Mapping, Sequence, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import text

from docent._log_util import get_logger
from docent_core._db_service.db import DocentDB
from docent_core.docent.db.dql import (
    AllowedTable,
    ColumnReference,
    DQLExecutionError,
    DQLRegistry,
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
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.rubric import SQLARubric
from docent_core.docent.db.schemas.tables import SQLAAgentRun, SQLATranscript

logger = get_logger(__name__)

MAX_DQL_RESULT_LIMIT: Final[int] = 10_000


@dataclass(slots=True)
class DQLQueryResult:
    """Results from executing a DQL query."""

    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]]
    selected_columns: list[SelectedColumn]
    truncated: bool
    execution_time_ms: float
    compiled_sql: str
    requested_limit: int | None
    applied_limit: int
    row_count: int


@dataclass(slots=True)
class DQLForeignKey:
    """Foreign key metadata for a column."""

    column: str
    target_table: str
    target_column: str


@dataclass(slots=True)
class DQLColumnSchema:
    """Schema metadata for a column."""

    name: str
    data_type: str | None
    nullable: bool
    is_primary_key: bool
    foreign_keys: list[DQLForeignKey]
    alias_for: str | None


@dataclass(slots=True)
class DQLTableSchema:
    """Schema metadata for a table."""

    name: str
    aliases: list[str]
    columns: list[DQLColumnSchema]


@dataclass(slots=True)
class DQLLinkHintData:
    """Link hint data for navigating to related entities."""

    link_type: Literal["agent_run", "rubric"]
    value_kind: Literal["agent_run_id", "transcript_id", "rubric_id"]
    transcript_id_map: dict[str, str] | None = None


class DQLService:
    """Service for DQL query execution and schema operations."""

    def __init__(self, db: DocentDB):
        self.db = db

    def _format_datatype_error(self, original_message: str, parameters: dict[str, Any]) -> str:
        """Format IndeterminateDatatypeError with helpful context.

        These errors occur when PostgreSQL can't infer argument types for
        functions like jsonb_build_object. Rather than showing internal
        parameter values (which may be confusing), we give actionable advice.
        """
        _ = parameters  # Not used - internal params can be misleading
        _ = original_message
        return (
            "Could not determine data type for a value in the query. "
            "This often happens with `jsonb_build_object` or `jsonb_object_agg` "
            "when arguments are expressions rather than literals. "
            "Try adding explicit type casts to the arguments, e.g., `column::text`."
        )

    async def execute_query(
        self,
        *,
        user: User,
        collection_id: str,
        dql: str,
        json_fields: Mapping[str, list[JsonFieldInfo]] | None = None,
    ) -> DQLQueryResult:
        """Execute a DQL query and return results."""
        from docent_core.docent.services.monoservice import MonoService

        mono_service = MonoService(self.db)
        await ensure_dql_collection_access(
            mono_service=mono_service,
            user=user,
            collection_id=collection_id,
        )

        json_field_map = json_fields or {}
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
                orig = getattr(exc, "orig", exc)
                message = str(orig).strip()
                # Strip the class prefix if present (e.g., "<class '...'>: message")
                if message.startswith("<class "):
                    colon_idx = message.find(">:")
                    if colon_idx != -1:
                        message = message[colon_idx + 2 :].strip()
                if not message:
                    message = "Failed to execute query."
                # Provide friendlier error for IndeterminateDatatypeError
                # Check both the type name and the message content for robustness
                is_datatype_error = (
                    "IndeterminateDatatypeError" in type(orig).__name__
                    or "could not determine data type of parameter" in message.lower()
                )
                if is_datatype_error:
                    message = self._format_datatype_error(message, parameters or {})
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

    async def get_agent_run_ids_for_transcripts(
        self,
        *,
        collection_id: str,
        transcript_ids: Sequence[str],
        batch_size: int = 10_000,
    ) -> dict[str, str]:
        """Map transcript IDs to their parent agent run IDs."""
        if not transcript_ids:
            return {}

        if len(transcript_ids) > batch_size:
            ids = list(dict.fromkeys(transcript_ids))
        else:
            ids = list(transcript_ids)

        result_map: dict[str, str] = {}
        async with self.db.session() as session:
            for i in range(0, len(ids), batch_size):
                batch = ids[i : i + batch_size]
                result = await session.execute(
                    select(SQLATranscript.id, SQLATranscript.agent_run_id).where(
                        SQLATranscript.collection_id == collection_id,
                        SQLATranscript.id.in_(batch),
                    )
                )
                for row in result.all():
                    result_map[row[0]] = row[1]

        return result_map

    def build_table_schema(self, table: AllowedTable) -> DQLTableSchema:
        """Build the schema representation for a DQL table."""
        table_obj = table.table
        column_schemas: list[DQLColumnSchema] = []
        actual_columns: set[str] = set()
        column_objects: dict[str, Any] = {}
        if hasattr(table_obj, "c"):
            for column in table_obj.c:
                column_name = getattr(column, "key", None)
                if column_name is None:
                    continue
                column_name_lower = column_name.lower()
                actual_columns.add(column_name_lower)
                if column_name_lower not in table.allowed_columns:
                    continue
                data_type = None
                column_type = getattr(column, "type", None)
                if column_type is not None:
                    data_type = str(column_type)
                column_objects[column_name_lower] = column
                column_schemas.append(
                    DQLColumnSchema(
                        name=str(column_name),
                        data_type=data_type,
                        nullable=bool(getattr(column, "nullable", True)),
                        is_primary_key=bool(getattr(column, "primary_key", False)),
                        foreign_keys=self._build_foreign_keys(column),
                        alias_for=None,
                    )
                )

        extra_columns = sorted(col for col in table.allowed_columns if col not in actual_columns)
        for extra_column in extra_columns:
            column_schemas.append(
                DQLColumnSchema(
                    name=extra_column,
                    data_type="json",
                    nullable=True,
                    is_primary_key=False,
                    foreign_keys=[],
                    alias_for=None,
                )
            )

        for alias_name, target_name in table.column_aliases.items():
            canonical_column = column_objects.get(target_name)
            data_type = None
            nullable = True
            foreign_keys: list[DQLForeignKey] = []

            if canonical_column is not None:
                column_type = getattr(canonical_column, "type", None)
                if column_type is not None:
                    data_type = str(column_type)
                nullable = bool(getattr(canonical_column, "nullable", True))
                foreign_keys = self._build_foreign_keys(canonical_column)

            column_schemas.append(
                DQLColumnSchema(
                    name=alias_name,
                    data_type=data_type,
                    nullable=nullable,
                    is_primary_key=False,
                    foreign_keys=foreign_keys,
                    alias_for=target_name,
                )
            )

        return DQLTableSchema(
            name=table.name,
            aliases=sorted(table.aliases),
            columns=sorted(column_schemas, key=lambda col: col.name),
        )

    def build_schema_response(self, registry: DQLRegistry) -> list[DQLTableSchema]:
        """Build the full schema response from a registry."""
        return sorted(
            (self.build_table_schema(table) for table in registry.iter_tables()),
            key=lambda tbl: tbl.name,
        )

    def build_link_hints(
        self,
        result: DQLQueryResult,
        *,
        registry: DQLRegistry,
    ) -> tuple[list[DQLLinkHintData | None], set[str]]:
        """Generate link hints for query results."""

        def sample_value(rows: list[tuple[Any, ...]], column_index: int) -> Any | None:
            for row in rows:
                if column_index >= len(row):
                    continue
                value = row[column_index]
                if value is not None:
                    return value
            return None

        def sample_type(rows: list[tuple[Any, ...]], column_index: int) -> str | None:
            value = sample_value(rows, column_index)
            if value is None:
                return None
            return type(value).__name__

        link_hints: list[DQLLinkHintData | None] = []
        transcript_ids: set[str] = set()
        fk_map = self._build_fk_reference_map(registry)
        pk_map = self._build_pk_map(registry)
        for column_index, selected in enumerate(result.selected_columns):
            hint: DQLLinkHintData | None = None
            if len(selected.source_columns) == 1:
                source = selected.source_columns[0]
                if source.table and (source.table.lower(), source.column.lower()) in pk_map:
                    if source.table.lower() == SQLAAgentRun.__tablename__.lower():
                        hint = DQLLinkHintData(link_type="agent_run", value_kind="agent_run_id")
                    elif source.table.lower() == SQLATranscript.__tablename__.lower():
                        hint = DQLLinkHintData(link_type="agent_run", value_kind="transcript_id")
                    elif source.table.lower() == SQLARubric.__tablename__.lower():
                        hint = DQLLinkHintData(link_type="rubric", value_kind="rubric_id")
                elif self._is_agent_run_reference(source, fk_map=fk_map):
                    hint = DQLLinkHintData(link_type="agent_run", value_kind="agent_run_id")
                elif self._is_transcript_reference(source, fk_map=fk_map):
                    hint = DQLLinkHintData(link_type="agent_run", value_kind="transcript_id")
                elif self._is_rubric_reference(source, fk_map=fk_map):
                    hint = DQLLinkHintData(link_type="rubric", value_kind="rubric_id")

            link_hints.append(hint)
            if hint and hint.value_kind == "transcript_id":
                for row in result.rows:
                    value = row[column_index]
                    if isinstance(value, str):
                        transcript_ids.add(value)

        logger.info(
            "DQL link hints: %s",
            [
                {
                    "column_index": idx,
                    "output": col.output_name,
                    "sources": [(ref.table, ref.column) for ref in col.source_columns],
                    "hint": {"link_type": hint.link_type, "value_kind": hint.value_kind}
                    if hint
                    else None,
                    "sample_value": sample_value(result.rows, idx),
                    "sample_type": sample_type(result.rows, idx),
                }
                for idx, (col, hint) in enumerate(zip(result.selected_columns, link_hints))
            ],
        )
        return link_hints, transcript_ids

    def attach_transcript_id_map(
        self,
        link_hints: list[DQLLinkHintData | None],
        transcript_id_map: dict[str, str],
    ) -> list[DQLLinkHintData | None]:
        """Attach transcript ID mappings to link hints."""
        if not transcript_id_map:
            return link_hints
        updated: list[DQLLinkHintData | None] = []
        for hint in link_hints:
            if hint and hint.value_kind == "transcript_id":
                updated.append(
                    DQLLinkHintData(
                        link_type=hint.link_type,
                        value_kind=hint.value_kind,
                        transcript_id_map=transcript_id_map,
                    )
                )
            else:
                updated.append(hint)
        return updated

    def _build_foreign_keys(self, column: Any) -> list[DQLForeignKey]:
        """Extract foreign key metadata from a SQLAlchemy column."""
        foreign_keys: list[DQLForeignKey] = []
        for fk in getattr(column, "foreign_keys", []):
            target_column = getattr(fk, "column", None)
            if target_column is not None and getattr(target_column, "table", None) is not None:
                foreign_keys.append(
                    DQLForeignKey(
                        column=column.key,
                        target_table=str(target_column.table.name),
                        target_column=str(target_column.name),
                    )
                )
        return foreign_keys

    def _build_fk_reference_map(
        self,
        registry: DQLRegistry,
    ) -> Mapping[tuple[str, str], set[tuple[str, str]]]:
        """Build foreign key reference map from registry."""
        references: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        for table in registry.iter_tables():
            table_obj = table.table
            if not hasattr(table_obj, "c"):
                continue
            for column in table_obj.c:
                column_name = getattr(column, "key", None)
                if column_name is None:
                    continue
                column_key = column_name.lower()
                if column_key not in table.allowed_columns:
                    continue
                for fk in getattr(column, "foreign_keys", []):
                    target_column = getattr(fk, "column", None)
                    if target_column is None:
                        continue
                    target_table = getattr(target_column, "table", None)
                    if target_table is None:
                        continue
                    references[(table.name.lower(), column_key)].add(
                        (target_table.name.lower(), target_column.name.lower())
                    )
        logger.info(
            "DQL FK map built: %s",
            {
                f"{source_table}.{source_column}": sorted(
                    f"{target_table}.{target_column}" for target_table, target_column in targets
                )
                for (source_table, source_column), targets in references.items()
            },
        )
        return references

    def _build_pk_map(self, registry: DQLRegistry) -> set[tuple[str, str]]:
        """Build primary key map from registry."""
        primary_keys: set[tuple[str, str]] = set()
        for table in registry.iter_tables():
            table_obj = table.table
            if not hasattr(table_obj, "c"):
                continue
            for column in table_obj.c:
                column_name = getattr(column, "key", None)
                if column_name is None:
                    continue
                column_key = column_name.lower()
                if column_key not in table.allowed_columns:
                    continue
                if getattr(column, "primary_key", False):
                    primary_keys.add((table.name.lower(), column_key))
        logger.info(
            "DQL PK map built: %s",
            sorted(f"{table}.{column}" for table, column in primary_keys),
        )
        return primary_keys

    def _has_fk_reference(
        self,
        source: ColumnReference,
        *,
        fk_map: Mapping[tuple[str, str], set[tuple[str, str]]],
        target_table: str,
    ) -> bool:
        """Check if source column has FK reference to target table."""
        if source.table is None:
            logger.info(
                "DQL FK hint skipped: missing table for column=%s target=%s",
                source.column,
                target_table,
            )
            return False
        table = source.table.lower()
        column = source.column.lower()
        targets = fk_map.get((table, column))
        if not targets:
            logger.info(
                "DQL FK hint not found: source=%s.%s target=%s",
                table,
                column,
                target_table,
            )
            return False
        for target_table_name, target_column_name in targets:
            if target_table_name != target_table:
                continue
            logger.info(
                "DQL FK hint match: source=%s.%s target=%s.%s",
                table,
                column,
                target_table_name,
                target_column_name,
            )
            return True
        logger.info(
            "DQL FK hint mismatch: source=%s.%s targets=%s expected=%s",
            table,
            column,
            sorted(f"{tbl}.{col}" for tbl, col in targets),
            target_table,
        )
        return False

    def _is_agent_run_reference(
        self, source: ColumnReference, *, fk_map: Mapping[tuple[str, str], set[tuple[str, str]]]
    ) -> bool:
        """Check if source column references agent_run table."""
        if source.column.lower() == "agent_run_id":
            return True
        return self._has_fk_reference(
            source,
            fk_map=fk_map,
            target_table=SQLAAgentRun.__tablename__.lower(),
        )

    def _is_transcript_reference(
        self, source: ColumnReference, *, fk_map: Mapping[tuple[str, str], set[tuple[str, str]]]
    ) -> bool:
        """Check if source column references transcript table."""
        if source.column.lower() == "transcript_id":
            return True
        return self._has_fk_reference(
            source,
            fk_map=fk_map,
            target_table=SQLATranscript.__tablename__.lower(),
        )

    def _is_rubric_reference(
        self, source: ColumnReference, *, fk_map: Mapping[tuple[str, str], set[tuple[str, str]]]
    ) -> bool:
        """Check if source column references rubric table."""
        if source.column.lower() == "rubric_id":
            return True
        return self._has_fk_reference(
            source,
            fk_map=fk_map,
            target_table=SQLARubric.__tablename__.lower(),
        )
