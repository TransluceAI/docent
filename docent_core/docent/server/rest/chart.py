from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.filters import ComplexFilter
from docent_core.docent.db.schemas.auth_models import (
    Permission,
)
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.permissions import (
    require_collection_permission,
)
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


class CreateChartRequest(BaseModel):
    name: str | None = None
    series_key: str | None = None
    x_key: str | None = None
    y_key: str | None = None
    chart_type: str = "bar"


@chart_router.post("/{collection_id}/create")
async def create_chart(
    collection_id: str,
    request: CreateChartRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
) -> dict[str, str]:
    async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
        async with mono_svc.db.session() as session:
            chart_service = ChartsService(session)
            chart_id = await chart_service.create_chart(
                ctx=ctx,
                name=request.name,
                series_key=request.series_key,
                x_key=request.x_key,
                y_key=request.y_key,
                chart_type=request.chart_type,
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


@chart_router.post("/{collection_id}")
async def update_chart(
    collection_id: str,
    request: UpdateChartRequest,
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
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
        chart_service = ChartsService(session)
        async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
            await chart_service.update_chart(ctx=ctx, chart_id=request.id, updates=update_fields)

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
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    async with mono_svc.db.session() as session:
        chart_service = ChartsService(session)
        async with mono_svc.advisory_lock(collection_id, action_id="mutation"):
            await chart_service.delete_chart(ctx, chart_id)

    return {"status": "ok"}


@chart_router.get("/{collection_id}")
async def get_charts(
    collection_id: str,
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


@chart_router.get("/{collection_id}/{chart_id}/data")
async def get_chart_data(
    collection_id: str,
    chart_id: str,
    chart_service: ChartsService = Depends(get_chart_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> dict[str, Any]:
    """Get chart data (binStats) for a specific chart."""
    try:
        # Get the chart specification
        chart = await chart_service.get_chart(ctx, chart_id)
        if not chart:
            raise HTTPException(status_code=404, detail="Chart not found")

        # Get chart data using the same logic as websocket publishing
        chart_data = await chart_service.get_chart_data(ctx, chart)
        return chart_data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chart data: {str(e)}")


@chart_router.get("/{collection_id}/metadata")
async def get_chart_metadata(
    collection_id: str,
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
