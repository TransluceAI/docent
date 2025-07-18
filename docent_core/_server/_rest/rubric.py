import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from docent_core._ai_tools.rubric.rubric import JudgeResultWithCitations, Rubric
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.service import DocentDB, MonoService
from docent_core._server._dependencies.database import get_db, get_mono_svc, get_session
from docent_core._server._dependencies.permissions import Permission, require_collection_permission
from docent_core._server._dependencies.services import get_job_service, get_rubric_service
from docent_core._server._dependencies.user import get_default_view_ctx, get_user_anonymous_ok
from docent_core.services.job import JobService
from docent_core.services.rubric import RubricService

rubric_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


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
    await rubric_svc.add_rubric(collection_id, request.rubric)
    await session.flush()
    return await rubric_svc.get_rubrics(collection_id)


class UpdateRubricRequest(BaseModel):
    rubric: Rubric


class ProposeCentroidsRequest(BaseModel):
    feedback: str | None = None


@rubric_router.put("/{collection_id}/rubric/{rubric_id}")
async def update_rubric(
    collection_id: str,
    rubric_id: str,
    request: UpdateRubricRequest,
    session: AsyncSession = Depends(get_session),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Update an existing rubric."""
    await rubric_svc.update_rubric(rubric_id, request.rubric)
    await session.flush()
    return await rubric_svc.get_rubrics(collection_id)


@rubric_router.get("/{collection_id}/rubrics")
async def get_rubrics(
    collection_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get all rubrics for a collection."""
    return await rubric_svc.get_rubrics(collection_id)


@rubric_router.delete("/{collection_id}/rubric/{rubric_id}")
async def delete_rubric(
    collection_id: str,
    rubric_id: str,
    session: AsyncSession = Depends(get_session),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Delete a rubric from a collection."""
    await rubric_svc.delete_rubric(rubric_id)
    await session.flush()
    return await rubric_svc.get_rubrics(collection_id)


#####################
# Rubric evaluation #
#####################


@rubric_router.post("/{collection_id}/{rubric_id}/evaluate")
async def start_eval_rubric_job(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Start or get an existing evaluation job for the specified rubric."""
    job_id = await rubric_svc.start_or_get_eval_rubric_job(ctx, rubric_id)
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


@rubric_router.post("/{collection_id}/{rubric_id}/propose-centroids")
async def propose_centroids(
    collection_id: str,
    rubric_id: str,
    request: ProposeCentroidsRequest,
    session: AsyncSession = Depends(get_session),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Propose centroids for a rubric and return them as dictionaries."""
    sqla_rubric = await rubric_svc.get_rubric(rubric_id)
    if sqla_rubric is None:
        raise HTTPException(status_code=404, detail=f"Rubric {rubric_id} not found")

    sqla_centroids = await rubric_svc.propose_centroids(sqla_rubric, request.feedback)
    return {"centroids": [centroid.dict() for centroid in sqla_centroids]}


@rubric_router.get("/{collection_id}/{rubric_id}/centroids")
async def get_centroids(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get existing centroids for a rubric."""
    sqla_centroids = await rubric_svc.get_centroids(rubric_id)
    return {"centroids": [centroid.dict() for centroid in sqla_centroids]}


@rubric_router.delete("/{collection_id}/{rubric_id}/centroids")
async def clear_centroids(
    collection_id: str,
    rubric_id: str,
    session: AsyncSession = Depends(get_session),
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Clear all centroids for a rubric."""
    await rubric_svc.clear_centroids(rubric_id)


@rubric_router.post("/{collection_id}/{rubric_id}/assign-centroids")
async def start_centroid_assignment_job(
    collection_id: str,
    rubric_id: str,
    rubric_svc: RubricService = Depends(get_rubric_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Start or get an existing centroid assignment job for the specified rubric."""
    job_id = await rubric_svc.start_or_get_centroid_assignment_job(ctx, rubric_id)
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
    rubric_svc: RubricService = Depends(get_rubric_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get centroid assignments for a rubric."""
    assignments = await rubric_svc.get_centroid_assignments(rubric_id)
    return {"assignments": assignments}
