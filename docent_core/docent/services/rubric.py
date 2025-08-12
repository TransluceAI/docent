import asyncio
import random
from typing import AsyncContextManager, Callable, Sequence, cast
from uuid import uuid4

import anyio
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent_core._ai_tools.clustering.cluster_assigner import DEFAULT_ASSIGNER, assign_with_backend
from docent_core._ai_tools.clustering.cluster_generator import ClusterFeedback, propose_clusters
from docent_core._ai_tools.rubric.rubric import (
    JudgeResult,
    ResultType,
    Rubric,
    evaluate_rubric,
    evaluate_rubric_near_misses,
)
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
from docent_core.docent.services.job import JobService

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
        self.job_svc = JobService(session, session_cm_factory)

    ###############
    # Rubric CRUD #
    ###############

    async def create_rubric(self, collection_id: str, rubric: Rubric) -> str:
        """Add a rubric to the database and return the rubric ID.
        Will throw an error if the rubric already exists, or if the version is not 1.
        """

        if rubric.version != 1:
            raise ValueError(
                "Rubric version must be 1. "
                "If you want to add a new version to an existing rubric, use update_rubric instead."
            )

        sqla_rubric = SQLARubric.from_pydantic(rubric, collection_id)
        self.session.add(sqla_rubric)
        return sqla_rubric.id

    async def get_latest_rubric_version(self, rubric_id: str) -> int | None:
        """Get the latest version number for a rubric."""
        result = await self.session.execute(
            select(SQLARubric.version)
            .where(SQLARubric.id == rubric_id)
            .order_by(SQLARubric.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def add_rubric_version(self, rubric_id: str, rubric: Rubric) -> int:
        # Check that the version int is correct; raise if not
        latest_version = await self.get_latest_rubric_version(rubric_id)
        if latest_version is None:
            raise ValueError(f"Rubric {rubric_id} not found")
        if rubric.version != latest_version + 1:
            raise ValueError(
                f"Rubric version {rubric.version} is not the next version after {latest_version}"
            )

        # Get the collection_id from the existing rubric
        # TODO(mengk, caden): this is not that clean
        collection_result = await self.session.execute(
            select(SQLARubric.collection_id).where(SQLARubric.id == rubric_id).limit(1)
        )
        collection_id = collection_result.scalar_one()

        # Add the new version
        self.session.add(SQLARubric.from_pydantic(rubric, collection_id))
        return rubric.version

    async def get_all_rubrics(self, collection_id: str, latest_only: bool = True) -> list[Rubric]:
        """Get all rubrics for a collection. If latest_only is True, only return the latest version of each rubric."""
        if latest_only:
            # Join to a subquery of max version per rubric id within the collection
            max_versions_subq = (
                select(
                    SQLARubric.id.label("rid"),
                    func.max(SQLARubric.version).label("max_version"),
                )
                .where(SQLARubric.collection_id == collection_id)
                .group_by(SQLARubric.id)
                .subquery()
            )

            result = await self.session.execute(
                select(SQLARubric)
                .join(
                    max_versions_subq,
                    (SQLARubric.id == max_versions_subq.c.rid)
                    & (SQLARubric.version == max_versions_subq.c.max_version),
                )
                .where(SQLARubric.collection_id == collection_id)
            )
        else:
            # Get all versions of all rubrics
            result = await self.session.execute(
                select(SQLARubric).where(SQLARubric.collection_id == collection_id)
            )

        return [sqla_rubric.to_pydantic() for sqla_rubric in result.scalars().all()]

    async def delete_rubric(self, rubric_id: str):
        """Delete all versions of a rubric."""

        # First cancel any jobs involving this rubric
        await self.cancel_active_rubric_eval_job(rubric_id)
        await self.cancel_active_centroid_assignment_job(rubric_id)

        all_rubrics = await self.get_all_rubric_versions(rubric_id)
        for rubric in all_rubrics:
            await self.session.delete(rubric)

    async def delete_rubric_versions_after(self, rubric_id: str, after_version: int) -> int:
        """Delete all versions of a rubric after a specific version (non-inclusive).
        Returns the number of versions deleted.
        """

        # Get all versions after the specified version
        result = await self.session.execute(
            select(SQLARubric)
            .where(SQLARubric.id == rubric_id)
            .where(SQLARubric.version > after_version)
        )
        rubrics_to_delete = result.scalars().all()

        count = len(rubrics_to_delete)
        for rubric in rubrics_to_delete:
            await self.session.delete(rubric)

        return count

    ###############
    # Rubric jobs #
    ###############

    async def start_or_get_eval_rubric_job(
        self,
        ctx: ViewContext,
        rubric_id: str,
        max_results: int | None = None,
    ):
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
                job_json={
                    "rubric_id": rubric_id,
                    "max_results": max_results,
                },
            )
        )

        # Enqueue the job
        await enqueue_job(ctx, job_id)

        return job_id

    async def get_rubric(self, rubric_id: str, version: int | None) -> SQLARubric | None:
        """Get a rubric from the database.
        Gets the latest version if no version is specified.
        """
        if version is not None:
            # Get specific version
            result = await self.session.execute(
                select(SQLARubric).where(SQLARubric.id == rubric_id, SQLARubric.version == version)
            )
        else:
            # Get latest version
            result = await self.session.execute(
                select(SQLARubric)
                .where(SQLARubric.id == rubric_id)
                .order_by(SQLARubric.version.desc())
                .limit(1)
            )
        return result.scalar_one_or_none()

    async def get_all_rubric_versions(self, rubric_id: str) -> Sequence[SQLARubric]:
        """Get all versions of a rubric."""
        result = await self.session.execute(
            select(SQLARubric).where(SQLARubric.id == rubric_id).order_by(SQLARubric.version.asc())
        )
        return result.scalars().all()

    async def run_rubric_job(self, ctx: ViewContext, job: SQLAJob):
        """Run a rubric job. Should only be called by the worker."""

        # Get the rubric
        rubric_id = job.job_json["rubric_id"]
        rubric = await self.get_rubric(rubric_id, version=None)
        if rubric is None:
            raise ValueError(f"Rubric {rubric_id} not found")

        max_results = job.job_json.get("max_results", None)

        if max_results is not None:
            existing_results = await self.session.execute(
                select(func.count())
                .select_from(SQLAJudgeResult)
                .where(
                    SQLAJudgeResult.rubric_id == rubric_id,
                    SQLAJudgeResult.rubric_version == rubric.version,
                    SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
                    SQLAJudgeResult.value.isnot(None),
                )
            )
            num_existing_results = existing_results.scalar_one()
            if num_existing_results >= max_results:
                logger.info(
                    f"Skipping rubric evaluation because {num_existing_results} results already exist"
                )
                return
            max_results -= num_existing_results

        # Filter out agent runs with existing judge results
        result = await self.session.execute(
            select(SQLAAgentRun.id).where(
                SQLAAgentRun.collection_id == ctx.collection_id,
                ~exists().where(
                    SQLAJudgeResult.agent_run_id == SQLAAgentRun.id,
                    SQLAJudgeResult.rubric_id == rubric_id,
                    SQLAJudgeResult.rubric_version == rubric.version,
                    SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
                ),
            )
        )
        agent_run_ids = cast(list[str], result.scalars().all())
        random.shuffle(agent_run_ids)
        if len(agent_run_ids) == 0:
            logger.info("Skipping rubric evaluation because no agent runs are missing results")
            return

        logger.info(f"Evaluating rubrics for {len(agent_run_ids)} agent runs missing results")
        agent_runs = await self.service.get_agent_runs(ctx, agent_run_ids=agent_run_ids)

        num_results = 0
        rubric_results: list[list[str] | None] = [None] * len(agent_runs)

        async with BatchedWriter(self.session_cm_factory) as writer:
            # Use taskgroup for cancellation instead of events
            async with anyio.create_task_group() as tg:
                cancel_scope = tg.cancel_scope

                async def _callback(batch_index: int, judge_results: list[JudgeResult] | None):
                    if judge_results is None:
                        return

                    nonlocal num_results
                    num_results += sum(1 for j in judge_results if j.value is not None)

                    await writer.add_all(
                        [
                            SQLAJudgeResult.from_pydantic(judge_result)
                            for judge_result in judge_results
                        ]
                    )
                    rubric_results[batch_index] = [
                        j.value for j in judge_results if j.value is not None
                    ]
                    if (
                        max_results is not None
                        and num_results >= max_results
                        and not cancel_scope.cancel_called
                    ):
                        cancel_scope.cancel()

                # Run the search, saving data to the database as we go
                try:
                    await evaluate_rubric(
                        agent_runs,
                        rubric.to_pydantic(),
                        model_options=(
                            PROVIDER_PREFERENCES.execute_search
                            if max_results is not None
                            else PROVIDER_PREFERENCES.execute_full_search
                        ),
                        callback=_callback,
                    )
                except anyio.get_cancelled_exc_class():
                    logger.info(f"Rubric evaluation cancelled after reaching {num_results} results")

            # TODO(vincent): for now we assume refinement <-> has max results, full eval <-> no max results
            if max_results is None:
                return

            num_new_results = 0
            rubric_indices = [i for i, result in enumerate(rubric_results) if result is not None]

            # TODO(vincent): optimize this later, don't need to wait on first run to finish before starting second run

            async with anyio.create_task_group() as tg:
                cancel_scope = tg.cancel_scope

                async def _new_callback(batch_index: int, judge_results: list[JudgeResult] | None):
                    if judge_results is None:
                        return

                    nonlocal num_new_results
                    num_new_results += sum(1 for j in judge_results if j.value is not None)

                    if (
                        num_new_results >= job.job_json.get("max_results", 0)
                        and not cancel_scope.cancel_called
                    ):
                        cancel_scope.cancel()

                    # Use the session_cm_factory to get a session that commits immediately
                    await writer.add_all(
                        [
                            SQLAJudgeResult.from_pydantic(judge_result)
                            for judge_result in judge_results
                        ]
                    )

                try:
                    await evaluate_rubric_near_misses(
                        [agent_runs[i] for i in rubric_indices],
                        rubric.to_pydantic(),
                        [cast(list[str], rubric_results[i]) for i in rubric_indices],
                        model_options=PROVIDER_PREFERENCES.execute_search,
                        callback=_new_callback,
                    )
                except anyio.get_cancelled_exc_class():
                    logger.info(
                        f"Near misses evaluation cancelled after reaching {num_new_results} new results"
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

    async def get_rubric_results(
        self, rubric_id: str, version: int | None = None
    ) -> list[JudgeResult]:
        """Get the results of a rubric."""
        if version is None:
            # Get the latest version first
            latest_rubric = await self.get_rubric(rubric_id, version=None)
            if latest_rubric is None:
                return []
            version = latest_rubric.version

        result = await self.session.execute(
            select(SQLAJudgeResult).where(
                SQLAJudgeResult.rubric_id == rubric_id, SQLAJudgeResult.rubric_version == version
            )
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

    # async def clear_rubric_results(self, rubric_id: str):
    #     """Clear all results for a rubric."""
    #     # First cancel any jobs involving this rubric
    #     await self.cancel_active_rubric_eval_job(rubric_id)

    #     result = await self.session.execute(
    #         select(SQLAJudgeResult).where(SQLAJudgeResult.rubric_id == rubric_id)
    #     )
    #     results = result.scalars().all()
    #     for result in results:
    #         await self.session.delete(result)

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

        # Get all non-null judge results for this rubric
        judge_results = await self.get_rubric_results(rubric.id, sqla_rubric.version)
        judge_results = [jr for jr in judge_results if jr.value is not None]
        if not judge_results:
            logger.info(f"No judge results with values found for rubric {rubric.id}")
            return []
        # Separate the values because clustering just takes the values
        judge_result_types = set(jr.result_type for jr in judge_results)

        # TODO(vincent): figure out how to give type-specific feedback. broken rn

        # If we need to regenerate, save centroids and then delete from db
        cur_sqla_centroids = await self.get_centroids(sqla_rubric.id, sqla_rubric.version)
        centroid_result_types = set(c.result_type for c in cur_sqla_centroids)

        if judge_result_types != centroid_result_types or feedback is not None:
            await self.clear_centroids(sqla_rubric.id, sqla_rubric.version)
            await self.session.flush()

        async def _cluster_for_type(result_type: ResultType) -> list[SQLARubricCentroid]:
            if feedback is None and any(c.result_type == result_type for c in cur_sqla_centroids):
                logger.info(
                    f"Skipping centroid generation for rubric {sqla_rubric.id} because it already has {len(cur_sqla_centroids)} centroids"
                )
                return [c for c in cur_sqla_centroids if c.result_type == result_type]

            prev_centroid_strs = [
                c.centroid for c in cur_sqla_centroids if c.result_type == result_type
            ]

            # Propose centroids
            guidance = f"These are results for the rubric: {rubric.text}"
            centroids: list[str] = await propose_clusters(
                [str(j.value) for j in judge_results if j.result_type == result_type],
                extra_instructions_list=[guidance],
                feedback_list=(
                    [
                        ClusterFeedback(
                            clusters=prev_centroid_strs,
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
                    rubric_version=sqla_rubric.version,
                    centroid=centroid,
                    result_type=result_type,
                )
                for centroid in centroids
            ]
            # Use a separate session that self-commits, so results are immediately available
            async with self.session_cm_factory() as session:
                session.add_all(sqla_centroids)
            return sqla_centroids

        centroids = await asyncio.gather(*(_cluster_for_type(rt) for rt in judge_result_types))
        return [c for sqla_centroid in centroids for c in sqla_centroid]

    async def get_centroids(self, rubric_id: str, rubric_version: int | None):
        """Get existing clusters for a rubric."""

        # If latest version, figure it out
        if rubric_version is None:
            latest_version = await self.get_latest_rubric_version(rubric_id)
            if latest_version is None:
                return list[SQLARubricCentroid]()
            rubric_version = latest_version

        result = await self.session.execute(
            select(SQLARubricCentroid).where(
                SQLARubricCentroid.rubric_id == rubric_id,
                SQLARubricCentroid.rubric_version == rubric_version,
            )
        )
        return result.scalars().all()

    async def clear_centroids(self, rubric_id: str, rubric_version: int):
        """Clear all centroids for a rubric along with their assignments (cascaded)."""

        # First cancel the job so it doesn't try to assign non-existent centroids
        await self.cancel_active_centroid_assignment_job(rubric_id)

        # Delete each centroid using ORM to trigger cascade deletion
        centroids = await self.get_centroids(rubric_id, rubric_version)
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
        sqla_centroids = await self.get_centroids(sqla_rubric.id, sqla_rubric.version)
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
                SQLARubricCentroid.rubric_version == sqla_rubric.version,
            )
        )
        assigned_pairs = set(cast(list[tuple[str, str]], result.all()))

        # Get all non-null judge results for this rubric
        judge_results = await self.get_rubric_results(sqla_rubric.id, sqla_rubric.version)
        judge_results = [jr for jr in judge_results if jr.value is not None]
        if not judge_results:
            logger.info(f"No judge results with values found for rubric {sqla_rubric.id}")
            return

        # Construct inputs to the clustering function, filtering out assigned pairs
        pairs_to_assign = [
            (jr.id, jr.value, sc.centroid)
            for jr in judge_results
            for sc in sqla_centroids
            if (jr.id, sc.id) not in assigned_pairs
            and jr.value is not None
            and sc.result_type == jr.result_type
        ]
        result_types = [
            jr.result_type
            for jr in judge_results
            for sc in sqla_centroids
            if (jr.id, sc.id) not in assigned_pairs
            and jr.value is not None
            and sc.result_type == jr.result_type
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
                    result_type=result_types[batch_index],
                )
                await writer.add_all([judge_result_cluster])

            await assign_with_backend(
                DEFAULT_ASSIGNER,
                results_to_assign,
                centroids_to_assign,
                assignment_callback=record_assignment,
            )

    async def get_centroid_assignments(
        self, rubric_id: str, rubric_version: int | None = None
    ) -> dict[str, list[str]]:
        """Get centroid assignments for a rubric.

        Returns a dictionary mapping centroid ID to a list of judge result IDs
        that are assigned to that centroid (where decision=True).
        """

        if rubric_version is None:
            # Get the latest version first
            latest_rubric = await self.get_rubric(rubric_id, version=None)
            if latest_rubric is None:
                return {}
            rubric_version = latest_rubric.version

        # Get all centroids for this rubric
        centroids_result = await self.session.execute(
            select(SQLARubricCentroid).where(
                SQLARubricCentroid.rubric_id == rubric_id,
                SQLARubricCentroid.rubric_version == rubric_version,
            )
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

    async def get_active_assignment_job_for_rubric(self, rubric_id: str) -> SQLAJob | None:
        """Get the active centroid assignment job for a rubric if it exists."""
        return await self._get_active_centroid_assignment_job(self.session, rubric_id)

    async def cancel_active_centroid_assignment_job(self, rubric_id: str):
        """Cancel all running and pending centroid assignment jobs."""

        job = await self._get_active_centroid_assignment_job(self.session, rubric_id)
        if job:
            await self.job_svc.cancel_job(job.id)
