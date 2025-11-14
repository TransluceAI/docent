import asyncio
import json
import traceback
from typing import Any, AsyncContextManager, Callable, Sequence, cast
from uuid import uuid4

import anyio
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.judge import Label
from docent.judges import JudgeResult, ResultType, Rubric
from docent.judges.runner import run_rubric
from docent_core._db_service.batched_writer import BatchedWriter
from docent_core._server._broker.redis_client import (
    STREAM_KEY_FORMAT,
    enqueue_job,
    get_redis_client,
)
from docent_core._worker.constants import WorkerFunction
from docent_core.docent.ai_tools.clustering.cluster_assigner import (
    assign,
)
from docent_core.docent.ai_tools.clustering.cluster_generator import (
    ClusterFeedback,
    propose_clusters,
)
from docent_core.docent.ai_tools.rubric.reflect import (
    JudgeReflection,
    run_reflection,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.label import SQLALabel
from docent_core.docent.db.schemas.rubric import (
    SQLAJudgeReflection,
    SQLAJudgeResult,
    SQLAJudgeResultCentroid,
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
        max_agent_runs: int | None = None,
        n_rollouts_per_input: int = 1,
        label_set_id: str | None = None,
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
                    "max_agent_runs": max_agent_runs,
                    "n_rollouts_per_input": n_rollouts_per_input,
                    "label_set_id": label_set_id,
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
        """Run a rubric job. Should only be called by the worker.

        Logic:
        1. Select first N agent runs (by labeled_first, then UUID) where N = max_agent_runs
        2. From those N, identify which need more rollouts
        3. Generate only the needed rollouts for incomplete runs
        """

        if ctx.user is None:
            raise ValueError("User is required to run a rubric job")

        rubric_id = job.job_json["rubric_id"]
        rubric = await self.get_rubric(rubric_id, version=None)
        if rubric is None:
            raise ValueError(f"Rubric {rubric_id} not found")

        max_agent_runs = job.job_json.get("max_agent_runs", None)
        n_rollouts_per_input = job.job_json.get("n_rollouts_per_input", 1)
        label_set_id = job.job_json.get("label_set_id", None)

        # Subquery to count existing results per agent run for this rubric/version
        result_counts_subquery = (
            select(
                SQLAJudgeResult.agent_run_id,
                func.count(SQLAJudgeResult.id).label("result_count"),
            )
            .where(
                SQLAJudgeResult.rubric_id == rubric_id,
                SQLAJudgeResult.rubric_version == rubric.version,
                SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
            )
            .group_by(SQLAJudgeResult.agent_run_id)
            .subquery()
        )

        # Select agent runs with their result counts, ordered by: labeled first, then UUID
        query = (
            select(SQLAAgentRun.id, result_counts_subquery.c.result_count)
            .where(ctx.get_base_where_clause(SQLAAgentRun))
            .outerjoin(
                result_counts_subquery,
                SQLAAgentRun.id == result_counts_subquery.c.agent_run_id,
            )
        )

        # Join to labels to prioritize labeled runs
        if label_set_id:
            query = query.outerjoin(
                SQLALabel,
                (SQLALabel.agent_run_id == SQLAAgentRun.id)
                & (SQLALabel.label_set_id == label_set_id),
            )
        else:
            query = query.outerjoin(
                SQLALabel,
                SQLALabel.agent_run_id == SQLAAgentRun.id,
            )

        query = query.order_by(
            SQLALabel.id.is_(None).asc(),  # Labeled runs first
            SQLAAgentRun.id.asc(),  # Deterministic ordering
        )

        # Apply limit if max_agent_runs specified
        if max_agent_runs is not None:
            query = query.limit(max_agent_runs)

        result = await self.session.execute(query)
        rows = result.all()

        if len(rows) == 0:
            logger.info("Skipping rubric evaluation because no agent runs found in collection")
            return

        # Build mapping of agent_run_id -> existing result count
        # NOTE(mengk, cadentj): this is incorrect if you have multiple labels per agent run.
        #   but we have a schema constraint that prevents this.
        ar_ids_selected = [row[0] for row in rows]
        existing_counts = {row[0]: row[1] or 0 for row in rows}

        # Calculate rollouts needed per agent run (may be 0 for already-complete runs)
        rollouts_needed_per_run = [
            max(0, n_rollouts_per_input - existing_counts.get(ar_id, 0))
            for ar_id in ar_ids_selected
        ]
        total_rollouts_to_generate = sum(rollouts_needed_per_run)

        logger.info(
            f"Selected {len(ar_ids_selected)} agent runs; "
            f"{sum(1 for n in rollouts_needed_per_run if n > 0)} need additional rollouts "
            f"({total_rollouts_to_generate} total rollouts to generate)"
        )

        # Update job metadata for progress tracking
        await self.service.set_job_json(
            job.id,
            job.job_json
            | {
                "total_agent_runs": len(ar_ids_selected),
                "agent_run_ids_being_processed": ar_ids_selected,
            },
        )

        def _make_ar_resolver(agent_run_id: str):
            async def _resolver() -> AgentRun | None:
                """Resolves an agent run by grabbing it from the database.
                The AgentRun may not be found, in which case this returns None.
                """
                return await self.service.get_agent_run(ctx, agent_run_id)

            return _resolver

        ar_resolvers = [_make_ar_resolver(agent_run_id) for agent_run_id in ar_ids_selected]

        async with BatchedWriter(self.session_cm_factory) as writer:
            async with anyio.create_task_group() as tg:

                async def _callback(batch_index: int, judge_results: list[JudgeResult] | None):
                    if judge_results is None:
                        return

                    await writer.add_all(
                        [
                            SQLAJudgeResult.from_pydantic(judge_result)
                            for judge_result in judge_results
                        ]
                    )

                    # Spawn reflection task for this agent_run
                    # Pass new results directly; reflection will merge with existing DB results
                    # This handles race conditions where new results may not be committed yet
                    if judge_results:
                        tg.start_soon(
                            self._create_reflection_background,
                            judge_results,
                            rubric.to_pydantic(),
                            label_set_id,
                        )

                # Run the judge, saving data to the database as we go
                await run_rubric(
                    ar_resolvers,
                    rubric.to_pydantic(),
                    llm_svc=self.llm_svc,
                    callback=_callback,
                    n_rollouts_per_input=rollouts_needed_per_run,
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
            .where(SQLAJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.CANCELLING]))
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

    ####################
    # Judge Reflections #
    ####################

    async def _create_or_update_reflection(
        self,
        session: AsyncSession,
        judge_results: list[JudgeResult],
        rubric: Rubric,
        label_set_id: str | None = None,
    ) -> SQLAJudgeReflection | None:
        """Core logic for creating/updating reflections.

        Always replaces existing reflections for the same agent_run + rubric.

        Args:
            session: Database session to use
            judge_results: The judge results to reflect on (already loaded)
            rubric: The rubric
            label_set_id: Optional label set ID to filter labels by

        Returns:
            The created/updated reflection, or None if not enough results to reflect on
        """
        if not judge_results:
            return None

        agent_run_id = judge_results[0].agent_run_id
        rubric_id = judge_results[0].rubric_id
        rubric_version = judge_results[0].rubric_version

        # Get human label if exists for the specified label set
        human_label = None
        label_id = None
        if label_set_id:
            query = select(SQLALabel).where(
                SQLALabel.agent_run_id == agent_run_id,
                SQLALabel.label_set_id == label_set_id,
            )

            label_result = await session.execute(query)
            sqla_label = label_result.scalar_one_or_none()
            human_label = sqla_label.label_value if sqla_label else None
            label_id = sqla_label.id if sqla_label else None

        # Only create reflection if there are multiple results OR a label exists
        if len(judge_results) <= 1 and not human_label:
            return None

        # Extract rollouts
        rollouts = [jr.output for jr in judge_results]

        # Run the reflection
        reflection_output = await run_reflection(
            rubric=rubric, rollouts=rollouts, llm_svc=self.llm_svc, human_label=human_label
        )

        # Upsert reflection using unique constraint on (agent_run_id, rubric_id, rubric_version, label_id)
        result_ids = [jr.id for jr in judge_results]
        stmt = insert(SQLAJudgeReflection).values(
            id=str(uuid4()),
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=rubric_version,
            judge_result_ids=result_ids,
            label_id=label_id,
            reflection_output=reflection_output,
        )

        if label_id is not None:
            stmt = stmt.on_conflict_do_update(
                index_elements=["agent_run_id", "rubric_id", "rubric_version", "label_id"],
                index_where=(SQLAJudgeReflection.label_id.is_not(None)),
                set_={
                    "judge_result_ids": stmt.excluded.judge_result_ids,
                    "reflection_output": stmt.excluded.reflection_output,
                    "created_at": stmt.excluded.created_at,
                },
            )
        else:
            stmt = stmt.on_conflict_do_update(
                index_elements=["agent_run_id", "rubric_id", "rubric_version"],
                index_where=(SQLAJudgeReflection.label_id.is_(None)),
                set_={
                    "judge_result_ids": stmt.excluded.judge_result_ids,
                    "reflection_output": stmt.excluded.reflection_output,
                    "created_at": stmt.excluded.created_at,
                },
            )

        stmt = stmt.returning(SQLAJudgeReflection)
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _create_reflection_background(
        self,
        new_judge_results: list[JudgeResult],
        rubric: Rubric,
        label_set_id: str | None = None,
    ):
        """Background task to create a reflection for multi-rollout judge results.

        Merges newly generated results with existing DB results to handle cases where:
        - New results haven't been committed yet (BatchedWriter delay)
        - Evaluations are rerun with additional rollouts

        Args:
            new_judge_results: Newly generated judge results for a single agent_run
            rubric: The rubric
            label_set_id: Optional label set ID to filter labels by
        """
        if not new_judge_results:
            return

        agent_run_id = new_judge_results[0].agent_run_id
        rubric_id = new_judge_results[0].rubric_id
        rubric_version = new_judge_results[0].rubric_version

        try:
            async with self.session_cm_factory() as session:
                # Query ALL existing results from DB
                all_results_query = select(SQLAJudgeResult).where(
                    SQLAJudgeResult.agent_run_id == agent_run_id,
                    SQLAJudgeResult.rubric_id == rubric_id,
                    SQLAJudgeResult.rubric_version == rubric_version,
                )
                result = await session.execute(all_results_query)
                sqla_results = result.scalars().all()
                db_results = [r.to_pydantic() for r in sqla_results]

                # Merge new and DB results, deduplicating by ID
                # New results take precedence (in case of edge case updates)
                results_by_id = {r.id: r for r in db_results}
                for new_result in new_judge_results:
                    results_by_id[new_result.id] = new_result

                all_judge_results = list(results_by_id.values())

                sqla_reflection = await self._create_or_update_reflection(
                    session, all_judge_results, rubric, label_set_id=label_set_id
                )

                if sqla_reflection:
                    await session.commit()
                    logger.info(
                        f"Created reflection for agent_run {agent_run_id} "
                        f"with {len(all_judge_results)} total rollouts "
                        f"({len(new_judge_results)} new, {len(db_results)} from DB)"
                    )

        except Exception as e:
            logger.error(f"Failed to create reflection for agent_run {agent_run_id}: {e}")

    async def get_reflections_for_agent_runs(
        self,
        agent_run_ids: list[str],
        rubric_id: str,
        rubric_version: int,
        label_set_id: str | None = None,
    ) -> dict[str, JudgeReflection | None]:
        """Batch fetch reflections for multiple agent_runs.

        If label_set_id is provided, for each agent_run that has a label in that
        label set, returns the reflection associated with that label. Otherwise,
        returns the reflection with no label.

        Args:
            agent_run_ids: List of agent run IDs
            rubric_id: The rubric ID
            rubric_version: The rubric version
            label_set_id: Optional label set ID to check for labeled reflections

        Returns:
            Dict mapping agent_run_id to reflection (or None if not found)
        """
        if not agent_run_ids:
            return {}

        # Get the rubric for parsing citations
        sqla_rubric = await self.get_rubric(rubric_id, rubric_version)
        if sqla_rubric is None:
            return {agent_run_id: None for agent_run_id in agent_run_ids}

        # Map agent_run_id to label_id (if label_set_id is provided)
        agent_run_to_label_id: dict[str, str | None] = {
            agent_run_id: None for agent_run_id in agent_run_ids
        }

        if label_set_id is not None:
            labels_result = await self.session.execute(
                select(SQLALabel).where(
                    SQLALabel.agent_run_id.in_(agent_run_ids),
                    SQLALabel.label_set_id == label_set_id,
                )
            )
            sqla_labels = labels_result.scalars().all()
            for sqla_label in sqla_labels:
                agent_run_to_label_id[sqla_label.agent_run_id] = sqla_label.id

        # Fetch all reflections for these agent_runs in one query
        reflections_result = await self.session.execute(
            select(SQLAJudgeReflection).where(
                SQLAJudgeReflection.rubric_id == rubric_id,
                SQLAJudgeReflection.rubric_version == rubric_version,
                SQLAJudgeReflection.agent_run_id.in_(agent_run_ids),
            )
        )
        sqla_reflections_all = reflections_result.scalars().all()

        # Filter to match expected label_id for each agent_run
        sqla_reflections = [
            sqla_r
            for sqla_r in sqla_reflections_all
            if sqla_r.label_id == agent_run_to_label_id.get(sqla_r.agent_run_id)
        ]

        # Collect all judge result IDs we need to fetch
        all_judge_result_ids: set[str] = set()
        for sqla_reflection in sqla_reflections:
            if sqla_reflection.judge_result_ids:
                all_judge_result_ids.update(sqla_reflection.judge_result_ids)

        # Fetch all judge results in one query
        judge_results_map: dict[str, SQLAJudgeResult] = {}
        if all_judge_result_ids:
            results_result = await self.session.execute(
                select(SQLAJudgeResult).where(SQLAJudgeResult.id.in_(list(all_judge_result_ids)))
            )
            sqla_results = results_result.scalars().all()
            judge_results_map = {r.id: r for r in sqla_results}

        # Build the result map
        result_map: dict[str, JudgeReflection | None] = {}
        reflection_map = {sqla_r.agent_run_id: sqla_r for sqla_r in sqla_reflections}

        for agent_run_id in agent_run_ids:
            sqla_reflection = reflection_map.get(agent_run_id)
            if sqla_reflection is None or not sqla_reflection.judge_result_ids:
                result_map[agent_run_id] = None
                continue

            # Check if all judge results are present
            result_ids = sqla_reflection.judge_result_ids
            if not all(result_id in judge_results_map for result_id in result_ids):
                result_map[agent_run_id] = None
                continue

            reflection = JudgeReflection.from_raw_output(
                judge_result_ids=result_ids,
                raw_output=sqla_reflection.reflection_output,
            )
            result_map[agent_run_id] = reflection

        return result_map

    ####################
    # Reflection Jobs  #
    ####################

    async def start_or_get_reflection_job(
        self,
        ctx: ViewContext,
        agent_run_id: str,
        rubric_id: str,
        rubric_version: int,
        label_set_id: str | None = None,
        force_new: bool = False,
    ) -> str:
        """Start a job to compute reflection for an agent run's judge results.

        Args:
            ctx: View context
            agent_run_id: The agent run ID
            rubric_id: The rubric ID
            rubric_version: The rubric version
            label_set_id: Optional label set ID to filter labels by
            force_new: If True, always start a new job even if one is already running/pending
        """
        # Use a separate session that commits immediately so the job is in DB before worker picks it up
        async with self.session_cm_factory() as session:
            # Is there already a job for this agent_run + rubric?
            if not force_new:
                result = await session.execute(
                    select(SQLAJob)
                    .where(SQLAJob.type == WorkerFunction.REFLECTION_JOB.value)
                    .where(SQLAJob.job_json["agent_run_id"].astext == agent_run_id)
                    .where(SQLAJob.job_json["rubric_id"].astext == rubric_id)
                    .where(SQLAJob.job_json["rubric_version"].astext == str(rubric_version))
                    .where(
                        SQLAJob.status.in_(
                            [JobStatus.PENDING, JobStatus.RUNNING, JobStatus.CANCELLING]
                        )
                    )
                    .limit(1)
                )
                existing_job = result.scalar_one_or_none()
                if existing_job:
                    return existing_job.id

            # There is no running job, create a new one
            job_id = str(uuid4())
            session.add(
                SQLAJob(
                    id=job_id,
                    type=WorkerFunction.REFLECTION_JOB.value,
                    job_json={
                        "agent_run_id": agent_run_id,
                        "rubric_id": rubric_id,
                        "rubric_version": rubric_version,
                        "label_set_id": label_set_id,
                    },
                )
            )
            # Session commits when context exits

        # Job is now committed to DB, safe to enqueue
        await enqueue_job(ctx, job_id)

        return job_id

    async def wait_for_reflection_result(
        self,
        job_id: str,
        agent_run_id: str,
        rubric_id: str,
        rubric_version: int,
        label_set_id: str | None = None,
        timeout_seconds: int = 300,
    ) -> JudgeReflection | None:
        """Wait for reflection result to be computed via Redis stream.

        Blocks until the reflection is ready, then returns it.

        Args:
            job_id: The job ID to wait for
            agent_run_id: The agent run ID
            rubric_id: The rubric ID
            rubric_version: The rubric version
            timeout_seconds: Maximum time to wait (default 5 minutes)

        Returns:
            JudgeReflection when ready, or None if timeout/error

        Raises:
            TimeoutError: If reflection doesn't complete within timeout
        """
        REDIS = await get_redis_client()
        stream_key = STREAM_KEY_FORMAT.format(job_id=job_id)

        # Listen to stream for completion
        last_id = "0-0"
        start_time = asyncio.get_event_loop().time()

        while True:
            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"Reflection job {job_id} timed out after {timeout_seconds} seconds"
                )

            try:
                # Calculate remaining timeout
                remaining_timeout = int((timeout_seconds - elapsed) * 1000)  # milliseconds
                block_timeout = min(remaining_timeout, 30000)  # Max 30s per xread

                # Block until a notification arrives
                results = await REDIS.xread({stream_key: last_id}, block=block_timeout, count=1)  # type: ignore

                # Timed out on this read; loop again to check overall timeout
                if not results:
                    continue

                for _stream, entries in results:
                    if len(entries) == 0:
                        continue
                    _entry_id, _data = entries[-1]

                    # Advance cursor
                    last_id = _entry_id
                    data = cast(dict[str, str], _data)
                    logger.info(f"Reflection job {job_id} received event: {data}")

                    event = data.get("event")
                    if event not in {"state_updated", "finished"}:
                        logger.error(f"Reflection job {job_id} received unknown event: {event}")
                        continue

                    # Exit if finished
                    if event == "finished":
                        # Fetch final reflection from DB
                        results = await self.get_reflections_for_agent_runs(
                            [agent_run_id], rubric_id, rubric_version, label_set_id
                        )
                        return results.get(agent_run_id)

            except Exception as e:
                logger.error(
                    f"Error reading from Redis stream {stream_key}: {e}. Traceback:\n{traceback.format_exc()}"
                )
                return None

    async def run_reflection_job(self, ctx: ViewContext, job: SQLAJob):
        """Run a reflection job. Should only be called by the worker."""
        agent_run_id = job.job_json["agent_run_id"]
        rubric_id = job.job_json["rubric_id"]
        rubric_version = job.job_json["rubric_version"]
        label_set_id = job.job_json.get("label_set_id", None)

        # Get the rubric
        sqla_rubric = await self.get_rubric(rubric_id, rubric_version)
        if sqla_rubric is None:
            raise ValueError(f"Rubric {rubric_id} version {rubric_version} not found")

        # Query all judge results for this agent_run + rubric
        result = await self.session.execute(
            select(SQLAJudgeResult).where(
                SQLAJudgeResult.agent_run_id == agent_run_id,
                SQLAJudgeResult.rubric_id == rubric_id,
                SQLAJudgeResult.rubric_version == rubric_version,
                SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
            )
        )
        sqla_results = result.scalars().all()

        if len(sqla_results) == 0:
            logger.warning(f"Agent run {agent_run_id} has no results, skipping reflection")
            return

        # Convert to pydantic
        judge_results = [r.to_pydantic() for r in sqla_results]

        # Use common reflection logic
        sqla_reflection = await self._create_or_update_reflection(
            self.session, judge_results, sqla_rubric.to_pydantic(), label_set_id=label_set_id
        )

        if sqla_reflection:
            logger.info(
                f"Saved reflection for agent_run {agent_run_id} with {len(judge_results)} rollouts"
            )
        else:
            logger.info(
                f"Skipped reflection for agent_run {agent_run_id}: "
                f"only {len(judge_results)} result(s) and no human label"
            )

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
            .where(SQLAJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.CANCELLING]))
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

        # For clustering, only use the first result per agent_run_id
        # This ensures consistency with what's displayed in the UI
        first_results_map: dict[str, JudgeResult] = {}
        for jr in judge_results:
            if jr.agent_run_id not in first_results_map:
                first_results_map[jr.agent_run_id] = jr
        judge_results = list(first_results_map.values())

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

        # For clustering, only use the first result per agent_run_id
        # This ensures consistency with what's displayed in the UI
        first_results_map: dict[str, JudgeResult] = {}
        for jr in judge_results:
            if jr.agent_run_id not in first_results_map:
                first_results_map[jr.agent_run_id] = jr
        judge_results = list(first_results_map.values())

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

    #################
    # Label methods #
    #################

    async def get_judge_run_labels_and_results(
        self, rubric_id: str, label_set_id: str
    ) -> list[tuple[Label, JudgeResult]]:
        """Get all run labels and results for a rubric."""
        # Use the latest rubric version to avoid mixing versions in context
        latest_version = await self.get_latest_rubric_version(rubric_id)
        if latest_version is None:
            return []

        result = await self.session.execute(
            select(SQLALabel, SQLAJudgeResult)
            .join(SQLAJudgeResult, SQLALabel.agent_run_id == SQLAJudgeResult.agent_run_id)
            .where(
                SQLALabel.label_set_id == label_set_id,
                SQLAJudgeResult.rubric_id == rubric_id,
                SQLAJudgeResult.rubric_version == latest_version,
                SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
            )
        )
        rows = result.all()
        return [(row[0].to_pydantic(), row[1].to_pydantic()) for row in rows]
