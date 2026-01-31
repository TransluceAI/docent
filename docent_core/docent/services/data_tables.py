from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.data_table import SQLADataTable

DEFAULT_DATA_TABLE_NAME = "All runs"

# Limit number of rubric CTEs in default query to avoid overly complex queries
MAX_RUBRIC_CTES = 5


@dataclass(frozen=True)
class RubricInfo:
    """Rubric information needed for building default DQL with modal CTEs."""

    id: str
    version: int
    output_fields: list[str]


def _sanitize_identifier(name: str) -> str:
    """Sanitize a string for use as a SQL identifier."""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if sanitized and sanitized[0].isdigit():
        sanitized = "_" + sanitized
    return sanitized or "_"


def _escape_literal(value: str) -> str:
    """Escape a string for use as a SQL literal."""
    return value.replace("'", "''")


def _build_rubric_ctes(rubrics: list[RubricInfo]) -> tuple[list[str], dict[str, str]]:
    """Build CTEs for rubrics using mode() WITHIN GROUP for multiple rollouts.

    Returns (cte_strings, rubric_id -> alias map).
    """
    ctes: list[str] = []
    alias_map: dict[str, str] = {}
    alias_counts: dict[str, int] = {}

    for rubric in rubrics:
        short_id = rubric.id.split("-", maxsplit=1)[0]
        base_alias = _sanitize_identifier(f"rubric_{short_id}_modes")
        alias_index = alias_counts.get(base_alias, 0)
        alias_counts[base_alias] = alias_index + 1
        alias = base_alias if alias_index == 0 else f"{base_alias}_{alias_index}"
        alias_map[rubric.id] = alias

        escaped_id = _escape_literal(rubric.id)

        # Build mode() expressions for output fields (default to label if none specified)
        fields = rubric.output_fields if rubric.output_fields else ["label"]
        mode_lines: list[str] = []
        for field in sorted(fields):
            escaped_field = _escape_literal(field)
            sanitized_field = _sanitize_identifier(field)
            mode_lines.append(
                f"      mode() WITHIN GROUP (ORDER BY jr.output->>'{escaped_field}') "
                f"AS {sanitized_field}"
            )

        mode_clause = ",\n".join(mode_lines)

        cte = "\n".join(
            [
                f"  {alias} AS (",
                "    SELECT",
                "      jr.agent_run_id,",
                mode_clause,
                "    FROM judge_results jr",
                f"    WHERE jr.rubric_id = '{escaped_id}'",
                f"      AND jr.rubric_version = {rubric.version}",
                "      AND jr.result_type = 'DIRECT_RESULT'",
                "    GROUP BY jr.agent_run_id",
                "  )",
            ]
        )
        ctes.append(cte)

    return ctes, alias_map


def build_default_data_table_dql(
    metadata_fields: list[str] | None = None,
    rubrics: list[RubricInfo] | None = None,
) -> str:
    """Build a default query showing agent_runs with metadata and rubric results.

    Includes modal CTEs for rubrics (up to MAX_RUBRIC_CTES) to handle multiple
    rollouts via mode() WITHIN GROUP aggregation.
    """
    select_columns = ["ar.id", "ar.name", "ar.created_at"]

    # Build rubric CTEs (limited to MAX_RUBRIC_CTES)
    rubrics_to_include = (rubrics or [])[:MAX_RUBRIC_CTES]
    rubric_ctes, rubric_aliases = _build_rubric_ctes(rubrics_to_include)

    # Add rubric field selects
    for rubric in rubrics_to_include:
        alias = rubric_aliases.get(rubric.id)
        if not alias:
            continue
        fields = rubric.output_fields if rubric.output_fields else ["label"]
        short_id = rubric.id.split("-", maxsplit=1)[0]
        for field in sorted(fields):
            sanitized_field = _sanitize_identifier(field)
            col_alias = f"rubric_{short_id}_{field}"
            select_columns.append(f'{alias}.{sanitized_field} AS "{col_alias}"')

    # Add metadata field extractions if provided
    seen: set[str] = set()
    for field in metadata_fields or []:
        if not field.startswith("metadata."):
            continue
        path = [segment for segment in field.split(".")[1:] if segment]
        if not path:
            continue
        alias = "metadata." + ".".join(path)
        if alias in seen:
            continue
        seen.add(alias)
        # Build JSON path expression: metadata_json->>'field' or metadata_json->'a'->>'b'
        *parents, last = path
        base = "ar.metadata_json"
        for segment in parents:
            escaped = segment.replace("'", "''")
            base += f"->'{escaped}'"
        escaped_last = last.replace("'", "''")
        expression = f"{base}->>'{escaped_last}'"
        select_columns.append(f'{expression} AS "{alias}"')

    columns_str = ",\n  ".join(select_columns)

    # Build JOIN clauses for rubric CTEs
    join_clauses: list[str] = []
    for rubric in rubrics_to_include:
        alias = rubric_aliases.get(rubric.id)
        if alias:
            join_clauses.append(f"LEFT JOIN {alias} ON {alias}.agent_run_id = ar.id")

    # Build the query
    lines: list[str] = []
    if rubric_ctes:
        lines.append("WITH")
        lines.append(",\n".join(rubric_ctes))
    lines.append("SELECT")
    lines.append(f"  {columns_str}")
    lines.append("FROM agent_runs ar")
    lines.extend(join_clauses)
    lines.append("ORDER BY ar.created_at DESC")
    lines.append("LIMIT 20")

    return "\n".join(lines)


# Basic default query without rubric CTEs (used as fallback)
DEFAULT_DATA_TABLE_DQL = build_default_data_table_dql()


class DataTableSpec(BaseModel):
    id: str
    collection_id: str
    name: str
    dql: str
    state: dict[str, Any] | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_sqla(cls, data_table: SQLADataTable) -> "DataTableSpec":
        return cls(
            id=data_table.id,
            collection_id=data_table.collection_id,
            name=data_table.name,
            dql=data_table.dql,
            state=data_table.state_json,
            created_by=data_table.created_by,
            created_at=data_table.created_at,
            updated_at=data_table.updated_at,
        )


@dataclass(slots=True)
class DataTablesService:
    session: AsyncSession

    async def list_data_tables(self, ctx: ViewContext) -> list[DataTableSpec]:
        result = await self.session.execute(
            select(SQLADataTable)
            .where(SQLADataTable.collection_id == ctx.collection_id)
            .order_by(SQLADataTable.created_at.desc())
        )
        data_tables = list(result.scalars().all())
        return [DataTableSpec.from_sqla(row) for row in data_tables]

    async def get_data_table(self, ctx: ViewContext, data_table_id: str) -> DataTableSpec | None:
        result = await self.session.execute(
            select(SQLADataTable).where(
                SQLADataTable.collection_id == ctx.collection_id,
                SQLADataTable.id == data_table_id,
            )
        )
        data_table = result.scalar_one_or_none()
        if data_table is None:
            return None
        return DataTableSpec.from_sqla(data_table)

    async def create_data_table(
        self,
        ctx: ViewContext,
        *,
        name: str | None = None,
        dql: str | None = None,
        state: dict[str, Any] | None = None,
        metadata_fields: list[str] | None = None,
        rubrics: list[RubricInfo] | None = None,
    ) -> DataTableSpec:
        if ctx.user is None:
            raise PermissionError("User must be authenticated to create data tables.")

        data_table_id = str(uuid4())
        if name is None or not name.strip():
            name = await self._next_default_name(ctx)
        else:
            name = await self._make_unique_name(ctx, name.strip())
        if dql is None or not dql.strip():
            dql = build_default_data_table_dql(metadata_fields, rubrics)

        data_table = SQLADataTable(
            id=data_table_id,
            collection_id=ctx.collection_id,
            created_by=ctx.user.id,
            name=name,
            dql=dql,
            state_json=state,
        )
        self.session.add(data_table)
        await self.session.flush()
        return DataTableSpec.from_sqla(data_table)

    async def duplicate_data_table(
        self,
        ctx: ViewContext,
        data_table_id: str,
    ) -> DataTableSpec:
        result = await self.session.execute(
            select(SQLADataTable).where(
                SQLADataTable.collection_id == ctx.collection_id,
                SQLADataTable.id == data_table_id,
            )
        )
        data_table = result.scalar_one_or_none()
        if data_table is None:
            raise ValueError("Data table not found.")

        base_copy_name = f"{data_table.name} copy"
        name = await self._make_unique_name(ctx, base_copy_name)
        data_table_id = str(uuid4())
        duplicate = SQLADataTable(
            id=data_table_id,
            collection_id=data_table.collection_id,
            created_by=ctx.user.id if ctx.user else data_table.created_by,
            name=name,
            dql=data_table.dql,
            state_json=data_table.state_json,
        )
        self.session.add(duplicate)
        await self.session.flush()
        return DataTableSpec.from_sqla(duplicate)

    async def update_data_table(
        self,
        ctx: ViewContext,
        data_table_id: str,
        updates: dict[str, Any],
    ) -> DataTableSpec:
        if not updates:
            data_table = await self.get_data_table(ctx, data_table_id)
            if data_table is None:
                raise ValueError("Data table not found.")
            return data_table

        # Ensure name uniqueness if name is being updated
        if "name" in updates and updates["name"]:
            updates["name"] = await self._make_unique_name(
                ctx, updates["name"].strip(), exclude_id=data_table_id
            )

        await self.session.execute(
            update(SQLADataTable)
            .where(
                SQLADataTable.collection_id == ctx.collection_id,
                SQLADataTable.id == data_table_id,
            )
            .values(**updates)
        )
        result = await self.session.execute(
            select(SQLADataTable).where(
                SQLADataTable.collection_id == ctx.collection_id,
                SQLADataTable.id == data_table_id,
            )
        )
        data_table = result.scalar_one_or_none()
        if data_table is None:
            raise ValueError("Data table not found.")
        return DataTableSpec.from_sqla(data_table)

    async def delete_data_table(self, ctx: ViewContext, data_table_id: str) -> None:
        await self.session.execute(
            delete(SQLADataTable).where(
                SQLADataTable.collection_id == ctx.collection_id,
                SQLADataTable.id == data_table_id,
            )
        )

    async def _next_default_name(self, ctx: ViewContext) -> str:
        result = await self.session.execute(
            select(SQLADataTable.name).where(SQLADataTable.collection_id == ctx.collection_id)
        )
        existing_names = [row[0] for row in result.fetchall()]
        max_num = 0
        for existing_name in existing_names:
            if existing_name.startswith("Data Table "):
                try:
                    num = int(existing_name[11:])
                    max_num = max(max_num, num)
                except ValueError:
                    continue
        return f"Data Table {max_num + 1}"

    async def _make_unique_name(
        self,
        ctx: ViewContext,
        desired_name: str,
        exclude_id: str | None = None,
    ) -> str:
        """Ensure a name is unique within the collection by appending a number if needed.

        Args:
            ctx: View context with collection_id
            desired_name: The name to make unique
            exclude_id: Optional data table ID to exclude from uniqueness check (for updates)

        Returns:
            A unique name, possibly with " 2", " 3", etc. appended
        """
        query = select(SQLADataTable.name).where(SQLADataTable.collection_id == ctx.collection_id)
        if exclude_id:
            query = query.where(SQLADataTable.id != exclude_id)

        result = await self.session.execute(query)
        existing_names = {row[0].lower() for row in result.fetchall()}

        # If the name is already unique, return it as-is
        if desired_name.lower() not in existing_names:
            return desired_name

        # Find the next available number suffix
        # Check if desired_name already ends with a number (e.g., "Name 2")
        base_name = desired_name
        match = re.match(r"^(.+?)\s+(\d+)$", desired_name)
        if match:
            base_name = match.group(1)

        counter = 2
        while True:
            candidate = f"{base_name} {counter}"
            if candidate.lower() not in existing_names:
                return candidate
            counter += 1
