from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from docent._log_util import get_logger
from docent.data_models.chat.message import SystemMessage, UserMessage
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import Permission
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.permissions import require_collection_permission
from docent_core.docent.server.dependencies.services import (
    get_data_table_service,
    get_llm_svc,
    get_mono_svc,
    get_rubric_service,
)
from docent_core.docent.server.dependencies.user import get_default_view_ctx
from docent_core.docent.services.data_tables import (
    DEFAULT_DATA_TABLE_DQL,
    DataTableSpec,
    DataTablesService,
    RubricInfo,
    build_default_data_table_dql,
)
from docent_core.docent.services.llms import PROVIDER_PREFERENCES, LLMService
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService

logger = get_logger(__name__)

data_table_router = APIRouter()


class DataTableResponse(BaseModel):
    id: str
    collection_id: str
    name: str
    dql: str
    state: dict[str, Any] | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class CreateDataTableRequest(BaseModel):
    name: str | None = None
    dql: str | None = None
    state: dict[str, Any] | None = None


class UpdateDataTableRequest(BaseModel):
    name: str | None = None
    dql: str | None = None
    state: dict[str, Any] | None = None


class GenerateNameRequest(BaseModel):
    dql: str


class GenerateNameResponse(BaseModel):
    name: str


def _serialize_data_table(data_table: DataTableSpec) -> DataTableResponse:
    return DataTableResponse(**data_table.model_dump())


def _get_metadata_field_name(field: Any) -> str | None:
    if isinstance(field, dict):
        field_dict = cast(dict[str, Any], field)
        name = field_dict.get("name")
        return name if isinstance(name, str) else None
    name = getattr(field, "name", None)
    return name if isinstance(name, str) else None


def _extract_output_fields_from_schema(output_schema: dict[str, Any]) -> list[str]:
    """Extract field names from a JSON Schema's properties."""
    if not output_schema:
        return []
    properties = output_schema.get("properties")
    if properties is None or not isinstance(properties, dict):
        return []
    props_dict = cast(dict[str, Any], properties)
    return sorted(props_dict.keys())


@data_table_router.get("/{collection_id}")
async def list_data_tables(
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
    data_table_service: DataTablesService = Depends(get_data_table_service),
) -> list[DataTableResponse]:
    data_tables = await data_table_service.list_data_tables(ctx)
    return [_serialize_data_table(row) for row in data_tables]


@data_table_router.get("/{collection_id}/table/{data_table_id}")
async def get_data_table(
    data_table_id: str,
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
    data_table_service: DataTablesService = Depends(get_data_table_service),
) -> DataTableResponse:
    data_table = await data_table_service.get_data_table(ctx, data_table_id)
    if data_table is None:
        raise HTTPException(status_code=404, detail="Data table not found.")
    return _serialize_data_table(data_table)


@data_table_router.post("/{collection_id}")
async def create_data_table(
    collection_id: str,
    request: CreateDataTableRequest,
    ctx: ViewContext = Depends(get_default_view_ctx),
    mono_svc: MonoService = Depends(get_mono_svc),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    data_table_service: DataTablesService = Depends(get_data_table_service),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
) -> DataTableResponse:
    metadata_fields: list[str] | None = None
    rubrics: list[RubricInfo] | None = None

    if request.dql is None or not request.dql.strip():
        # Fetch metadata fields
        metadata_fields = sorted(
            [
                field_name
                for field in await mono_svc.get_agent_run_metadata_fields(ctx)
                for field_name in [_get_metadata_field_name(field)]
                if field_name is not None and field_name.startswith("metadata.")
            ]
        )

        # Fetch rubrics with results to include in default query
        all_rubrics = await rubric_svc.get_all_rubrics(collection_id, latest_only=True)
        rubrics_with_results: list[RubricInfo] = []
        for rubric in all_rubrics:
            stats = await rubric_svc.get_rubric_version_stats(rubric.id)
            if stats is None:
                continue
            _sqla_rubric, result_count = stats
            if result_count > 0:
                output_fields = _extract_output_fields_from_schema(rubric.output_schema)
                rubrics_with_results.append(
                    RubricInfo(
                        id=rubric.id,
                        version=rubric.version,
                        output_fields=output_fields,
                    )
                )
        rubrics = rubrics_with_results if rubrics_with_results else None

    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        data_table = await data_table_service.create_data_table(
            ctx,
            name=request.name,
            dql=request.dql,
            state=request.state,
            metadata_fields=metadata_fields,
            rubrics=rubrics,
        )

    analytics.track_event(
        "data_table_created",
        properties={
            "collection_id": collection_id,
            "data_table_id": data_table.id,
        },
    )
    return _serialize_data_table(data_table)


NAME_GENERATION_SYSTEM_PROMPT = """You generate short, descriptive names for data tables based on their SQL/DQL queries.

Given a query, generate a concise name (2-5 words) that describes what data the query retrieves.
Focus on the main entities and any key filters or aggregations.

Examples:
- "SELECT * FROM agent_runs ORDER BY created_at DESC" → "Recent Runs"
- "SELECT ar.*, jr.output FROM agent_runs ar JOIN judge_results jr..." → "Runs with Evaluations"
- "SELECT name, COUNT(*) FROM agent_runs GROUP BY name" → "Runs by Name"
- "SELECT * FROM agent_runs WHERE metadata_json->>'status' = 'failed'" → "Failed Runs"

Respond with ONLY the name, nothing else. No quotes, no explanation."""


@data_table_router.post("/{collection_id}/generate-name")
async def generate_data_table_name(
    request: GenerateNameRequest,
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    llm_svc: LLMService = Depends(get_llm_svc),
) -> GenerateNameResponse:
    """Generate a descriptive name for a data table based on its DQL query."""
    try:
        outputs = await llm_svc.get_completions(
            inputs=[
                [
                    SystemMessage(content=NAME_GENERATION_SYSTEM_PROMPT),
                    UserMessage(content=f"Query:\n{request.dql}"),
                ]
            ],
            model_options=PROVIDER_PREFERENCES.default_chat_models,
            max_new_tokens=50,
            temperature=0.3,
            use_cache=True,
        )

        result = outputs[0]
        if result.did_error or result.first is None or not result.first.text:
            logger.warning("Failed to generate data table name: %s", result.errors)
            return GenerateNameResponse(name="Data View")

        generated_name = result.first.text.strip().strip("\"'")
        # Truncate if too long
        if len(generated_name) > 50:
            generated_name = generated_name[:47] + "..."

        return GenerateNameResponse(name=generated_name)
    except Exception as e:
        logger.warning("Error generating data table name: %s", e)
        return GenerateNameResponse(name="Data View")


@data_table_router.post("/{collection_id}/table/{data_table_id}")
async def update_data_table(
    collection_id: str,
    data_table_id: str,
    request: UpdateDataTableRequest,
    ctx: ViewContext = Depends(get_default_view_ctx),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    data_table_service: DataTablesService = Depends(get_data_table_service),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
) -> DataTableResponse:
    metadata_fields: list[str] | None = None
    if "dql" in request.model_fields_set:
        dql_value = (request.dql or "").strip()
        if not dql_value:
            metadata_fields = sorted(
                [
                    field_name
                    for field in await mono_svc.get_agent_run_metadata_fields(ctx)
                    for field_name in [_get_metadata_field_name(field)]
                    if field_name is not None and field_name.startswith("metadata.")
                ]
            )
    updates: dict[str, Any] = {}
    if "name" in request.model_fields_set:
        name = (request.name or "").strip()
        updates["name"] = name or "Untitled data table"
    if "dql" in request.model_fields_set:
        dql = (request.dql or "").strip()
        if not dql and metadata_fields is not None:
            dql = build_default_data_table_dql(metadata_fields)
        updates["dql"] = dql or DEFAULT_DATA_TABLE_DQL
    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        # Merge state with existing state to avoid clobbering unrelated fields
        if "state" in request.model_fields_set:
            current = await data_table_service.get_data_table(ctx, data_table_id)
            current_state = current.state if current else None
            merged_state = {**(current_state or {}), **(request.state or {})}
            updates["state_json"] = merged_state

        data_table = await data_table_service.update_data_table(ctx, data_table_id, updates)

    analytics.track_event(
        "data_table_updated",
        properties={
            "collection_id": collection_id,
            "data_table_id": data_table_id,
        },
    )
    return _serialize_data_table(data_table)


@data_table_router.delete("/{collection_id}/table/{data_table_id}")
async def delete_data_table(
    collection_id: str,
    data_table_id: str,
    ctx: ViewContext = Depends(get_default_view_ctx),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    data_table_service: DataTablesService = Depends(get_data_table_service),
) -> dict[str, str]:
    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        await data_table_service.delete_data_table(ctx, data_table_id)
    return {"status": "ok"}


@data_table_router.post("/{collection_id}/table/{data_table_id}/duplicate")
async def duplicate_data_table(
    collection_id: str,
    data_table_id: str,
    ctx: ViewContext = Depends(get_default_view_ctx),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    data_table_service: DataTablesService = Depends(get_data_table_service),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
) -> DataTableResponse:
    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        data_table = await data_table_service.duplicate_data_table(ctx, data_table_id)

    analytics.track_event(
        "data_table_duplicated",
        properties={
            "collection_id": collection_id,
            "data_table_id": data_table.id,
        },
    )
    return _serialize_data_table(data_table)
