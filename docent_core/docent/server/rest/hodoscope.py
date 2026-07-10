from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import Permission
from docent_core.docent.server.dependencies.permissions import require_collection_permission
from docent_core.docent.server.dependencies.services import get_hodoscope_service
from docent_core.docent.server.dependencies.user import get_default_view_ctx
from docent_core.docent.services.hodoscope import (
    HodoscopeAnalysisConfig,
    HodoscopeAnalysisSummary,
    HodoscopeService,
)

hodoscope_router = APIRouter()


@hodoscope_router.post("/{collection_id}/analyses")
async def start_hodoscope_analysis(
    collection_id: str,
    request: HodoscopeAnalysisConfig,
    hodoscope_svc: HodoscopeService = Depends(get_hodoscope_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> HodoscopeAnalysisSummary:
    return await hodoscope_svc.start_or_get_analysis(ctx, request)


@hodoscope_router.get("/{collection_id}/analyses")
async def list_hodoscope_analyses(
    collection_id: str,
    hodoscope_svc: HodoscopeService = Depends(get_hodoscope_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[HodoscopeAnalysisSummary]:
    return await hodoscope_svc.list_analyses(ctx)


@hodoscope_router.get("/{collection_id}/analyses/{analysis_id}")
async def get_hodoscope_analysis(
    collection_id: str,
    analysis_id: str,
    hodoscope_svc: HodoscopeService = Depends(get_hodoscope_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> HodoscopeAnalysisSummary:
    analysis = await hodoscope_svc.get_analysis_summary(ctx, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Hodoscope analysis not found")
    return analysis


@hodoscope_router.get("/{collection_id}/analyses/{analysis_id}/projection")
async def get_hodoscope_projection(
    collection_id: str,
    analysis_id: str,
    compact: bool = False,
    hodoscope_svc: HodoscopeService = Depends(get_hodoscope_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> dict[str, Any]:
    analysis = await hodoscope_svc.get_analysis_summary(ctx, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Hodoscope analysis not found")
    projection = await hodoscope_svc.get_projection(ctx, analysis_id, compact=compact)
    if projection is None:
        raise HTTPException(status_code=409, detail="Hodoscope projection is not ready")
    return projection


@hodoscope_router.get("/{collection_id}/analyses/{analysis_id}/artifact")
async def get_hodoscope_artifact(
    collection_id: str,
    analysis_id: str,
    hodoscope_svc: HodoscopeService = Depends(get_hodoscope_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> dict[str, Any]:
    analysis = await hodoscope_svc.get_analysis_summary(ctx, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Hodoscope analysis not found")
    artifact = await hodoscope_svc.get_artifact(ctx, analysis_id)
    if artifact is None:
        raise HTTPException(status_code=409, detail="Hodoscope artifact is not ready")
    return artifact


@hodoscope_router.post("/{collection_id}/analyses/{analysis_id}/cancel")
async def cancel_hodoscope_analysis(
    collection_id: str,
    analysis_id: str,
    hodoscope_svc: HodoscopeService = Depends(get_hodoscope_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> HodoscopeAnalysisSummary:
    analysis = await hodoscope_svc.cancel_analysis(ctx, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Hodoscope analysis not found")
    return analysis
