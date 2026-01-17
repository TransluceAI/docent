from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import Permission
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.permissions import require_collection_permission
from docent_core.docent.server.dependencies.services import get_data_table_service, get_mono_svc
from docent_core.docent.server.dependencies.user import get_default_view_ctx
from docent_core.docent.services.data_tables import (
    DEFAULT_DATA_TABLE_DQL,
    DataTableSpec,
    DataTablesService,
    build_default_data_table_dql,
)
from docent_core.docent.services.monoservice import MonoService

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


def _serialize_data_table(data_table: DataTableSpec) -> DataTableResponse:
    return DataTableResponse(**data_table.model_dump())


def _get_metadata_field_name(field: Any) -> str | None:
    if isinstance(field, dict):
        name = field.get("name")
        return name if isinstance(name, str) else None
    name = getattr(field, "name", None)
    return name if isinstance(name, str) else None


@data_table_router.get("/{collection_id}")
async def list_data_tables(
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
    data_table_service: DataTablesService = Depends(get_data_table_service),
) -> list[DataTableResponse]:
    data_tables = await data_table_service.list_data_tables(ctx)
    return [_serialize_data_table(row) for row in data_tables]


@data_table_router.get("/{collection_id}/{data_table_id}")
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
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    data_table_service: DataTablesService = Depends(get_data_table_service),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
) -> DataTableResponse:
    metadata_fields: list[str] | None = None
    if request.dql is None or not request.dql.strip():
        metadata_fields = sorted(
            [
                field_name
                for field in await mono_svc.get_agent_run_metadata_fields(ctx)
                for field_name in [_get_metadata_field_name(field)]
                if field_name is not None and field_name.startswith("metadata.")
            ]
        )

    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        data_table = await data_table_service.create_data_table(
            ctx,
            name=request.name,
            dql=request.dql,
            state=request.state,
            metadata_fields=metadata_fields,
        )

    analytics.track_event(
        "data_table_created",
        properties={
            "collection_id": collection_id,
            "data_table_id": data_table.id,
        },
    )
    return _serialize_data_table(data_table)


@data_table_router.post("/{collection_id}/{data_table_id}")
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
    if "state" in request.model_fields_set:
        updates["state_json"] = request.state

    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        data_table = await data_table_service.update_data_table(ctx, data_table_id, updates)

    analytics.track_event(
        "data_table_updated",
        properties={
            "collection_id": collection_id,
            "data_table_id": data_table_id,
        },
    )
    return _serialize_data_table(data_table)


@data_table_router.delete("/{collection_id}/{data_table_id}")
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


@data_table_router.post("/{collection_id}/{data_table_id}/duplicate")
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
