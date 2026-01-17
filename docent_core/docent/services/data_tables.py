from __future__ import annotations

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


def _escape_metadata_segment(segment: str) -> str:
    return segment.replace("'", "''")


def _metadata_field_expression(path: list[str]) -> str:
    base = "br.metadata_json"
    if not path:
        return base
    *parents, last = path
    for segment in parents:
        base += f"->'{_escape_metadata_segment(segment)}'"
    return f"{base}->>'{_escape_metadata_segment(last)}'"


def build_default_data_table_dql(metadata_fields: list[str] | None = None) -> str:
    metadata_selects: list[str] = []
    metadata_aliases: list[str] = []
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
        metadata_aliases.append(alias)
        expression = _metadata_field_expression(path)
        metadata_selects.append(f'  {expression} AS "{alias}"')

    metadata_columns = [f'  rm."{alias}"' for alias in metadata_aliases]
    select_lines = [
        "  br.id",
        "  br.name",
        "  br.created_at",
        *metadata_columns,
        "  rr.rubric_id",
        "  rr.rubric_version",
        "  rr.result_type",
        "  rr.output",
        "  rr.result_metadata",
    ]
    select_clause = ",\n".join(select_lines)

    return (
        "WITH base_runs AS (\n"
        "  SELECT id, name, created_at, metadata_json\n"
        "  FROM agent_runs\n"
        "  ORDER BY created_at DESC\n"
        "  LIMIT 20\n"
        "),\n"
        "run_metadata AS (\n"
        "  SELECT\n"
        "    br.id AS agent_run_id"
        + (",\n" + ",\n".join(metadata_selects) if metadata_selects else "")
        + "\n"
        "  FROM base_runs br\n"
        "),\n"
        "rubric_results AS (\n"
        "  SELECT\n"
        "    jr.agent_run_id,\n"
        "    jr.rubric_id,\n"
        "    jr.rubric_version,\n"
        "    jr.result_type,\n"
        "    jr.output,\n"
        "    jr.result_metadata\n"
        "  FROM judge_results jr\n"
        "  JOIN base_runs br ON br.id = jr.agent_run_id\n"
        ")\n"
        "SELECT\n"
        f"{select_clause}\n"
        "FROM base_runs br\n"
        "LEFT JOIN run_metadata rm ON rm.agent_run_id = br.id\n"
        "LEFT JOIN rubric_results rr ON rr.agent_run_id = br.id\n"
        "ORDER BY br.created_at DESC"
    )


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
    ) -> DataTableSpec:
        if ctx.user is None:
            raise PermissionError("User must be authenticated to create data tables.")

        data_table_id = str(uuid4())
        if name is None or not name.strip():
            name = await self._next_default_name(ctx)
        if dql is None or not dql.strip():
            dql = build_default_data_table_dql(metadata_fields)

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

        name = f"{data_table.name} copy"
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

        await self.session.execute(
            update(SQLADataTable)
            .where(
                SQLADataTable.collection_id == ctx.collection_id,
                SQLADataTable.id == data_table_id,
            )
            .values(**updates)
        )
        result = await self.session.execute(
            select(SQLADataTable).where(SQLADataTable.id == data_table_id)
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
