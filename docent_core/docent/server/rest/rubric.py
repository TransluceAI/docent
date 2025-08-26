from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util.logger import get_logger
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES, ModelOption
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.ai_tools.rubric.rubric import JudgeResultWithCitations, Rubric
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.rubric import SQLARubric
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.database import get_session
from docent_core.docent.server.dependencies.permissions import (
    Permission,
    require_collection_permission,
)
from docent_core.docent.server.dependencies.services import (
    get_job_service,
    get_mono_svc,
    get_rubric_service,
)
from docent_core.docent.server.dependencies.user import get_default_view_ctx, get_user_anonymous_ok
from docent_core.docent.services import monoservice
from docent_core.docent.services.job import JobService
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService

rubric_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])

logger = get_logger(__name__)


################
# Dependencies #
################


async def get_rubric(
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
):
    sqla_rubric = await rubric_svc.get_rubric(rubric_id, version=None)
    if sqla_rubric is None:
        raise HTTPException(status_code=404, detail=f"Rubric {rubric_id} not found")
    return sqla_rubric


###############
# Rubric CRUD #
###############


class CreateRubricRequest(BaseModel):
    rubric: Rubric


@rubric_router.post("/{collection_id}/rubric")
async def create_rubric(
    collection_id: str,
    request: CreateRubricRequest,
    session: AsyncSession = Depends(get_session),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    return await rubric_svc.create_rubric(collection_id, request.rubric)


@rubric_router.get("/{collection_id}/rubric/{rubric_id}")
async def get_rubric_endpoint(
    collection_id: str,
    rubric_id: str,
    version: int | None = None,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> Rubric:
    rubric = await rubric_svc.get_rubric(rubric_id, version)
    if rubric is None:
        raise HTTPException(status_code=404, detail="Rubric not found")
    return rubric.to_pydantic()


class UpdateRubricRequest(BaseModel):
    rubric: Rubric


@rubric_router.put("/{collection_id}/rubric/{rubric_id}")
async def add_rubric_version(
    collection_id: str,
    rubric_id: str,
    request: UpdateRubricRequest,
    session: AsyncSession = Depends(get_session),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Update an existing rubric."""
    await rubric_svc.add_rubric_version(rubric_id, request.rubric)
    analytics.track_event(
        "update_rubric",
        properties={
            "collection_id": collection_id,
            "rubric_id": rubric_id,
            "rubric_version": request.rubric.version,
        },
    )


@rubric_router.get("/{collection_id}/rubrics")
async def get_rubrics(
    collection_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get all rubrics for a collection."""
    return await rubric_svc.get_all_rubrics(collection_id, latest_only=True)


@rubric_router.get("/{collection_id}/rubric/{rubric_id}/latest-version")
async def get_latest_rubric_version(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get the latest version number for a specific rubric."""
    latest_version = await rubric_svc.get_latest_rubric_version(rubric_id)
    if latest_version is None:
        raise HTTPException(status_code=404, detail="Rubric not found")
    return latest_version


@rubric_router.delete("/{collection_id}/rubric/{rubric_id}")
async def delete_rubric_all_versions(
    collection_id: str,
    rubric_id: str,
    session: AsyncSession = Depends(get_session),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Delete a rubric from a collection."""
    await rubric_svc.delete_rubric(rubric_id)


class DeleteFutureVersionsResponse(BaseModel):
    deleted_count: int


@rubric_router.delete("/{collection_id}/jobs/{job_id}")
async def cancel_job(
    collection_id: str,
    job_id: str,
    job_svc: JobService = Depends(get_job_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    await job_svc.cancel_job(job_id)
    return {"message": "Job cancelled successfully"}


#####################
# Rubric evaluation #
#####################


@rubric_router.delete("/{collection_id}/rubric/{rubric_id}/future-versions")
async def delete_future_versions(
    collection_id: str,
    rubric_id: str,
    after_version: int,
    session: AsyncSession = Depends(get_session),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Delete all versions of a rubric after a specific version."""
    deleted_count = await rubric_svc.delete_rubric_versions_after(rubric_id, after_version)
    return DeleteFutureVersionsResponse(deleted_count=deleted_count)


class StartEvalJobResponse(BaseModel):
    job_id: str


class StartClusteringJobRequest(BaseModel):
    clustering_feedback: str | None = None
    recluster: bool


@rubric_router.post("/{collection_id}/{rubric_id}/evaluate")
async def start_eval_rubric_job(
    collection_id: str,
    rubric_id: str,
    max_results: int | None = None,
    mono_svc: MonoService = Depends(get_mono_svc),
    rubric_svc: RubricService = Depends(get_rubric_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Start or get an existing evaluation job for the specified rubric."""

    # Get the rubric; check that it exists
    sqla_rubric = await rubric_svc.get_rubric(rubric_id, version=None)
    if sqla_rubric is None:
        raise HTTPException(status_code=404, detail=f"Rubric {rubric_id} not found")

    logger.info(f"Starting evaluation job for rubric {rubric_id} with max results {max_results}")
    job_id = await rubric_svc.start_or_get_eval_rubric_job(ctx, rubric_id, max_results)

    # Check if user has a custom API key (just for analytics purposes)
    is_byok = False
    if jm := sqla_rubric.judge_model:
        if ctx.user:
            overrides = await mono_svc.get_api_key_overrides(ctx.user.id)
            is_byok = jm.get("provider") in overrides
        else:
            is_byok = False
    else:
        is_byok = False

    analytics.track_event(
        "start_eval_rubric_job",
        properties={
            "collection_id": collection_id,
            "rubric_id": rubric_id,
            # Log the rubric content
            "text": sqla_rubric.rubric_text,
            "judge_model": sqla_rubric.judge_model,
            "is_byok": is_byok,
        },
    )

    return {"job_id": job_id}


@rubric_router.get("/{collection_id}/{rubric_id}/rubric_run_state")
async def get_rubric_run_state(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    # What's the ID of the job that's currently running, if any?
    cur_job = await rubric_svc.get_active_job_for_rubric(rubric_id)
    # Get current results
    results = await rubric_svc.get_rubric_results(rubric_id)
    results_parsed = [JudgeResultWithCitations.from_judge_result(result) for result in results]
    # Get the total number of agent runs
    total_agent_runs = cur_job.job_json.get("total_agent_runs") if cur_job else None

    return {
        "results": results_parsed,
        "job_id": cur_job.id if cur_job else None,
        "total_agent_runs": total_agent_runs,
    }


@rubric_router.get("/{collection_id}/{rubric_id}/job")
async def get_rubric_job_details(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get the complete job details for a rubric if it exists, otherwise None."""
    job = await rubric_svc.get_active_job_for_rubric(rubric_id)
    if job:
        return {
            "id": job.id,
            "status": job.status.value,
            "created_at": job.created_at,
            "total_agent_runs": job.job_json.get("total_agent_runs"),
        }
    return None


@rubric_router.get("/judge-models")
async def get_judge_models(
    mono_svc: monoservice.MonoService = Depends(get_mono_svc),
    user: User = Depends(get_user_anonymous_ok),
):
    # Start with default judge models
    models: list[ModelOption] = PROVIDER_PREFERENCES.default_judge_models.copy()

    # Append user-available BYOK models
    api_keys: dict[str, str] = {}
    if not user.is_anonymous:
        api_keys = await mono_svc.get_api_key_overrides(user.id)
        models += [m for m in PROVIDER_PREFERENCES.byok_judge_models if m.provider in api_keys]

    # Return annotated list with whether each model requires a user-provided API key
    return [
        {
            "provider": m.provider,
            "model_name": m.model_name,
            "reasoning_effort": m.reasoning_effort,
            "uses_byok": m.provider in api_keys,
        }
        for m in models
    ]


##############
# Clustering #
##############


@rubric_router.post("/{collection_id}/{rubric_id}/cluster")
async def start_clustering_job(
    collection_id: str,
    request: StartClusteringJobRequest,
    sq_rubric: SQLARubric = Depends(get_rubric),
    rubric_svc: RubricService = Depends(get_rubric_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Start or get an existing clustering job for the specified rubric."""
    clustering_feedback = request.clustering_feedback
    recluster = request.recluster

    if not recluster and clustering_feedback is not None:
        raise HTTPException(
            status_code=400,
            detail="clustering_feedback must be null when recluster is false",
        )

    job_id = await rubric_svc.start_or_get_clustering_job(
        ctx, sq_rubric, clustering_feedback, recluster
    )

    analytics.track_event(
        "start_clustering_job",
        properties={
            "collection_id": collection_id,
            "rubric_id": sq_rubric.id,
            "clustering_feedback": clustering_feedback,
            "recluster": recluster,
        },
    )

    return {"job_id": job_id}


@rubric_router.get("/{collection_id}/{rubric_id}/clustering_job")
async def get_clustering_state(
    collection_id: str,
    sq_rubric: SQLARubric = Depends(get_rubric),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get the state of the clustering job for a rubric."""
    sq_job = await rubric_svc.get_active_clustering_job(sq_rubric.id)
    sq_centroids = await rubric_svc.get_centroids(sq_rubric.id, sq_rubric.version)
    assignments = await rubric_svc.get_centroid_assignments(sq_rubric.id, sq_rubric.version)

    return {
        "job_id": sq_job.id if sq_job else None,
        "centroids": [centroid.dict() for centroid in sq_centroids],
        "assignments": assignments,
    }


@rubric_router.delete("/{collection_id}/{rubric_id}/clear_clusters")
async def clear_clusters(
    collection_id: str,
    sq_rubric: SQLARubric = Depends(get_rubric),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Clear all centroids (and cascaded assignments) for the latest version of a rubric."""
    await rubric_svc.clear_centroids(sq_rubric.id, sq_rubric.version)
