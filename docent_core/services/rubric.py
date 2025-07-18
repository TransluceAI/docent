from typing import AsyncContextManager, Callable, Sequence, cast
from uuid import uuid4

import anyio
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent_core._ai_tools.clustering.cluster_assigner import DEFAULT_ASSIGNER, assign_with_backend
from docent_core._ai_tools.clustering.cluster_generator import ClusterFeedback, propose_clusters
from docent_core._ai_tools.rubric.rubric import JudgeResult, Rubric, evaluate_rubric
from docent_core._db_service.batched_writer import BatchedWriter
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.rubric import (
    SQLAJudgeResult,
    SQLAJudgeResultCentroid,
    SQLARubric,
    SQLARubricCentroid,
)
from docent_core._db_service.schemas.tables import JobStatus, SQLAAgentRun, SQLAJob
from docent_core._db_service.service import MonoService
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent_core._server._broker.redis_client import enqueue_job
from docent_core._worker.constants import WorkerFunction
from docent_core.services.job import JobService

logger = get_logger(__name__)

MAX_RUBRIC_RESULTS = 50


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
        self.job_svc = JobService(session, session_cm_factory)

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

        # Cancel jobs and clear centroids and results (should cascade to assignments)
        await self.clear_rubric_results(rubric_id)
        await self.clear_centroids(rubric_id)

        # Finally, update the rubric
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

        # First cancel any jobs involving this rubric
        await self.cancel_active_rubric_eval_job(rubric_id)
        await self.cancel_active_centroid_assignment_job(rubric_id)

        # Then use ORM delete to trigger cascade
        rubric = await self.get_rubric(rubric_id)
        if rubric is not None:
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
        await enqueue_job(ctx, job_id)

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

        # Filter out agent runs with existing judge results
        result = await self.session.execute(
            select(SQLAAgentRun.id).where(
                SQLAAgentRun.collection_id == ctx.collection_id,
                ~exists().where(
                    SQLAJudgeResult.agent_run_id == SQLAAgentRun.id,
                    SQLAJudgeResult.rubric_id == rubric_id,
                ),
            )
        )
        agent_run_ids = cast(list[str], result.scalars().all())
        if len(agent_run_ids) == 0:
            logger.info("Skipping rubric evaluation because no agent runs are missing results")
            return

        logger.info(f"Evaluating rubrics for {len(agent_run_ids)} agent runs missing results")
        agent_runs = await self.service.get_agent_runs(ctx, agent_run_ids=agent_run_ids)

        num_results = 0
        cancellation_event = anyio.Event()

        async with BatchedWriter(self.session_cm_factory) as writer:

            async def _callback(judge_results: list[JudgeResult] | None):
                if judge_results is None:
                    return

                nonlocal num_results
                num_results += sum(1 for j in judge_results if j.value is not None)

                await writer.add_all(
                    [SQLAJudgeResult.from_pydantic(judge_result) for judge_result in judge_results]
                )

                if num_results >= MAX_RUBRIC_RESULTS and not cancellation_event.is_set():
                    cancellation_event.set()

            # Run the search, saving data to the database as we go
            await evaluate_rubric(
                agent_runs,
                rubric.to_pydantic(),
                model_options=PROVIDER_PREFERENCES.execute_search,
                callback=_callback,
                cancellation_event=cancellation_event,
            )

    async def get_active_job_for_rubric(self, rubric_id: str) -> SQLAJob | None:
        return await self._get_active_rubric_job(self.session, rubric_id)

    @staticmethod
    async def _get_active_rubric_job(session: AsyncSession, rubric_id: str) -> SQLAJob | None:
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

    async def cancel_active_rubric_eval_job(self, rubric_id: str):
        job = await self.get_active_job_for_rubric(rubric_id)
        if job:
            await self.job_svc.cancel_job(job.id)

    async def poll_for_judge_results(self, rubric_id: str):
        """While there is a running job for this rubric, poll."""

        async def _get_job():
            """Requires a new session; otherwise, the poller will never see the updates to SQLAJob."""
            async with self.session_cm_factory() as session:
                return await self._get_active_rubric_job(session, rubric_id)

        while (job := await _get_job()) is not None:
            results = await self.get_rubric_results(rubric_id)
            yield job.id, results, job.job_json.get("total_agent_runs", None)
            await anyio.sleep(1)

        # Final yield, just in case the above was never run (do-while)
        results = await self.get_rubric_results(rubric_id)
        yield None, results, None

    async def clear_rubric_results(self, rubric_id: str):
        """Clear all results for a rubric."""
        # First cancel any jobs involving this rubric
        await self.cancel_active_rubric_eval_job(rubric_id)

        result = await self.session.execute(
            select(SQLAJudgeResult).where(SQLAJudgeResult.rubric_id == rubric_id)
        )
        results = result.scalars().all()
        for result in results:
            await self.session.delete(result)

    #############################
    # Clustering rubric results #
    #############################

    async def propose_centroids(
        self,
        sqla_rubric: SQLARubric,
        feedback: str | None = None,
    ) -> Sequence[SQLARubricCentroid]:
        """Cluster judge results and store cluster information with the judge results.
        If feedback is not None, current centroids will be overwritten."""
        rubric = sqla_rubric.to_pydantic()

        # If there are already centroids, skip centroid generation
        cur_sqla_centroids = await self.get_centroids(sqla_rubric.id)
        if len(cur_sqla_centroids) > 0 and feedback is None:
            logger.info(
                f"Skipping centroid generation for rubric {sqla_rubric.id} because it already has {len(cur_sqla_centroids)} centroids"
            )
            return cur_sqla_centroids

        # Delete existing centroids (cascade) and cancel jobs, but save the strings
        cur_centroid_strs = [c.centroid for c in cur_sqla_centroids]
        await self.clear_centroids(sqla_rubric.id)
        await self.session.flush()

        # Get all non-null judge results for this rubric
        judge_results = await self.get_rubric_results(rubric.id)
        judge_results = [jr for jr in judge_results if jr.value is not None]
        if not judge_results:
            logger.info(f"No judge results with values found for rubric {rubric.id}")
            return []
        # Separate the values because clustering just takes the values
        judge_result_values = cast(
            list[str], [jr.value for jr in judge_results]
        )  # We already filtered out the None values

        # Propose centroids
        guidance = f"These are results for the rubric: {rubric.text}"
        centroids: list[str] = await propose_clusters(
            judge_result_values,
            extra_instructions_list=[guidance],
            feedback_list=(
                [
                    ClusterFeedback(
                        clusters=cur_centroid_strs,
                        feedback=feedback,
                    )
                ]
                if feedback is not None and feedback != ""
                else None
            ),
        )
        logger.info(f"Proposed {len(centroids)} centroids")

        sqla_centroids: list[SQLARubricCentroid] = [
            SQLARubricCentroid(
                id=str(uuid4()),
                collection_id=sqla_rubric.collection_id,
                rubric_id=rubric.id,
                centroid=centroid,
            )
            for centroid in centroids
        ]
        # Use a separate session that self-commits, so results are immediately available
        async with self.session_cm_factory() as session:
            session.add_all(sqla_centroids)

        return sqla_centroids

    async def get_centroids(self, rubric_id: str):
        """Get existing clusters for a rubric."""
        result = await self.session.execute(
            select(SQLARubricCentroid).where(SQLARubricCentroid.rubric_id == rubric_id)
        )
        return result.scalars().all()

    async def clear_centroids(self, rubric_id: str):
        """Clear all centroids for a rubric along with their assignments (cascaded)."""

        # First cancel the job so it doesn't try to assign non-existent centroids
        await self.cancel_active_centroid_assignment_job(rubric_id)

        # Delete each centroid using ORM to trigger cascade deletion
        centroids = await self.get_centroids(rubric_id)
        for centroid in centroids:
            await self.session.delete(centroid)

        logger.info(f"Cleared {len(centroids)} centroids for rubric {rubric_id}")

    async def start_or_get_centroid_assignment_job(self, ctx: ViewContext, rubric_id: str):
        """Start a job to assign centroids to judge results."""

        # Is there already a job for this rubric?
        result = await self.session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.CENTROID_ASSIGNMENT_JOB.value)
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
                type=WorkerFunction.CENTROID_ASSIGNMENT_JOB.value,
                job_json={"rubric_id": rubric_id},
            )
        )

        # Enqueue the job
        await enqueue_job(ctx, job_id)

        return job_id

    async def assign_centroids(
        self,
        sqla_rubric: SQLARubric,
    ):
        sqla_centroids = await self.get_centroids(sqla_rubric.id)
        if len(sqla_centroids) == 0:
            logger.info(f"No centroids found for rubric {sqla_rubric.id}")
            return

        # Get (judge_result_id, centroid_id) pairs that already have assignments
        result = await self.session.execute(
            select(SQLAJudgeResultCentroid.judge_result_id, SQLAJudgeResultCentroid.centroid_id)
            .join(SQLAJudgeResult, SQLAJudgeResultCentroid.judge_result_id == SQLAJudgeResult.id)
            .join(SQLARubricCentroid, SQLAJudgeResultCentroid.centroid_id == SQLARubricCentroid.id)
            .where(
                SQLAJudgeResult.rubric_id == sqla_rubric.id,
                SQLARubricCentroid.rubric_id == sqla_rubric.id,
            )
        )
        assigned_pairs = set(cast(list[tuple[str, str]], result.all()))

        # Get all non-null judge results for this rubric
        judge_results = await self.get_rubric_results(sqla_rubric.id)
        judge_results = [jr for jr in judge_results if jr.value is not None]
        if not judge_results:
            logger.info(f"No judge results with values found for rubric {sqla_rubric.id}")
            return

        # Construct inputs to the clustering function, filtering out assigned pairs
        pairs_to_assign = [
            (jr.id, jr.value, sc.centroid)
            for jr in judge_results
            for sc in sqla_centroids
            if (jr.id, sc.id) not in assigned_pairs and jr.value is not None
        ]
        if len(pairs_to_assign) == 0:
            logger.info(f"No pairs to assign, already found {len(assigned_pairs)}")
            return

        logger.info(
            f"Assigning {len(pairs_to_assign)} pairs out of {len(judge_results) * len(sqla_centroids)} total"
        )
        result_ids_to_assign, results_to_assign, centroids_to_assign = cast(
            tuple[list[str], list[str], list[str]], zip(*pairs_to_assign)
        )

        # We need to map the centroid to the id for the assignment
        centroid_to_id = {
            sqla_centroid.centroid: sqla_centroid.id for sqla_centroid in sqla_centroids
        }

        async with BatchedWriter(self.session_cm_factory) as writer:

            async def record_assignment(batch_index: int, assignment: tuple[bool, str] | None):
                if assignment is None:
                    return

                judge_result_cluster = SQLAJudgeResultCentroid(
                    id=str(uuid4()),
                    judge_result_id=result_ids_to_assign[batch_index],
                    centroid_id=centroid_to_id[centroids_to_assign[batch_index]],
                    decision=assignment[0],
                    reason=assignment[1],
                )
                await writer.add_all([judge_result_cluster])

            await assign_with_backend(
                DEFAULT_ASSIGNER,
                results_to_assign,
                centroids_to_assign,
                assignment_callback=record_assignment,
            )

    async def get_centroid_assignments(self, rubric_id: str) -> dict[str, list[str]]:
        """Get centroid assignments for a rubric.

        Returns a dictionary mapping centroid ID to a list of judge result IDs
        that are assigned to that centroid (where decision=True).
        """
        # Get all centroids for this rubric
        centroids_result = await self.session.execute(
            select(SQLARubricCentroid).where(SQLARubricCentroid.rubric_id == rubric_id)
        )
        centroids = centroids_result.scalars().all()

        # Get all assignments for these centroids where decision=True
        assignments_result = await self.session.execute(
            select(SQLAJudgeResultCentroid).where(
                SQLAJudgeResultCentroid.centroid_id.in_([c.id for c in centroids]),
                SQLAJudgeResultCentroid.decision,
            )
        )
        assignments = assignments_result.scalars().all()

        # Build the result dictionary
        result: dict[str, list[str]] = {}
        for centroid in centroids:
            result[centroid.id] = []

        for assignment in assignments:
            result[assignment.centroid_id].append(assignment.judge_result_id)

        return result

    @staticmethod
    async def _get_active_centroid_assignment_job(
        session: AsyncSession, rubric_id: str
    ) -> SQLAJob | None:
        """Has weird type signature because of the polling loop"""
        result = await session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.CENTROID_ASSIGNMENT_JOB.value)
            .where(SQLAJob.job_json["rubric_id"].astext == rubric_id)
            .where((SQLAJob.status == JobStatus.PENDING) | (SQLAJob.status == JobStatus.RUNNING))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def poll_for_centroid_assignments(self, rubric_id: str):
        """While there is a running job for this rubric, poll."""

        async def _get_job():
            """Requires a new session; otherwise, the poller will never see the updates to SQLAJob."""
            async with self.session_cm_factory() as session:
                return await self._get_active_centroid_assignment_job(session, rubric_id)

        while (job := await _get_job()) is not None:
            results = await self.get_centroid_assignments(rubric_id)
            yield job.id, results
            await anyio.sleep(1)

        # Final yield, just in case the above was never run (do-while)
        results = await self.get_centroid_assignments(rubric_id)
        yield None, results

    async def cancel_active_centroid_assignment_job(self, rubric_id: str):
        """Cancel all running and pending centroid assignment jobs."""

        job = await self._get_active_centroid_assignment_job(self.session, rubric_id)
        if job:
            await self.job_svc.cancel_job(job.id)
