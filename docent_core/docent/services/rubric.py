import asyncio
import json
from typing import Any, AsyncContextManager, Callable, Sequence, cast
from uuid import uuid4

import anyio
import jsonschema
from sqlalchemy import and_, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent.data_models.judge import JudgeRunLabel
from docent.judges import JudgeResult, ResultType, Rubric
from docent.judges.runner import run_rubric
from docent_core._db_service.batched_writer import BatchedWriter
from docent_core._server._broker.redis_client import enqueue_job
from docent_core._worker.constants import WorkerFunction
from docent_core.docent.ai_tools.clustering.cluster_assigner import (
    assign,
)
from docent_core.docent.ai_tools.clustering.cluster_generator import (
    ClusterFeedback,
    propose_clusters,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.rubric import (
    SQLAJudgeResult,
    SQLAJudgeResultCentroid,
    SQLAJudgeRunLabel,
    SQLARubric,
    SQLARubricCentroid,
)
from docent_core.docent.db.schemas.tables import (
    JobStatus,
    SQLAAgentRun,
    SQLAJob,
)
from docent_core.docent.services.job import JobService
from docent_core.docent.services.llms import LLMService
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


class RubricService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        service: MonoService,
        llm_svc: LLMService,
    ):
        """The `session_cm_factory` creates new sessions that commit writes immediately.
        This is helpful if you don't want to wait for results to be written."""

        self.session = session
        self.session_cm_factory = session_cm_factory
        self.service = service
        self.llm_svc = llm_svc
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

    async def get_rubric_version_stats(self, rubric_id: str) -> tuple[SQLARubric, int] | None:
        """Return the latest rubric record and the number of judge results for it."""

        latest_rubric = await self.get_rubric(rubric_id, version=None)
        if latest_rubric is None:
            return None

        result = await self.session.execute(
            select(func.count(SQLAJudgeResult.id)).where(
                SQLAJudgeResult.rubric_id == rubric_id,
                SQLAJudgeResult.rubric_version == latest_rubric.version,
            )
        )
        judge_result_count = result.scalar_one() or 0
        return latest_rubric, judge_result_count

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
        await self.cancel_active_clustering_job(rubric_id)

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
        existing_job = await self._get_active_rubric_job(self.session, rubric_id)
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

        # Exception to rule of not committing inside the service:
        #   commit so that the enqueued job is visible to the worker
        await self.session.commit()
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

        if ctx.user is None:
            raise ValueError("User is required to run a rubric job")

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
                )
            )
            num_existing_results = existing_results.scalar_one()
            if num_existing_results >= max_results:
                logger.info(
                    f"Skipping rubric evaluation because {num_existing_results} results already exist"
                )
                return
            max_results -= num_existing_results

        # Get runs sorting by those with labels first
        query = (
            select(SQLAAgentRun.id)
            # Join to labels
            .outerjoin(
                SQLAJudgeRunLabel,
                and_(
                    SQLAJudgeRunLabel.agent_run_id == SQLAAgentRun.id,
                    SQLAJudgeRunLabel.rubric_id == rubric_id,
                ),
            )
            # Runs without existing results
            .where(
                SQLAAgentRun.collection_id == ctx.collection_id,
                ~exists().where(
                    SQLAJudgeResult.agent_run_id == SQLAAgentRun.id,
                    SQLAJudgeResult.rubric_id == rubric_id,
                    SQLAJudgeResult.rubric_version == rubric.version,
                    SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
                ),
            )
            .group_by(SQLAAgentRun.id)
            .order_by(func.count(SQLAJudgeRunLabel.id).desc())
        )

        query = query.where(ctx.get_base_where_clause(SQLAAgentRun))

        result = await self.session.execute(query)
        agent_run_ids = cast(list[str], result.scalars().all())

        # Update the job with the actual total number of agent runs to process
        await self.service.set_job_json(
            job.id, job.job_json | {"total_agent_runs": len(agent_run_ids)}
        )

        # Preserve ordering: labeled runs first
        if len(agent_run_ids) == 0:
            logger.info("Skipping rubric evaluation because no agent runs are missing results")
            return

        logger.info(f"Evaluating rubrics for {len(agent_run_ids)} agent runs missing results")
        agent_runs = await self.service.get_agent_runs(ctx, agent_run_ids=agent_run_ids)
        # Preserve the label-first ordering from agent_run_ids
        order_index = {rid: i for i, rid in enumerate(agent_run_ids)}
        agent_runs.sort(key=lambda ar: order_index.get(ar.id, len(order_index)))

        num_results = 0

        async with BatchedWriter(self.session_cm_factory) as writer:
            # Use taskgroup for cancellation instead of events
            async with anyio.create_task_group() as tg:

                async def _callback(batch_index: int, judge_results: list[JudgeResult] | None):
                    if judge_results is None:
                        return

                    nonlocal num_results
                    num_results += len(judge_results)

                    await writer.add_all(
                        [
                            SQLAJudgeResult.from_pydantic(judge_result)
                            for judge_result in judge_results
                        ]
                    )

                    if (
                        max_results is not None
                        and num_results >= max_results
                        and not tg.cancel_scope.cancel_called
                    ):
                        tg.cancel_scope.cancel()

                # Run the search, saving data to the database as we go
                try:
                    await run_rubric(
                        agent_runs,
                        rubric.to_pydantic(),
                        llm_svc=self.llm_svc,
                        callback=_callback,
                    )
                except anyio.get_cancelled_exc_class():
                    logger.info(f"Rubric evaluation cancelled after reaching {num_results} results")

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

        search_query = select(SQLAJudgeResult).where(
            SQLAJudgeResult.rubric_id == rubric_id,
            SQLAJudgeResult.rubric_version == version,
        )

        result = await self.session.execute(search_query)
        sqla_results = result.scalars().all()
        return [sqla_result.to_pydantic() for sqla_result in sqla_results]

    async def get_rubric_result_by_id(self, judge_result_id: str) -> JudgeResult | None:
        result = await self.session.execute(
            select(SQLAJudgeResult).where(SQLAJudgeResult.id == judge_result_id)
        )
        sqla_result = result.scalar_one_or_none()
        if sqla_result is None:
            return None
        return sqla_result.to_pydantic()

    async def get_rubric_result_by_agent_run(
        self, agent_run_id: str, rubric_id: str, rubric_version: int
    ) -> JudgeResult | None:
        """Get the DIRECT_RESULT judge result for an agent run/rubric/version.

        Returns None if a DIRECT_RESULT does not exist.
        """
        direct_res = await self.session.execute(
            select(SQLAJudgeResult)
            .where(
                SQLAJudgeResult.agent_run_id == agent_run_id,
                SQLAJudgeResult.rubric_id == rubric_id,
                SQLAJudgeResult.rubric_version == rubric_version,
                SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
            )
            .limit(1)
        )
        sqla_direct = direct_res.scalar_one_or_none()
        if sqla_direct is None:
            return None
        return sqla_direct.to_pydantic()

    async def cancel_active_rubric_eval_job(self, rubric_id: str):
        job = await self.get_active_job_for_rubric(rubric_id)
        if job:
            await self.job_svc.cancel_job(job.id)

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

    async def start_or_get_clustering_job(
        self,
        ctx: ViewContext,
        sq_rubric: SQLARubric,
        clustering_feedback: str | None = None,
        recluster: bool = False,
    ):
        """Start a job to cluster rubric results."""

        # Is there already a job for this rubric?
        existing_job = await self.get_active_clustering_job(sq_rubric.id)
        if existing_job:
            return existing_job.id

        # There is no running job, create a new one
        job_id = str(uuid4())
        self.session.add(
            SQLAJob(
                id=job_id,
                type=WorkerFunction.CLUSTERING_JOB.value,
                job_json={
                    "rubric_id": sq_rubric.id,
                    "clustering_feedback": clustering_feedback,
                    "recluster": recluster,
                },
            )
        )

        # Enqueue the job
        await enqueue_job(ctx, job_id)

        return job_id

    async def cancel_active_clustering_job(self, rubric_id: str):
        job = await self.get_active_clustering_job(rubric_id)
        if job:
            await self.job_svc.cancel_job(job.id)

    async def get_active_clustering_job(self, rubric_id: str) -> SQLAJob | None:
        result = await self.session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.CLUSTERING_JOB.value)
            .where(SQLAJob.job_json["rubric_id"].astext == rubric_id)
            .where((SQLAJob.status == JobStatus.PENDING) | (SQLAJob.status == JobStatus.RUNNING))
            .order_by(SQLAJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def run_clustering_job(self, ctx: ViewContext, job: SQLAJob):
        """Run a clustering job. Should only be called by the worker."""
        rubric_id = job.job_json["rubric_id"]
        sq_rubric = await self.get_rubric(rubric_id, version=None)
        if sq_rubric is None:
            raise ValueError(f"Rubric {rubric_id} not found")
        centroids_feedback = job.job_json.get("clustering_feedback", None)
        recluster = bool(job.job_json.get("recluster", False))

        if ctx.user is None:
            raise ValueError("User is required to propose centroids")

        # Propose centroids
        await self.propose_centroids(sq_rubric, ctx.user.id, recluster, centroids_feedback)
        # Assign centroids
        await self.assign_centroids(sq_rubric, ctx.user.id)

    async def propose_centroids(
        self,
        sq_rubric: SQLARubric,
        user_id: str,
        recluster: bool,
        feedback: str | None = None,
    ) -> Sequence[SQLARubricCentroid]:
        """Cluster judge results and store cluster information with the judge results.
        If recluster, current centroids will be overwritten."""
        rubric = sq_rubric.to_pydantic()

        # Get all non-null judge results for this rubric
        judge_results = await self.get_rubric_results(rubric.id, sq_rubric.version)
        if not judge_results:
            logger.info(f"No judge results with values found for rubric {rubric.id}")
            return []
        # Separate the values because clustering just takes the values
        judge_result_types = set(jr.result_type for jr in judge_results)

        # TODO(vincent): figure out how to give type-specific feedback. broken rn

        # If we need to regenerate, save centroids and then delete from db
        cur_sqla_centroids = await self.get_centroids(sq_rubric.id, sq_rubric.version)
        centroid_result_types = set(c.result_type for c in cur_sqla_centroids)

        if judge_result_types != centroid_result_types or feedback is not None or recluster:
            await self.clear_centroids(sq_rubric.id, sq_rubric.version)
            await self.session.flush()

        async def _cluster_for_type(result_type: ResultType) -> list[SQLARubricCentroid]:
            if (
                feedback is None
                and not recluster
                and any(c.result_type == result_type for c in cur_sqla_centroids)
            ):
                logger.info(
                    f"Skipping centroid generation for rubric {sq_rubric.id} because it already has {len(cur_sqla_centroids)} centroids"
                )
                return [c for c in cur_sqla_centroids if c.result_type == result_type]

            prev_centroid_strs = [
                c.centroid for c in cur_sqla_centroids if c.result_type == result_type
            ]

            # Propose centroids
            guidance = f"These are results for the rubric: {rubric.rubric_text}"
            centroids: list[str] = await propose_clusters(
                [json.dumps(j.output) for j in judge_results if j.result_type == result_type],
                self.llm_svc,
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
                    collection_id=sq_rubric.collection_id,
                    rubric_id=rubric.id,
                    rubric_version=sq_rubric.version,
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

        # Delete each centroid using ORM to trigger cascade deletion
        centroids = await self.get_centroids(rubric_id, rubric_version)
        for centroid in centroids:
            await self.session.delete(centroid)

        logger.info(f"Cleared {len(centroids)} centroids for rubric {rubric_id}")

    async def assign_centroids(
        self,
        sqla_rubric: SQLARubric,
        user_id: str,
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
        if not judge_results:
            logger.info(f"No judge results with values found for rubric {sqla_rubric.id}")
            return

        # Construct inputs to the clustering function, filtering out assigned pairs
        pairs_to_assign = [
            (jr.id, jr.output, sc.centroid)
            for jr in judge_results
            for sc in sqla_centroids
            if (jr.id, sc.id) not in assigned_pairs and sc.result_type == jr.result_type
        ]
        result_types = [
            jr.result_type
            for jr in judge_results
            for sc in sqla_centroids
            if (jr.id, sc.id) not in assigned_pairs and sc.result_type == jr.result_type
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

            await assign(
                results_to_assign,
                centroids_to_assign,
                self.llm_svc,
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

    ######################
    # Result Labels CRUD #
    ######################

    async def create_judge_run_labels(
        self, collection_id: str, labels: list[JudgeRunLabel]
    ) -> None:
        """Add one or more run labels to judge results."""

        if not labels:
            return

        # Get the single rubric_id that all labels share
        rubric_ids = {label.rubric_id for label in labels}
        if len(rubric_ids) != 1:
            raise ValueError("All labels in a batch must target the same rubric")
        rubric_id = labels[0].rubric_id

        # Get *latest* rubric for its output schema
        sqla_rubric = await self.get_rubric(rubric_id, version=None)
        if sqla_rubric is None:
            raise ValueError(f"Rubric {rubric_id} not found")
        if sqla_rubric.collection_id != collection_id:
            raise ValueError(f"Rubric {rubric_id} does not belong to collection {collection_id}")

        # Validate labels against rubric output schema (raises ValueError if invalid)
        for label in labels:
            jsonschema.validate(label.label, sqla_rubric.output_schema)

        # Add labels to db
        self.session.add_all([SQLAJudgeRunLabel.from_pydantic(label) for label in labels])

    async def update_judge_run_label(self, agent_run_id: str, label: dict[str, Any]) -> bool:
        """Update a run label for a judge result."""
        # Check that there's an existing label
        result = await self.session.execute(
            select(SQLAJudgeRunLabel).where(SQLAJudgeRunLabel.agent_run_id == agent_run_id)
        )
        existing_label = result.scalar_one_or_none()
        if existing_label is None:
            raise ValueError(f"Label for agent run {agent_run_id} not found")

        # Get *latest* rubric for its output schema
        sqla_rubric = await self.get_rubric(existing_label.rubric_id, version=None)
        if sqla_rubric is None:
            raise ValueError(f"Rubric {existing_label.rubric_id} not found")

        # Validate label against rubric output schema (raises ValueError if invalid)
        jsonschema.validate(label, sqla_rubric.output_schema)

        # Update label in db
        existing_label.label = label
        return True

    async def get_judge_run_labels(self, rubric_id: str) -> list[JudgeRunLabel]:
        """Get all result labels for a rubric.

        Returns a list of labels with agent_run_id.
        """
        result = await self.session.execute(
            select(SQLAJudgeRunLabel)
            .where(SQLAJudgeRunLabel.rubric_id == rubric_id)
            .order_by(SQLAJudgeRunLabel.id)
        )
        rows = result.scalars().all()
        return [row.to_pydantic() for row in rows]

    async def has_judge_run_labels(self, rubric_id: str) -> bool:
        """Check if a rubric has any run labels."""
        result = await self.session.execute(
            select(exists().where(SQLAJudgeRunLabel.rubric_id == rubric_id))
        )
        return result.scalar_one()

    async def delete_all_judge_run_labels(self, rubric_id: str):
        """Delete all run labels for a rubric."""
        await self.session.execute(
            delete(SQLAJudgeRunLabel).where(SQLAJudgeRunLabel.rubric_id == rubric_id)
        )

    async def get_judge_run_label(self, agent_run_id: str) -> JudgeRunLabel | None:
        """Get a run label for a judge result."""
        result = await self.session.execute(
            select(SQLAJudgeRunLabel).where(SQLAJudgeRunLabel.agent_run_id == agent_run_id)
        )

        result_label = result.scalar_one_or_none()
        if result_label is None:
            return None
        return result_label.to_pydantic()

    async def get_judge_run_labels_and_results(
        self, rubric_id: str
    ) -> list[tuple[JudgeRunLabel, JudgeResult]]:
        """Get all run labels and results for a rubric."""
        # Use the latest rubric version to avoid mixing versions in context
        latest_version = await self.get_latest_rubric_version(rubric_id)
        if latest_version is None:
            return []

        result = await self.session.execute(
            select(SQLAJudgeRunLabel, SQLAJudgeResult)
            .join(SQLAJudgeResult, SQLAJudgeRunLabel.agent_run_id == SQLAJudgeResult.agent_run_id)
            .where(
                SQLAJudgeRunLabel.rubric_id == rubric_id,
                SQLAJudgeResult.rubric_id == rubric_id,
                SQLAJudgeResult.rubric_version == latest_version,
                SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
            )
        )
        rows = result.all()
        return [(row[0].to_pydantic(), row[1].to_pydantic()) for row in rows]

    async def delete_judge_run_label(self, agent_run_id: str):
        """Delete a judge run label from a judge result."""
        # We only need agent_run_id since there's one label per agent run
        result = await self.session.execute(
            select(SQLAJudgeRunLabel).where(SQLAJudgeRunLabel.agent_run_id == agent_run_id)
        )
        label_to_delete = result.scalar_one_or_none()
        if label_to_delete:
            await self.session.delete(label_to_delete)

    async def copy_rubric_to_collection(
        self, source_rubric_id: str, target_collection_id: str
    ) -> str:
        """Copy a rubric to another collection with a new ID and version 1."""
        source_sqla_rubric = await self.get_rubric(source_rubric_id, version=None)
        if source_sqla_rubric is None:
            raise ValueError(f"Source rubric {source_rubric_id} not found")

        source_rubric = source_sqla_rubric.to_pydantic()
        new_rubric = source_rubric.model_copy(update={"id": str(uuid4()), "version": 1})

        return await self.create_rubric(target_collection_id, new_rubric)

    async def estimate_rubric_cost(
        self,
        rubric_id: str,
        version: int | None,
        agent_run_ids: list[str],
        ctx: ViewContext,
    ) -> tuple[float, dict[str, Any]]:
        """Estimate the cost in cents to evaluate a rubric on a set of agent runs.

        Args:
            ctx: View context for accessing agent runs
            rubric_id: The rubric ID
            version: The rubric version (None for latest)
            agent_run_ids: List of agent run IDs to evaluate

        Returns:
            A tuple of (total_cents, details_dict) where details_dict contains:
                - model_name: The judge model name
                - num_runs: Number of agent runs
                - avg_tokens_per_run: Average tokens per run
                - total_input_tokens: Total estimated input tokens
                - total_cost_cents: Total estimated cost in cents
        """
        from docent._llm_util.model_registry import estimate_cost_cents
        from docent._log_util.logger import get_logger
        from docent.data_models._tiktoken_util import get_token_count

        logger = get_logger(__name__)

        # Get the rubric
        sqla_rubric = await self.get_rubric(rubric_id, version)
        if sqla_rubric is None:
            raise ValueError(f"Rubric {rubric_id} (version={version}) not found")

        if not agent_run_ids:
            return 0.0, {
                "model_name": "unknown",
                "num_runs": 0,
                "avg_tokens_per_run": 0,
                "total_input_tokens": 0,
                "total_cost_cents": 0.0,
            }

        # Extract model name from judge_model
        judge_model = sqla_rubric.judge_model
        model_name = judge_model.get("model_name", "unknown")

        # Sample a few agent runs to estimate average token count
        # We'll sample up to 10 runs to get a reasonable estimate
        sample_size = min(10, len(agent_run_ids))
        sample_ids = agent_run_ids[:sample_size]

        # Get sample agent runs using the service (which properly loads transcripts)
        sample_agent_runs = await self.service.get_agent_runs(
            ctx, agent_run_ids=sample_ids, apply_base_where_clause=False
        )

        if not sample_agent_runs:
            logger.warning("No agent runs found for cost estimation")
            return 0.0, {
                "model_name": model_name,
                "num_runs": len(agent_run_ids),
                "avg_tokens_per_run": 0,
                "total_input_tokens": 0,
                "total_cost_cents": 0.0,
            }

        # Estimate tokens for sample runs using the canonical prompt construction
        rubric_pydantic = sqla_rubric.to_pydantic()
        total_sample_tokens = 0
        for agent_run in sample_agent_runs:
            # Use the canonical prompt construction function
            prompt = rubric_pydantic.materialize_system_prompt(agent_run)
            tokens = get_token_count(prompt)
            total_sample_tokens += tokens

        avg_tokens_per_run = int(total_sample_tokens / len(sample_agent_runs))

        # Estimate total tokens for all runs
        total_input_tokens = avg_tokens_per_run * len(agent_run_ids)

        avg_output_tokens = 300  # A very rough guess
        total_output_tokens = avg_output_tokens * len(agent_run_ids)

        # Calculate costs
        input_cost_cents = estimate_cost_cents(model_name, total_input_tokens, "input")
        output_cost_cents = estimate_cost_cents(model_name, total_output_tokens, "output")
        total_cost_cents = input_cost_cents + output_cost_cents

        return total_cost_cents, {
            "model_name": model_name,
            "num_runs": len(agent_run_ids),
            "avg_tokens_per_run": avg_tokens_per_run,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost_cents": total_cost_cents,
        }
