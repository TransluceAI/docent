from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic_core import to_jsonable_python

from docent._llm_util.providers.preference_types import ModelOption
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.dql import (
    DQLExecutionError,
    DQLParseError,
    DQLValidationError,
    SelectedColumn,
    build_default_registry,
)
from docent_core.docent.db.schemas.auth_models import Permission
from docent_core.docent.server.dependencies.database import get_mono_svc
from docent_core.docent.server.dependencies.permissions import require_view_permission
from docent_core.docent.server.dependencies.services import (
    get_dql_generator_service,
    get_dql_service,
    get_rubric_service,
)
from docent_core.docent.server.dependencies.user import get_default_view_ctx
from docent_core.docent.services.dql import DQLQueryResult, DQLService
from docent_core.docent.services.dql_generator import (
    DQLGeneratorMessage,
    DQLGeneratorService,
    RubricSchemaInfo,
)
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService

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


class DQLRubricSchema(BaseModel):
    """Schema information for a rubric's output structure."""

    id: str
    version: int
    name: str | None = None
    output_fields: list[str] = Field(default_factory=list)


class DQLSchemaResponse(BaseModel):
    tables: list[DQLTableSchema]
    rubrics: list[DQLRubricSchema] = Field(default_factory=lambda: [])


def _extract_output_fields_from_schema(output_schema: dict[str, Any]) -> list[str]:
    """Extract field names from a JSON Schema's properties."""
    if not output_schema:
        return []
    properties = output_schema.get("properties")
    if properties is None or not isinstance(properties, dict):
        return []
    # Cast to dict[str, Any] since JSON Schema properties are string-keyed
    props_dict: dict[str, Any] = properties  # type: ignore[reportUnknownVariableType]
    return sorted(props_dict.keys())


class DQLExecuteRequest(BaseModel):
    dql: str


class DQLColumnReferenceModel(BaseModel):
    table: str | None
    column: str


class DQLSelectedColumnModel(BaseModel):
    output_name: str
    expression_sql: str
    source_columns: list[DQLColumnReferenceModel]


class DQLLinkHint(BaseModel):
    link_type: Literal["agent_run", "rubric"]
    value_kind: Literal["agent_run_id", "transcript_id", "rubric_id"]
    transcript_id_map: dict[str, str] | None = None


class DQLExecuteResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    row_count: int
    execution_time_ms: float
    requested_limit: int | None
    applied_limit: int
    selected_columns: list[DQLSelectedColumnModel]
    link_hints: list[DQLLinkHint | None]


def _serialize_selected_columns(columns: list[SelectedColumn]) -> list[DQLSelectedColumnModel]:
    """Serialize selected columns to response models."""
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


def _build_execute_response(
    result: DQLQueryResult,
    link_hints: list[DQLLinkHint | None],
) -> DQLExecuteResponse:
    """Build the execute response from query result and link hints."""
    return DQLExecuteResponse(
        columns=list(result.columns),
        rows=[[to_jsonable_python(value) for value in row] for row in result.rows],
        truncated=result.truncated,
        row_count=result.row_count,
        execution_time_ms=result.execution_time_ms,
        requested_limit=result.requested_limit,
        applied_limit=result.applied_limit,
        selected_columns=_serialize_selected_columns(result.selected_columns),
        link_hints=link_hints,
    )


def _convert_service_schema_to_response(
    dql_svc: DQLService,
    registry: Any,
) -> list[DQLTableSchema]:
    """Convert service schema to Pydantic response models."""
    service_tables = dql_svc.build_schema_response(registry)
    tables: list[DQLTableSchema] = []
    for svc_table in service_tables:
        columns: list[DQLColumnSchema] = []
        for svc_col in svc_table.columns:
            foreign_keys = [
                DQLForeignKeySchema(
                    column=fk.column,
                    target_table=fk.target_table,
                    target_column=fk.target_column,
                )
                for fk in svc_col.foreign_keys
            ]
            columns.append(
                DQLColumnSchema(
                    name=svc_col.name,
                    data_type=svc_col.data_type,
                    nullable=svc_col.nullable,
                    is_primary_key=svc_col.is_primary_key,
                    foreign_keys=foreign_keys,
                    alias_for=svc_col.alias_for,
                )
            )
        tables.append(
            DQLTableSchema(
                name=svc_table.name,
                aliases=svc_table.aliases,
                columns=columns,
            )
        )
    return tables


def _convert_service_link_hints_to_response(
    service_hints: list[Any | None],
) -> list[DQLLinkHint | None]:
    """Convert service link hints to Pydantic response models."""
    response_hints: list[DQLLinkHint | None] = []
    for hint in service_hints:
        if hint is None:
            response_hints.append(None)
        else:
            response_hints.append(
                DQLLinkHint(
                    link_type=hint.link_type,
                    value_kind=hint.value_kind,
                    transcript_id_map=hint.transcript_id_map,
                )
            )
    return response_hints


@dql_router.get("/{collection_id}/schema")
async def get_dql_schema(
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
    mono_svc: MonoService = Depends(get_mono_svc),
    dql_svc: DQLService = Depends(get_dql_service),
    rubric_svc: RubricService = Depends(get_rubric_service),
) -> DQLSchemaResponse:
    json_fields = await mono_svc.get_json_metadata_fields_map(ctx.collection_id)
    registry = build_default_registry(
        collection_id=ctx.collection_id,
        json_fields=json_fields,
    )
    tables = _convert_service_schema_to_response(dql_svc, registry)

    # Fetch rubrics and extract their output schemas
    rubrics_list = await rubric_svc.get_all_rubrics(ctx.collection_id, latest_only=True)
    rubric_schemas: list[DQLRubricSchema] = []
    for rubric in rubrics_list:
        output_fields = _extract_output_fields_from_schema(rubric.output_schema)
        rubric_schemas.append(
            DQLRubricSchema(
                id=rubric.id,
                version=rubric.version,
                name=rubric.rubric_text[:100] if rubric.rubric_text else None,
                output_fields=output_fields,
            )
        )

    return DQLSchemaResponse(tables=tables, rubrics=rubric_schemas)


@dql_router.post("/{collection_id}/execute")
async def execute_dql_query(
    collection_id: str,
    request: DQLExecuteRequest,
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
    mono_svc: MonoService = Depends(get_mono_svc),
    dql_svc: DQLService = Depends(get_dql_service),
) -> DQLExecuteResponse:
    if ctx.user is None:
        raise HTTPException(status_code=400, detail="User context unavailable.")

    json_fields = await mono_svc.get_json_metadata_fields_map(collection_id)

    try:
        result = await dql_svc.execute_query(
            user=ctx.user,
            collection_id=collection_id,
            dql=request.dql,
            json_fields=json_fields,
        )
    except (DQLParseError, DQLValidationError, DQLExecutionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    registry = build_default_registry(
        collection_id=collection_id,
        json_fields=json_fields,
    )
    service_link_hints, transcript_ids = dql_svc.build_link_hints(result, registry=registry)
    transcript_id_map = await dql_svc.get_agent_run_ids_for_transcripts(
        collection_id=collection_id,
        transcript_ids=list(transcript_ids),
    )
    service_link_hints = dql_svc.attach_transcript_id_map(service_link_hints, transcript_id_map)
    link_hints = _convert_service_link_hints_to_response(service_link_hints)
    return _build_execute_response(result, link_hints)


class DQLGenerateMessage(BaseModel):
    """A message in the DQL generation conversation."""

    role: Literal["user", "assistant", "system"]
    content: str
    query: str | None = None


class DQLGenerateRequest(BaseModel):
    """Request body for DQL generation."""

    messages: list[DQLGenerateMessage]
    current_query: str | None = None
    model: str | None = None


class DQLGenerateResponse(BaseModel):
    """Response from DQL generation."""

    dql: str
    assistant_message: str
    execution: DQLExecuteResponse | None = None
    error: str | None = None
    used_tables: list[str] = Field(default_factory=list)


def _parse_model_option(model_str: str | None) -> ModelOption | None:
    """Parse a model string like 'openai/gpt-4o' into a ModelOption."""
    if not model_str:
        return None
    parts = model_str.split("/", 1)
    if len(parts) != 2:
        return None
    provider, model_name = parts
    return ModelOption(provider=provider, model_name=model_name)


@dql_router.post("/{collection_id}/generate")
async def generate_dql_query(
    collection_id: str,
    request: DQLGenerateRequest,
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_view_permission(Permission.READ)),
    mono_svc: MonoService = Depends(get_mono_svc),
    dql_svc: DQLService = Depends(get_dql_service),
    generator_svc: DQLGeneratorService = Depends(get_dql_generator_service),
    rubric_svc: RubricService = Depends(get_rubric_service),
) -> DQLGenerateResponse:
    """Generate a DQL query from natural language using an LLM."""
    if ctx.user is None:
        raise HTTPException(status_code=400, detail="User context unavailable.")

    if not request.messages:
        raise HTTPException(status_code=400, detail="At least one message is required.")

    json_fields = await mono_svc.get_json_metadata_fields_map(collection_id)
    model_override = _parse_model_option(request.model)

    # Fetch rubrics and convert to schema info for the generator
    rubrics_list = await rubric_svc.get_all_rubrics(collection_id, latest_only=True)
    rubric_schemas = [
        RubricSchemaInfo(
            id=rubric.id,
            version=rubric.version,
            name=rubric.rubric_text[:100] if rubric.rubric_text else None,
            output_fields=_extract_output_fields_from_schema(rubric.output_schema),
        )
        for rubric in rubrics_list
    ]

    messages = [
        DQLGeneratorMessage(
            role=msg.role,
            content=msg.content,
            query=msg.query,
        )
        for msg in request.messages
    ]

    try:
        outcome = await generator_svc.generate(
            ctx=ctx,
            messages=messages,
            current_query=request.current_query,
            model_override=model_override,
            json_fields=json_fields,
            rubric_schemas=rubric_schemas,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Build execution response if query ran successfully
    execution_response: DQLExecuteResponse | None = None
    if outcome.execution_result is not None:
        registry = build_default_registry(
            collection_id=collection_id,
            json_fields=json_fields,
        )
        service_link_hints, transcript_ids = dql_svc.build_link_hints(
            outcome.execution_result, registry=registry
        )
        transcript_id_map = await dql_svc.get_agent_run_ids_for_transcripts(
            collection_id=collection_id,
            transcript_ids=list(transcript_ids),
        )
        service_link_hints = dql_svc.attach_transcript_id_map(service_link_hints, transcript_id_map)
        link_hints = _convert_service_link_hints_to_response(service_link_hints)
        execution_response = _build_execute_response(outcome.execution_result, link_hints)

    return DQLGenerateResponse(
        dql=outcome.query,
        assistant_message=outcome.assistant_message,
        execution=execution_response,
        error=outcome.execution_error,
        used_tables=outcome.used_tables,
    )
