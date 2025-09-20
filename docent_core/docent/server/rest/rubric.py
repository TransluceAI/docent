from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util.logger import get_logger
from docent_core._llm_util.providers.preferences import (
    PROVIDER_PREFERENCES,
    merge_models_with_byok,
)
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.ai_tools.rubric.rubric import (
    JudgeResultWithCitations,
    JudgeRunLabel,
    Rubric,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.rubric import SQLARubric
from docent_core.docent.server.dependencies.analytics import (
    use_posthog_user_context,
)
from docent_core.docent.server.dependencies.database import get_session
from docent_core.docent.server.dependencies.permissions import (
    Permission,
    ResourceType,
    require_collection_permission,
)
from docent_core.docent.server.dependencies.services import (
    get_job_service,
    get_mono_svc,
    get_rubric_service,
)
from docent_core.docent.server.dependencies.user import (
    get_default_view_ctx,
    get_user_anonymous_ok,
)
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


class RubricRunStateResponse(BaseModel):
    results: list[JudgeResultWithCitations]
    job_id: str | None
    total_agent_runs: int | None


class StartFilteredEvalJobRequest(BaseModel):
    max_results: int | None = None


@rubric_router.post("/{collection_id}/{rubric_id}/evaluate")
async def start_eval_rubric_job(
    collection_id: str,
    rubric_id: str,
    request: StartFilteredEvalJobRequest,
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

    logger.info(
        f"Starting evaluation job for rubric {rubric_id} with max results {request.max_results}"
    )
    job_id = await rubric_svc.start_or_get_eval_rubric_job(ctx, rubric_id, request.max_results)

    # Check if user has a custom API key (just for analytics purposes)
    if ctx.user:
        overrides = await mono_svc.get_api_key_overrides(ctx.user)
        is_byok = sqla_rubric.judge_model.get("provider") in overrides
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
    version: int | None = None,
    sqla_rubric_latest: SQLARubric = Depends(get_rubric),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> RubricRunStateResponse:
    if version is not None:
        sqla_rubric_for_schema = await rubric_svc.get_rubric(rubric_id, version)
        if sqla_rubric_for_schema is None:
            # If requested version doesn't exist, behave like empty results
            return RubricRunStateResponse(results=[], job_id=None, total_agent_runs=None)
    else:
        sqla_rubric_for_schema = sqla_rubric_latest

    # What's the ID of the job that's currently running, if any?
    cur_job = None
    total_agent_runs = None
    # Make sure that we're not pushing job status for versions other than the latest
    if version is None or version == sqla_rubric_latest.version:
        cur_job = await rubric_svc.get_active_job_for_rubric(rubric_id)
        total_agent_runs = cur_job.job_json.get("total_agent_runs") if cur_job else None

    # Get current results for the specified version (defaults to latest inside service)
    results = await rubric_svc.get_rubric_results(rubric_id, version)

    results_parsed = [
        JudgeResultWithCitations.from_judge_result(result, sqla_rubric_for_schema.output_schema)
        for result in results
    ]

    return RubricRunStateResponse(
        results=results_parsed,
        job_id=cur_job.id if cur_job else None,
        total_agent_runs=total_agent_runs,
    )


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
    return merge_models_with_byok(
        defaults=PROVIDER_PREFERENCES.default_judge_models,
        byok=PROVIDER_PREFERENCES.byok_judge_models,
        api_keys=await mono_svc.get_api_key_overrides(user),
    )


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


###############
# Labels CRUD #
###############


class CreateRunLabelRequest(BaseModel):
    label: JudgeRunLabel


class DeleteRunLabelRequest(BaseModel):
    agent_run_id: str


class UpdateRunLabelRequest(BaseModel):
    agent_run_id: str
    label: dict[str, Any]


class CopyRubricRequest(BaseModel):
    target_collection_id: str


@rubric_router.post("/{collection_id}/rubric/{rubric_id}/label")
async def create_judge_run_label(
    collection_id: str,
    rubric_id: str,
    request: CreateRunLabelRequest,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Add a label to a judge result."""
    success = await rubric_svc.create_judge_run_label(request.label)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid JSON format in label")
    return {"message": "Label added successfully"}


@rubric_router.put("/{collection_id}/rubric/{rubric_id}/label")
async def update_judge_run_label(
    collection_id: str,
    rubric_id: str,
    request: UpdateRunLabelRequest,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Update a label for a judge result."""
    success = await rubric_svc.update_judge_run_label(request.agent_run_id, request.label)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid JSON format in label")
    return {"message": "Label updated successfully"}


@rubric_router.get("/{collection_id}/rubric/{rubric_id}/labels")
async def get_judge_run_labels(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[JudgeRunLabel]:
    """Get all labels for judge results of a rubric across all versions."""
    return await rubric_svc.get_judge_run_labels(rubric_id)


@rubric_router.get("/{collection_id}/rubric/{rubric_id}/label/{agent_run_id}")
async def get_judge_run_label(
    collection_id: str,
    rubric_id: str,
    agent_run_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> JudgeRunLabel | None:
    """Get a specific label for a judge result."""
    return await rubric_svc.get_judge_run_label(agent_run_id)


@rubric_router.delete("/{collection_id}/rubric/{rubric_id}/label")
async def delete_judge_run_label(
    collection_id: str,
    rubric_id: str,
    request: DeleteRunLabelRequest,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Delete a label from a judge result."""
    await rubric_svc.delete_judge_run_label(request.agent_run_id)
    return {"message": "Label deleted successfully"}


@rubric_router.delete("/{collection_id}/rubric/{rubric_id}/labels")
async def delete_all_judge_run_labels(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Delete all labels for a rubric."""
    await rubric_svc.delete_all_judge_run_labels(rubric_id)
    return {"message": "All labels deleted successfully"}


@rubric_router.post("/{collection_id}/rubric/{rubric_id}/copy")
async def copy_rubric(
    collection_id: str,
    rubric_id: str,
    request: CopyRubricRequest,
    rubric_svc: RubricService = Depends(get_rubric_service),
    mono_svc: MonoService = Depends(get_mono_svc),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Copy a rubric to another collection."""
    has_target_permission = await mono_svc.has_permission(
        user, ResourceType.COLLECTION, request.target_collection_id, Permission.WRITE
    )
    if not has_target_permission:
        raise HTTPException(status_code=403, detail="No write permission on target collection")

    new_rubric_id = await rubric_svc.copy_rubric_to_collection(
        rubric_id, request.target_collection_id
    )
    return {"rubric_id": new_rubric_id}
