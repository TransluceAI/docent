from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from docent._llm_util.providers.preference_types import merge_models_with_byok
from docent._log_util.logger import get_logger
from docent.judges import JudgeResultWithCitations, ResultType, Rubric
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.ai_tools.rubric.reflect import JudgeReflection
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.rubric import SQLARubric
from docent_core.docent.db.schemas.tables import JobStatus
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
from docent_core.docent.services.llms import PROVIDER_PREFERENCES
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


class RubricMetricsResponse(BaseModel):
    latest_version: int
    judge_result_count: int


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


@rubric_router.get("/{collection_id}/result/{result_id}")
async def get_result_by_id(
    collection_id: str,
    result_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> JudgeResultWithCitations:
    """Get the full judge result (with citations parsed) by result ID."""
    result = await rubric_svc.get_rubric_result_by_id(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Judge result not found")

    # Fetch the matching rubric schema for the result's rubric/version so we can parse citations
    sqla_rubric = await rubric_svc.get_rubric(result.rubric_id, result.rubric_version)
    if sqla_rubric is None:
        raise HTTPException(status_code=404, detail="Rubric version not found for result")

    results = await rubric_svc.resolve_result_citations(
        [result], sqla_rubric.output_schema, ctx, persist=True
    )
    return results[0]


@rubric_router.get("/{collection_id}/rubric/{rubric_id}/metrics")
async def get_rubric_metrics(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> RubricMetricsResponse:
    stats = await rubric_svc.get_rubric_version_stats(rubric_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Rubric not found")

    latest_rubric, judge_result_count = stats
    if latest_rubric.collection_id != collection_id:
        raise HTTPException(status_code=404, detail="Rubric not found")

    return RubricMetricsResponse(
        latest_version=latest_rubric.version,
        judge_result_count=judge_result_count,
    )


@rubric_router.get("/{collection_id}/rubric/{rubric_id}/result/{agent_run_id}")
async def get_result_by_agent_run(
    collection_id: str,
    rubric_id: str,
    agent_run_id: str,
    version: int,
    rubric_svc: RubricService = Depends(get_rubric_service),
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> JudgeResultWithCitations:
    """Get a single judge result by agent run, rubric id, and rubric version.

    Returns the result parsed with the rubric's output schema as citations.
    """
    # Fetch the judge result
    result = await rubric_svc.get_rubric_result_by_agent_run(
        agent_run_id=agent_run_id, rubric_id=rubric_id, rubric_version=version
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Judge result not found")

    # Ensure rubric/version exists and use schema to parse citations
    sqla_rubric = await rubric_svc.get_rubric(rubric_id, version)
    if sqla_rubric is None:
        raise HTTPException(status_code=404, detail="Rubric version not found")

    results = await rubric_svc.resolve_result_citations(
        [result], sqla_rubric.output_schema, ctx, persist=True
    )
    return results[0]


@rubric_router.get("/{collection_id}/rubric/{rubric_id}/agent_run/{agent_run_id}/reflection")
async def get_agent_run_reflection(
    collection_id: str,
    rubric_id: str,
    agent_run_id: str,
    version: int,
    label_set_id: str | None = None,
    force_recompute: bool = False,
    rubric_svc: RubricService = Depends(get_rubric_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> JudgeReflection:
    """Get the reflection analysis for an agent_run's multi-rollout judge results.

    Returns structured summaries and the independent rollouts that were reflected on.
    If reflection exists in DB: returns it directly (200 OK)
    If not exists: starts background job and waits for completion (blocks until ready)
    Returns 404 if the agent_run has no multi-rollout results.

    Args:
        collection_id: The collection ID
        rubric_id: The rubric ID
        agent_run_id: The agent run ID
        version: The rubric version
        label_set_id: Optional label set ID to filter labels by
        force_recompute: If true, recompute the reflection even if it exists in DB
    """
    # Try to get the reflection from DB if not forcing recompute
    if not force_recompute:
        results = await rubric_svc.get_reflections_for_agent_runs(
            [agent_run_id], rubric_id, version, label_set_id=label_set_id
        )
        reflection = results.get(agent_run_id)
        if reflection is not None:
            # Reflection exists - return it directly
            return reflection

    # Start or get existing reflection job (force new if recomputing)
    job_id = await rubric_svc.start_or_get_reflection_job(
        ctx, agent_run_id, rubric_id, version, label_set_id=label_set_id, force_new=force_recompute
    )

    # Wait for reflection to complete and return it
    reflection = await rubric_svc.wait_for_reflection_result(
        job_id, agent_run_id, rubric_id, version, label_set_id=label_set_id
    )

    if reflection is None:
        raise HTTPException(status_code=500, detail="Reflection computation failed or timed out")

    return reflection


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


class AgentRunJudgeResults(BaseModel):
    agent_run_id: str
    rubric_id: str
    rubric_version: int
    results: list[JudgeResultWithCitations]
    reflection: JudgeReflection | None


class RubricRunStateResponse(BaseModel):
    results: list[AgentRunJudgeResults]
    job_id: str | None
    job_status: JobStatus | None
    total_results_needed: int | None
    current_results_count: int | None


class RubricCentroidResponse(BaseModel):
    id: str
    collection_id: str
    rubric_id: str
    rubric_version: int
    centroid: str
    result_type: ResultType


class ClusteringStateResponse(BaseModel):
    job_id: str | None
    job_status: JobStatus | None
    centroids: list[RubricCentroidResponse]
    assignments: dict[str, list[str]]


class StartFilteredEvalJobRequest(BaseModel):
    max_agent_runs: int | None = None
    n_rollouts_per_input: int = 1
    label_set_id: str | None = None
    filter: dict[str, Any] | None = None


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
        f"Starting evaluation job for rubric {rubric_id} with max results {request.max_agent_runs} "
        f"and {request.n_rollouts_per_input} rollouts per input"
    )
    job_id = await rubric_svc.start_or_get_eval_rubric_job(
        ctx,
        rubric_id,
        request.max_agent_runs,
        request.n_rollouts_per_input,
        request.label_set_id,
        request.filter,
    )

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
    label_set_id: str | None = None,
    sqla_rubric_latest: SQLARubric = Depends(get_rubric),
    rubric_svc: RubricService = Depends(get_rubric_service),
    mono_svc: MonoService = Depends(get_mono_svc),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> RubricRunStateResponse:
    if version is not None:
        sqla_rubric_for_schema = await rubric_svc.get_rubric(rubric_id, version)
        if sqla_rubric_for_schema is None:
            # If requested version doesn't exist, behave like empty results
            return RubricRunStateResponse(
                results=[],
                job_id=None,
                job_status=None,
                total_results_needed=None,
                current_results_count=None,
            )
    else:
        sqla_rubric_for_schema = sqla_rubric_latest

    # What's the ID of the job that's currently running, if any?
    cur_job = None
    total_results_needed = None
    current_results_count = None
    agent_run_ids_being_processed: list[str] = []
    # Make sure that we're not pushing job status for versions other than the latest
    if version is None or version == sqla_rubric_latest.version:
        cur_job = await rubric_svc.get_active_job_for_rubric(rubric_id)
        if cur_job:
            agent_run_ids_being_processed = cur_job.job_json.get(
                "agent_run_ids_being_processed", []
            )

    # Get current results for the specified version (defaults to latest inside service)
    results = await rubric_svc.get_rubric_results(rubric_id, version)

    # Resolve and store citations for old judge results that don't have them
    results_parsed = await rubric_svc.resolve_result_citations(
        results, sqla_rubric_for_schema.output_schema, ctx, persist=True
    )

    # Group results by agent_run_id
    from collections import defaultdict

    grouped_results: dict[str, list[JudgeResultWithCitations]] = defaultdict(list)
    for result in results_parsed:
        grouped_results[result.agent_run_id].append(result)

    # Batch fetch all reflections at once
    agent_run_ids = list(grouped_results.keys())
    reflections_map = await rubric_svc.get_reflections_for_agent_runs(
        agent_run_ids, rubric_id, version or sqla_rubric_latest.version, label_set_id
    )

    # Build agent run results
    agent_run_results: list[AgentRunJudgeResults] = []
    for agent_run_id, agent_results in grouped_results.items():
        reflection = reflections_map.get(agent_run_id)
        agent_run_results.append(
            AgentRunJudgeResults(
                agent_run_id=agent_run_id,
                rubric_id=rubric_id,
                rubric_version=version or sqla_rubric_latest.version,
                results=agent_results,
                reflection=reflection,
            )
        )

    # Calculate current results count for agent runs being processed by the job
    if cur_job and agent_run_ids_being_processed:
        n_rollouts = cur_job.job_json.get("n_rollouts_per_input", 1)
        agent_run_ids_set = set(agent_run_ids_being_processed)
        current_results_count = sum(
            min(len(results), n_rollouts)
            for agent_run_id, results in grouped_results.items()
            if agent_run_id in agent_run_ids_set
        )
        total_results_needed = len(agent_run_ids_being_processed) * n_rollouts

    return RubricRunStateResponse(
        results=agent_run_results,
        job_id=cur_job.id if cur_job else None,
        job_status=cur_job.status if cur_job else None,
        total_results_needed=total_results_needed,
        current_results_count=current_results_count,
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


@rubric_router.get(
    "/{collection_id}/{rubric_id}/clustering_job", response_model=ClusteringStateResponse
)
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

    return ClusteringStateResponse(
        job_id=sq_job.id if sq_job else None,
        job_status=sq_job.status if sq_job else None,
        centroids=[
            RubricCentroidResponse(
                id=centroid.id,
                collection_id=centroid.collection_id,
                rubric_id=centroid.rubric_id,
                rubric_version=centroid.rubric_version,
                centroid=centroid.centroid,
                result_type=centroid.result_type,
            )
            for centroid in sq_centroids
        ],
        assignments=assignments,
    )


@rubric_router.delete("/{collection_id}/{rubric_id}/clear_clusters")
async def clear_clusters(
    collection_id: str,
    sq_rubric: SQLARubric = Depends(get_rubric),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Clear all centroids (and cascaded assignments) for the latest version of a rubric."""
    await rubric_svc.clear_centroids(sq_rubric.id, sq_rubric.version)


class CopyRubricRequest(BaseModel):
    target_collection_id: str


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
