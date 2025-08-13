import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util.logger import get_logger
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.ai_tools.rubric.rubric import JudgeResultWithCitations, Rubric
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.database import get_db, get_mono_svc, get_session
from docent_core.docent.server.dependencies.permissions import (
    Permission,
    require_collection_permission,
)
from docent_core.docent.server.dependencies.services import get_job_service, get_rubric_service
from docent_core.docent.server.dependencies.user import get_default_view_ctx, get_user_anonymous_ok
from docent_core.docent.services.job import JobService
from docent_core.docent.services.monoservice import DocentDB, MonoService
from docent_core.docent.services.rubric import RubricService

rubric_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])

logger = get_logger(__name__)


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
async def get_rubric(
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
):
    """Update an existing rubric."""
    await rubric_svc.add_rubric_version(rubric_id, request.rubric)


@rubric_router.get("/{collection_id}/rubrics")
async def get_rubrics(
    collection_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get all rubrics for a collection."""
    return await rubric_svc.get_all_rubrics(collection_id, latest_only=False)


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


@rubric_router.post("/{collection_id}/{rubric_id}/evaluate")
async def start_eval_rubric_job(
    collection_id: str,
    rubric_id: str,
    max_results: int | None = None,
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

    analytics.track_event(
        "start_eval_rubric_job",
        properties={
            "collection_id": collection_id,
            "rubric_id": rubric_id,
            # Log the rubric content
            "high_level_description": sqla_rubric.high_level_description,
            "inclusion_rules": sqla_rubric.inclusion_rules,
            "exclusion_rules": sqla_rubric.exclusion_rules,
        },
    )

    return {"job_id": job_id}


@rubric_router.delete("/{collection_id}/jobs/{job_id}")
async def cancel_eval_job(
    collection_id: str,
    job_id: str,
    job_svc: JobService = Depends(get_job_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    await job_svc.cancel_job(job_id)
    return {"message": "Job cancelled successfully"}


@rubric_router.get("/{collection_id}/{rubric_id}/results/poll")
async def poll_judge_results(
    rubric_id: str,
    db: DocentDB = Depends(get_db),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Poll for judge results from a rubric evaluation (Server-Sent Events).
    NOTE: using dependency injection here will cause a silent failure.
        DI is supposed to clean up the session when the function exits. With SSEs,
        the function exits immediately. So the session must be owned by the generator.
    """

    async def generate():
        async with db.session() as session:
            rubric_svc = RubricService(session, db.session, mono_svc)

            async for job_id, results, total_agent_runs in rubric_svc.poll_for_judge_results(
                rubric_id
            ):
                # Convert JudgeResult objects to dictionaries for JSON serialization
                payload = {
                    "job_id": job_id,
                    "results": [
                        JudgeResultWithCitations.from_judge_result(result).model_dump()
                        for result in results
                    ],
                    "total_agent_runs": total_agent_runs,
                }
                yield f"data: {json.dumps(payload)}\n\n"

            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


@rubric_router.get("/{collection_id}/{rubric_id}/results")
async def get_rubric_results(
    collection_id: str,
    rubric_id: str,
    rubric_version: int,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get the judge results for a rubric."""
    results = await rubric_svc.get_rubric_results(rubric_id, rubric_version)
    return {
        "results": [
            JudgeResultWithCitations.from_judge_result(result).model_dump() for result in results
        ]
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


##############
# Clustering #
##############


class ProposeCentroidsRequest(BaseModel):
    feedback: str | None = None


@rubric_router.post("/{collection_id}/{rubric_id}/propose-centroids")
async def propose_centroids(
    collection_id: str,
    rubric_id: str,
    request: ProposeCentroidsRequest,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Propose centroids for a rubric and return them as dictionaries."""
    sqla_rubric = await rubric_svc.get_rubric(rubric_id, version=None)
    if sqla_rubric is None:
        raise HTTPException(status_code=404, detail=f"Rubric {rubric_id} not found")

    sqla_centroids = await rubric_svc.propose_centroids(sqla_rubric, request.feedback)

    analytics.track_event(
        "propose_centroids",
        properties={
            "collection_id": collection_id,
            "rubric_id": rubric_id,
            "feedback": request.feedback,
        },
    )

    return {"centroids": [centroid.dict() for centroid in sqla_centroids]}


@rubric_router.get("/{collection_id}/{rubric_id}/centroids")
async def get_centroids(
    collection_id: str,
    rubric_id: str,
    rubric_version: int | None = None,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Get existing centroids for a rubric."""
    sqla_centroids = await rubric_svc.get_centroids(rubric_id, rubric_version)

    analytics.track_event(
        "get_centroids", properties={"collection_id": collection_id, "rubric_id": rubric_id}
    )

    return {"centroids": [centroid.dict() for centroid in sqla_centroids]}


@rubric_router.delete("/{collection_id}/{rubric_id}/centroids")
async def clear_centroids(
    collection_id: str,
    rubric_id: str,
    rubric_version: int,
    session: AsyncSession = Depends(get_session),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Clear all centroids for a rubric."""
    await rubric_svc.clear_centroids(rubric_id, rubric_version)


@rubric_router.post("/{collection_id}/{rubric_id}/assign-centroids")
async def start_centroid_assignment_job(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Start or get an existing centroid assignment job for the specified rubric."""
    job_id = await rubric_svc.start_or_get_centroid_assignment_job(ctx, rubric_id)

    analytics.track_event(
        "start_centroid_assignment_job",
        properties={"collection_id": collection_id, "rubric_id": rubric_id},
    )

    return {"job_id": job_id}


@rubric_router.get("/{collection_id}/{rubric_id}/assignments/poll")
async def poll_centroid_assignments(
    rubric_id: str,
    db: DocentDB = Depends(get_db),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Poll for centroid assignment results (Server-Sent Events).
    NOTE: using dependency injection here will cause a silent failure.
        DI is supposed to clean up the session when the function exits. With SSEs,
        the function exits immediately. So the session must be owned by the generator.
    """

    async def generate():
        async with db.session() as session:
            rubric_svc = RubricService(session, db.session, mono_svc)

            async for job_id, assignments in rubric_svc.poll_for_centroid_assignments(rubric_id):
                payload = {"job_id": job_id, "assignments": assignments}
                yield f"data: {json.dumps(payload)}\n\n"

            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


@rubric_router.get("/{collection_id}/{rubric_id}/assignments")
async def get_centroid_assignments(
    collection_id: str,
    rubric_id: str,
    rubric_version: int,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get centroid assignments for a rubric."""
    assignments = await rubric_svc.get_centroid_assignments(rubric_id, rubric_version)
    return {"assignments": assignments}


@rubric_router.get("/{collection_id}/{rubric_id}/assignment-job")
async def get_assignment_job_details(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get the complete job details for a centroid assignment job if it exists, otherwise None."""
    job = await rubric_svc.get_active_assignment_job_for_rubric(rubric_id)
    if job:
        return {
            "id": job.id,
            "status": job.status.value,
            "created_at": job.created_at,
        }
    return None
