from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic_core import to_jsonable_python

from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.dql import (
    AllowedTable,
    DQLExecutionError,
    DQLParseError,
    DQLValidationError,
    SelectedColumn,
    build_default_registry,
)
from docent_core.docent.db.schemas.auth_models import Permission
from docent_core.docent.server.dependencies.database import get_mono_svc
from docent_core.docent.server.dependencies.permissions import require_view_permission
from docent_core.docent.server.dependencies.user import get_default_view_ctx
from docent_core.docent.services.monoservice import DQLQueryResult, MonoService

dql_router = APIRouter()


class DQLForeignKeySchema(BaseModel):
    column: str
    target_table: str
    target_column: str


class DQLColumnSchema(BaseModel):
    name: str
    data_type: str | None
    nullable: bool
    is_primary_key: bool
    foreign_keys: list[DQLForeignKeySchema] = Field(default_factory=lambda: [])
    alias_for: str | None = None


class DQLTableSchema(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    columns: list[DQLColumnSchema]


class DQLSchemaResponse(BaseModel):
    tables: list[DQLTableSchema]


class DQLExecuteRequest(BaseModel):
    dql: str


class DQLColumnReferenceModel(BaseModel):
    table: str | None
    column: str


class DQLSelectedColumnModel(BaseModel):
    output_name: str
    expression_sql: str
    source_columns: list[DQLColumnReferenceModel]


class DQLExecuteResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    row_count: int
    execution_time_ms: float
    requested_limit: int | None
    applied_limit: int
    selected_columns: list[DQLSelectedColumnModel]


def _build_foreign_keys(column: Any) -> list[DQLForeignKeySchema]:
    foreign_keys: list[DQLForeignKeySchema] = []
    for fk in getattr(column, "foreign_keys", []):
        target_column = getattr(fk, "column", None)
        if target_column is not None and getattr(target_column, "table", None) is not None:
            foreign_keys.append(
                DQLForeignKeySchema(
                    column=column.key,
                    target_table=str(target_column.table.name),
                    target_column=str(target_column.name),
                )
            )
    return foreign_keys


def _table_to_schema(table: AllowedTable) -> DQLTableSchema:
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
                    foreign_keys=_build_foreign_keys(column),
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
        foreign_keys: list[DQLForeignKeySchema] = []

        if canonical_column is not None:
            column_type = getattr(canonical_column, "type", None)
            if column_type is not None:
                data_type = str(column_type)
            nullable = bool(getattr(canonical_column, "nullable", True))
            foreign_keys = _build_foreign_keys(canonical_column)

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


@dql_router.get("/{collection_id}/schema")
async def get_dql_schema(
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
    mono_svc: MonoService = Depends(get_mono_svc),
) -> DQLSchemaResponse:
    json_fields = await mono_svc.get_json_metadata_fields_map(ctx.collection_id)
    registry = build_default_registry(
        collection_id=ctx.collection_id,
        json_fields=json_fields,
    )
    tables = sorted(
        (_table_to_schema(table) for table in registry.iter_tables()),
        key=lambda tbl: tbl.name,
    )
    return DQLSchemaResponse(tables=tables)


def _serialize_selected_columns(columns: list[SelectedColumn]) -> list[DQLSelectedColumnModel]:
    serialized: list[DQLSelectedColumnModel] = []
    for column in columns:
        serialized.append(
            DQLSelectedColumnModel(
                output_name=column.output_name,
                expression_sql=column.expression_sql,
                source_columns=[
                    DQLColumnReferenceModel(table=ref.table, column=ref.column)
                    for ref in column.source_columns
                ],
            )
        )
    return serialized


def _build_execute_response(result: DQLQueryResult) -> DQLExecuteResponse:
    return DQLExecuteResponse(
        columns=list(result.columns),
        rows=[[to_jsonable_python(value) for value in row] for row in result.rows],
        truncated=result.truncated,
        row_count=result.row_count,
        execution_time_ms=result.execution_time_ms,
        requested_limit=result.requested_limit,
        applied_limit=result.applied_limit,
        selected_columns=_serialize_selected_columns(result.selected_columns),
    )


@dql_router.post("/{collection_id}/execute")
async def execute_dql_query(
    collection_id: str,
    request: DQLExecuteRequest,
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
    mono_svc: MonoService = Depends(get_mono_svc),
) -> DQLExecuteResponse:
    if ctx.user is None:
        raise HTTPException(status_code=400, detail="User context unavailable.")
    try:
        result = await mono_svc.execute_dql_query(
            user=ctx.user,
            collection_id=collection_id,
            dql=request.dql,
        )
    except (DQLParseError, DQLValidationError, DQLExecutionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _build_execute_response(result)
