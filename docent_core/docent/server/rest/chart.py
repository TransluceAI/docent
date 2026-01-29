from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.filters import ComplexFilter
from docent_core.docent.db.schemas.auth_models import (
    Permission,
)
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.permissions import require_collection_permission
from docent_core.docent.server.dependencies.services import (
    get_chart_service,
    get_mono_svc,
)
from docent_core.docent.server.dependencies.user import (
    get_default_view_ctx,
)
from docent_core.docent.services.charts import (
    ChartSpec,
    ChartsService,
)
from docent_core.docent.services.monoservice import MonoService

chart_router = APIRouter()


################
# Dependencies #
################


async def require_chart_in_collection(
    collection_id: str,
    chart_id: str,
    chart_svc: ChartsService = Depends(get_chart_service),
) -> None:
    """Validate that chart belongs to collection. Raises 404 if not."""
    from sqlalchemy import select

    from docent_core.docent.db.schemas.chart import SQLAChart

    result = await chart_svc.session.execute(select(SQLAChart).where(SQLAChart.id == chart_id))
    chart = result.scalar_one_or_none()
    if chart is None or chart.collection_id != collection_id:
        raise HTTPException(
            status_code=404, detail=f"Chart {chart_id} not found in collection {collection_id}"
        )


class CreateChartRequest(BaseModel):
    name: str | None = None
    series_key: str | None = None
    x_key: str | None = None
    y_key: str | None = None
    chart_type: str = "bar"
    data_table_id: str | None = None


@chart_router.post("/{collection_id}/create")
async def create_chart(
    collection_id: str,
    request: CreateChartRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
) -> dict[str, str]:
    async with mono_svc.db.session() as session:
        chart_service = ChartsService(session, mono_svc.db)
        chart_id = await chart_service.create_chart(
            ctx=ctx,
            name=request.name,
            series_key=request.series_key,
            x_key=request.x_key,
            y_key=request.y_key,
            chart_type=request.chart_type,
            data_table_id=request.data_table_id,
        )

    analytics.track_event(
        "create_chart",
        properties={
            "collection_id": collection_id,
            "request": request.model_dump(),
        },
    )

    return {"id": chart_id}


class UpdateChartRequest(BaseModel):
    id: str
    name: str | None = None
    series_key: str | None = None
    x_key: str | None = None
    y_key: str | None = None
    chart_type: str = "bar"
    runs_filter: ComplexFilter | None = None
    data_table_id: str | None = None


@chart_router.post("/{collection_id}/{chart_id}")
async def update_chart(
    collection_id: str,
    chart_id: str,
    request: UpdateChartRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _chart: None = Depends(require_chart_in_collection),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    # Only include fields that were explicitly set in the request
    update_fields = {
        field: getattr(request, field)
        for field in request.model_fields_set
        if field not in {"id", "runs_filter"}  # Exclude fields with special handling
    }

    if request.runs_filter is not None:
        update_fields["runs_filter_dict"] = request.runs_filter.model_dump()
    elif "runs_filter" in request.model_fields_set:
        update_fields["runs_filter_dict"] = None

    async with mono_svc.db.session() as session:
        chart_service = ChartsService(session, mono_svc.db)
        await chart_service.update_chart(ctx=ctx, chart_id=chart_id, updates=update_fields)

    analytics.track_event(
        "update_chart",
        properties={
            "collection_id": collection_id,
            "request": request.model_dump(),
        },
    )

    return {"status": "ok"}


@chart_router.delete("/{collection_id}/{chart_id}")
async def delete_chart(
    collection_id: str,
    chart_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _chart: None = Depends(require_chart_in_collection),
):
    async with mono_svc.db.session() as session:
        chart_service = ChartsService(session, mono_svc.db)
        await chart_service.delete_chart(ctx, chart_id)

    return {"status": "ok"}


@chart_router.get("/{collection_id}")
async def get_charts(
    chart_service: ChartsService = Depends(get_chart_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[ChartSpec]:
    """Get all charts for the current view."""
    try:
        return await chart_service.get_charts(ctx)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get charts: {str(e)}")


class DataTableColumnResponse(BaseModel):
    name: str
    inferred_type: Literal["numeric", "categorical", "unknown"]


@chart_router.get("/{collection_id}/data-table/{data_table_id}/columns")
async def get_data_table_columns(
    collection_id: str,
    data_table_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[DataTableColumnResponse]:
    """Get columns from a data table's DQL query with inferred types."""
    try:
        async with mono_svc.db.session() as session:
            chart_service = ChartsService(session, mono_svc.db)
            columns = await chart_service.get_data_table_columns(ctx, data_table_id)
            return [
                DataTableColumnResponse(name=c.name, inferred_type=c.inferred_type) for c in columns
            ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get data table columns: {str(e)}")


@chart_router.get("/{collection_id}/{chart_id}/data")
async def get_chart_data(
    chart_id: str,
    chart_service: ChartsService = Depends(get_chart_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    _chart: None = Depends(require_chart_in_collection),
) -> dict[str, Any]:
    """Get chart data (binStats) for a specific chart."""
    try:
        # Get the chart specification
        chart = await chart_service.get_chart(ctx, chart_id)
        if not chart:
            raise HTTPException(status_code=404, detail="Chart not found")

        chart_data = await chart_service.get_chart_data(ctx, chart)
        return chart_data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chart data: {str(e)}")


@chart_router.get("/{collection_id}/metadata")
async def get_chart_metadata(
    chart_service: ChartsService = Depends(get_chart_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> dict[str, Any]:
    """Get chart metadata including available fields."""
    try:
        available = await chart_service.get_available_dimensions_and_measures(ctx)
        return {
            "dimensions": available.dimensions,
            "measures": available.measures,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chart metadata: {str(e)}")
