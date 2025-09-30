from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, AsyncIterator, Optional, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from docent._log_util import get_logger
from docent_core._server._broker.redis_client import (
    STATE_KEY_FORMAT,
    STREAM_KEY_FORMAT,
    enqueue_job,
    get_redis_client,
)
from docent_core._worker.constants import WorkerFunction
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import JobStatus, SQLAJob
from docent_core.docent.services.monoservice import MonoService as DocentMonoService
from docent_core.investigator.db.contexts import WorkspaceContext
from docent_core.investigator.db.schemas.experiment import (
    SQLASimpleRolloutExperimentConfig,
    SQLASimpleRolloutExperimentResult,
)
from docent_core.investigator.services.monoservice import InvestigatorMonoService
from docent_core.investigator.tools.simple_rollout.types import (
    SimpleRolloutExperimentConfig,
    SimpleRolloutExperimentResult,
    SimpleRolloutExperimentSummary,
)

logger = get_logger(__name__)


class SimpleRolloutService:
    """Service for managing simple rollout experiments."""

    def __init__(self, investigator_svc: InvestigatorMonoService):
        self.investigator_svc = investigator_svc
        self.db = investigator_svc.db

    async def build_experiment_config(
        self, experiment_config_id: str
    ) -> Optional[SimpleRolloutExperimentConfig]:
        """
        Load an experiment config from the database and convert to Pydantic model.

        This method loads the SQLAlchemy experiment config with all its related
        objects and converts them to the Pydantic SimpleRolloutExperimentConfig.
        """
        async with self.db.session() as session:
            # Load the experiment config with all related objects
            result = await session.execute(
                select(SQLASimpleRolloutExperimentConfig)
                .where(SQLASimpleRolloutExperimentConfig.id == experiment_config_id)
                .where(SQLASimpleRolloutExperimentConfig.deleted_at.is_(None))
                .options(
                    selectinload(SQLASimpleRolloutExperimentConfig.judge_config_obj),
                    selectinload(SQLASimpleRolloutExperimentConfig.openai_compatible_backend_objs),
                    selectinload(SQLASimpleRolloutExperimentConfig.base_context_obj),
                )
            )
            sqla_config = result.scalar_one_or_none()

            if sqla_config is None:
                logger.warning(f"Experiment config {experiment_config_id} not found")
                return None

            # Convert to Pydantic model using the from_sql method
            return SimpleRolloutExperimentConfig.from_sql(sqla_config)

    async def start_or_get_experiment_job(
        self, ctx: WorkspaceContext, experiment_config_id: str
    ) -> str:
        """Start a new simple rollout experiment job or return existing active job."""
        async with self.db.session() as session:
            async with self.investigator_svc.advisory_lock(
                experiment_config_id, f"start_simple_rollout_{experiment_config_id}"
            ):
                # Check if there's already an active job for this experiment
                active_job = await self._get_active_experiment_job(session, experiment_config_id)
                if active_job:
                    logger.info(
                        f"Found existing active job {active_job.id} for experiment {experiment_config_id}"
                    )
                    return active_job.id

                # Create new job
                job_id = str(uuid4())
                session.add(
                    SQLAJob(
                        id=job_id,
                        type=WorkerFunction.SIMPLE_ROLLOUT_EXPERIMENT_JOB.value,
                        status=JobStatus.PENDING,
                        job_json={"experiment_config_id": experiment_config_id},
                    )
                )

                # Commit so the job is visible to the worker
                await session.commit()

                # Enqueue the job to Redis
                await enqueue_job(ctx, job_id)

                logger.info(
                    f"Created and enqueued new job {job_id} for simple rollout experiment {experiment_config_id}"
                )
                return job_id

    async def _get_active_experiment_job(
        self, session: AsyncSession, experiment_config_id: str
    ) -> Optional[SQLAJob]:
        """Get active job for an experiment if it exists (with session)."""
        result = await session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.SIMPLE_ROLLOUT_EXPERIMENT_JOB.value)
            .where(SQLAJob.job_json["experiment_config_id"].as_string() == experiment_config_id)
            .where(SQLAJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
        )
        return result.scalar_one_or_none()

    async def get_active_experiment_job(self, experiment_config_id: str) -> Optional[SQLAJob]:
        """Get active job for an experiment if it exists (public API)."""
        async with self.db.session() as session:
            return await self._get_active_experiment_job(session, experiment_config_id)

    async def get_job(self, job_id: str) -> Optional[SQLAJob]:
        """Get a job by ID."""
        async with self.db.session() as session:
            result = await session.execute(select(SQLAJob).where(SQLAJob.id == job_id))
            return result.scalar_one_or_none()

    async def get_job_state_from_redis(
        self, job_id: str
    ) -> Optional[SimpleRolloutExperimentSummary]:
        """Get the current state of a simple rollout experiment from Redis."""
        REDIS = await get_redis_client()
        state_key = STATE_KEY_FORMAT.format(job_id=job_id)
        raw_state = await REDIS.get(state_key)  # type: ignore

        if raw_state is not None:
            return SimpleRolloutExperimentSummary.model_validate_json(raw_state)

        return None

    async def listen_for_job_state(
        self, job_id: str
    ) -> AsyncIterator[SimpleRolloutExperimentSummary]:
        """Stream experiment state updates for a job."""
        REDIS = await get_redis_client()
        stream_key = STREAM_KEY_FORMAT.format(job_id=job_id)

        logger.info(f"Starting to listen for job {job_id} on stream {stream_key}")

        # Push initial state if available
        state = await self.get_job_state_from_redis(job_id)
        if state is not None:
            logger.debug(f"Yielding initial state for job {job_id}")
            yield state

        # Listen for updates
        last_id = "0-0"
        done = False

        while not done:
            try:
                # Block until a notifier event arrives (30 second timeout)
                results = await REDIS.xread(  # type: ignore
                    {stream_key: last_id}, block=30000, count=1
                )

                if not results:
                    # Timeout - check if job is still running
                    job = await self.get_job(job_id)
                    if job and job.status in [
                        JobStatus.COMPLETED,
                        JobStatus.CANCELED,
                    ]:
                        logger.info(f"Job {job_id} is no longer active: {job.status}")
                        done = True
                    continue

                for _stream, entries in results:
                    if len(entries) == 0:
                        continue

                    _entry_id, _data = entries[-1]
                    last_id = _entry_id

                    # Parse the event data
                    data = cast(dict[str, str], _data)
                    event = data.get("event")

                    logger.debug(f"Job {job_id} received event: {event}")

                    if event not in {"state_updated", "finished", "error"}:
                        logger.warning(f"Job {job_id} received unknown event {event}")
                        continue

                    # Get the updated state
                    state = await self.get_job_state_from_redis(job_id)
                    if state is not None:
                        yield state

                    # Check if we're done
                    if event in {"finished", "error"}:
                        done = True
                        logger.info(f"Job {job_id} completed with event: {event}")
                        if event == "error":
                            error_msg = data.get("error", "Unknown error")
                            logger.error(f"Job {job_id} failed: {error_msg}")

            except Exception as e:
                logger.error(f"Error listening to job {job_id}: {e}")
                # Check job status before giving up
                job = await self.get_job(job_id)
                if job and job.status in [
                    JobStatus.COMPLETED,
                    JobStatus.CANCELED,
                ]:
                    done = True
                else:
                    # Re-raise the error if job is still active
                    raise

    async def get_experiment_result(
        self,
        experiment_config_id: str,
        include_agent_runs: bool = False,
        user: Optional[User] = None,
    ) -> Optional[SimpleRolloutExperimentResult]:
        """Get the stored result for a simple rollout experiment."""
        async with self.db.session() as session:
            # Get the result from database with config loaded

            result = await session.execute(
                select(SQLASimpleRolloutExperimentResult)
                .options(
                    selectinload(SQLASimpleRolloutExperimentResult.experiment_config).selectinload(
                        SQLASimpleRolloutExperimentConfig.base_context_obj
                    ),
                    selectinload(SQLASimpleRolloutExperimentResult.experiment_config).selectinload(
                        SQLASimpleRolloutExperimentConfig.openai_compatible_backend_objs
                    ),
                    selectinload(SQLASimpleRolloutExperimentResult.experiment_config).selectinload(
                        SQLASimpleRolloutExperimentConfig.judge_config_obj
                    ),
                )
                .where(
                    SQLASimpleRolloutExperimentResult.experiment_config_id == experiment_config_id
                )
            )
            sqla_result = result.scalar_one_or_none()

            if sqla_result is None:
                return None

            # Build result object from SQL
            experiment_result = SimpleRolloutExperimentResult.from_sql(sqla_result)

            # Optionally include full agent runs
            if include_agent_runs and sqla_result.collection_id and user:
                docent_svc = await DocentMonoService.init()
                ctx = await docent_svc.get_default_view_ctx(sqla_result.collection_id, user)

                # Get all agent runs from the collection
                agent_runs = await docent_svc.get_agent_runs(ctx)

                # Convert to dict format that SimpleRolloutExperimentResult expects
                experiment_result.agent_runs = {run.id: run for run in agent_runs}

            return experiment_result

    async def get_experiment_agent_run(
        self, experiment_config_id: str, agent_run_id: str, user: User
    ) -> Any:
        """Get a specific agent run from a simple rollout experiment."""
        # Get the experiment result to find the collection
        result = await self.get_experiment_result(experiment_config_id, False, user)

        if not result or not result.docent_collection_id:
            return None

        # Get the specific agent run from the collection
        docent_svc = await DocentMonoService.init()
        ctx = await docent_svc.get_default_view_ctx(result.docent_collection_id, user)
        agent_run = await docent_svc.get_agent_run(ctx, agent_run_id, apply_base_where_clause=True)

        return agent_run

    async def store_experiment_result(
        self,
        experiment_config_id: str,
        result: SimpleRolloutExperimentResult,
        user: User,
    ) -> str:
        """
        Store a completed experiment result in the database.
        Creates a docent collection for agent runs and stores the result.

        Returns the result ID.
        """
        # Initialize docent service
        docent_svc = await DocentMonoService.init()

        # Create a collection for the agent runs
        collection_name = (
            f"Simple Rollout {experiment_config_id[:8]} - {datetime.now(UTC).isoformat()}"
        )
        collection_description = f"Agent runs for simple rollout experiment {experiment_config_id}"

        collection_id = await docent_svc.create_collection(
            user=user,
            name=collection_name,
            description=collection_description,
        )

        # Store agent runs in the collection only if experiment completed successfully
        # For experiment-level errors, we save the summary but not the agent runs
        if result.agent_runs and result.experiment_status.status != "error":
            # Get or create a default view for this user and collection
            ctx = await docent_svc.get_default_view_ctx(collection_id, user)
            await docent_svc.add_agent_runs(ctx, list(result.agent_runs.values()))

        # Set the collection_id in the result
        result.docent_collection_id = collection_id

        # Store the experiment result in database
        result_id = str(uuid4())
        async with self.db.session() as session:
            # Check if a result already exists for this config
            existing = await session.execute(
                select(SQLASimpleRolloutExperimentResult).where(
                    SQLASimpleRolloutExperimentResult.experiment_config_id == experiment_config_id
                )
            )
            existing_result = existing.scalar_one_or_none()

            if existing_result:
                # Update existing result
                existing_result.collection_id = collection_id
                existing_result.status = result.experiment_status.status
                existing_result.progress = result.experiment_status.progress
                existing_result.agent_run_metadata = (
                    {k: v.model_dump() for k, v in result.agent_run_metadata.items()}
                    if result.agent_run_metadata
                    else None
                )
                existing_result.base_policy_config = (
                    result.base_policy_config.model_dump() if result.base_policy_config else None
                )
                existing_result.completed_at = datetime.now(UTC).replace(tzinfo=None)
                result_id = existing_result.id
            else:
                # Create new result
                session.add(
                    SQLASimpleRolloutExperimentResult(
                        id=result_id,
                        experiment_config_id=experiment_config_id,
                        collection_id=collection_id,
                        status=result.experiment_status.status,
                        progress=result.experiment_status.progress,
                        agent_run_metadata=(
                            {k: v.model_dump() for k, v in result.agent_run_metadata.items()}
                            if result.agent_run_metadata
                            else None
                        ),
                        base_policy_config=(
                            result.base_policy_config.model_dump()
                            if result.base_policy_config
                            else None
                        ),
                        completed_at=(
                            datetime.now(UTC).replace(tzinfo=None)
                            if result.experiment_status.status == "completed"
                            else None
                        ),
                    )
                )

            await session.commit()

        logger.info(
            f"Stored experiment result {result_id} with collection {collection_id} "
            f"containing {len(result.agent_runs) if result.agent_runs else 0} agent runs"
        )

        return result_id
