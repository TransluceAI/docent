from typing import Any, AsyncContextManager, Callable
from uuid import uuid4

import anyio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent_core._ai_tools.rubric.rubric import JudgeResult, Rubric, evaluate_rubric
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.rubric import SQLAJudgeResult, SQLARubric
from docent_core._db_service.schemas.tables import JobStatus, SQLAJob
from docent_core._db_service.service import MonoService
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent_core._server._broker.redis_client import enqueue_rubric_job
from docent_core._worker.constants import WorkerFunction

logger = get_logger(__name__)


class RubricService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        service: MonoService,
    ):
        """The `session_cm_factory` creates new sessions that commit writes immediately.
        This is helpful if you don't want to wait for results to be written."""

        self.session = session
        self.session_cm_factory = session_cm_factory
        self.service = service

    ###############
    # Rubric CRUD #
    ###############

    async def add_rubric(self, collection_id: str, rubric: Rubric) -> str:
        """Add a rubric to the database and return the rubric ID."""
        sqla_rubric = SQLARubric.from_pydantic(rubric, collection_id)
        self.session.add(sqla_rubric)
        return sqla_rubric.id

    async def get_rubrics(self, collection_id: str) -> list[Rubric]:
        """Get all rubrics for a collection."""
        result = await self.session.execute(
            select(SQLARubric).where(SQLARubric.collection_id == collection_id)
        )
        return [sqla_rubric.to_pydantic() for sqla_rubric in result.scalars().all()]

    async def update_rubric(self, rubric_id: str, rubric: Rubric):
        """Update a rubric."""
        await self.session.execute(
            update(SQLARubric)
            .where(SQLARubric.id == rubric_id)
            .values(
                high_level_description=rubric.high_level_description,
                inclusion_rules=rubric.inclusion_rules,
                exclusion_rules=rubric.exclusion_rules,
            )
        )

    async def delete_rubric(self, rubric_id: str):
        """Delete a rubric."""
        # First fetch the rubric object to enable cascade deletion
        rubric = await self.get_rubric(rubric_id)
        if rubric is not None:
            # Use ORM delete to trigger cascade
            await self.session.delete(rubric)

    ###############
    # Rubric jobs #
    ###############

    async def start_or_get_eval_rubric_job(self, ctx: ViewContext, rubric_id: str):
        """Start a job to evaluate the rubric."""

        # Is there already a job for this rubric?
        result = await self.session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.RUBRIC_JOB.value)
            .where(SQLAJob.job_json["rubric_id"].astext == rubric_id)
            .where((SQLAJob.status == JobStatus.PENDING) | (SQLAJob.status == JobStatus.RUNNING))
            .order_by(SQLAJob.created_at.desc())
            .limit(1)
        )
        existing_job: SQLAJob | None = result.scalar_one_or_none()
        if existing_job:
            return existing_job.id

        # There is no running job, create a new one
        job_id = str(uuid4())
        self.session.add(
            SQLAJob(
                id=job_id,
                type=WorkerFunction.RUBRIC_JOB.value,
                job_json={"rubric_id": rubric_id},
            )
        )

        # Enqueue the job
        await enqueue_rubric_job(ctx, job_id)

        return job_id

    async def get_rubric(self, rubric_id: str) -> SQLARubric | None:
        """Get a rubric from the database."""
        result = await self.session.execute(select(SQLARubric).where(SQLARubric.id == rubric_id))
        return result.scalar_one_or_none()

    async def run_rubric_job(self, ctx: ViewContext, job: SQLAJob):
        """Run a rubric job. Should only be called by the worker."""

        # Get the rubric
        rubric_id = job.job_json["rubric_id"]
        rubric = await self.get_rubric(rubric_id)
        if rubric is None:
            raise ValueError(f"Rubric {rubric_id} not found")

        # Get the agent runs
        agent_runs = await self.service.get_agent_runs(ctx)

        async def _callback(judge_results: list[JudgeResult] | None):
            if judge_results is None:
                return

            # Use the session_cm_factory to get a session that commits immediately
            async with self.session_cm_factory() as writer_session:
                writer_session.add_all(
                    [SQLAJudgeResult.from_pydantic(judge_result) for judge_result in judge_results]
                )

        # Run the search, saving data to the database as we go
        await evaluate_rubric(
            agent_runs,
            rubric.to_pydantic(),
            model_options=PROVIDER_PREFERENCES.execute_search,
            callback=_callback,
        )

    async def get_active_job_for_rubric(self, rubric_id: str) -> SQLAJob | None:
        return await self._get_pending_or_running_rubric_job(self.session, rubric_id)

    async def get_active_job_details_for_rubric(self, rubric_id: str) -> dict[str, Any] | None:
        """Get the complete job details for a rubric if it exists, otherwise None."""
        job = await self.get_active_job_for_rubric(rubric_id)
        if job:
            return {
                "id": job.id,
                "status": job.status.value,
                "created_at": job.created_at,
                "total_agent_runs": job.job_json.get("total_agent_runs"),
            }
        return None

    @staticmethod
    async def _get_pending_or_running_rubric_job(
        session: AsyncSession, rubric_id: str
    ) -> SQLAJob | None:
        """Has weird type signature because of the polling loop"""
        result = await session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.RUBRIC_JOB.value)
            .where(SQLAJob.job_json["rubric_id"].astext == rubric_id)
            .where((SQLAJob.status == JobStatus.PENDING) | (SQLAJob.status == JobStatus.RUNNING))
            .limit(1)
        )
        return result.scalar_one_or_none()

    ##################
    # Rubric results #
    ##################

    async def get_rubric_results(self, rubric_id: str) -> list[JudgeResult]:
        """Get the results of a rubric."""
        result = await self.session.execute(
            select(SQLAJudgeResult).where(SQLAJudgeResult.rubric_id == rubric_id)
        )
        sqla_results = result.scalars().all()
        return [sqla_result.to_pydantic() for sqla_result in sqla_results]

    async def poll_for_judge_results(self, rubric_id: str):
        """While there is a running job for this rubric, poll."""

        async def _get_job():
            """Requires a new session; otherwise, the poller will never see the updates to SQLAJob."""
            async with self.session_cm_factory() as session:
                return await self._get_pending_or_running_rubric_job(session, rubric_id)

        while (job := await _get_job()) is not None:
            results = await self.get_rubric_results(rubric_id)
            yield results, job.job_json.get("total_agent_runs", None)
            await anyio.sleep(1)

        # Final yield, just in case the above was never run (do-while)
        results = await self.get_rubric_results(rubric_id)
        yield results, None

    #############################
    # Clustering rubric results #
    #############################
