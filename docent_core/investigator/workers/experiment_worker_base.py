"""Shared base functionality for experiment workers."""

import asyncio
import json
import time
import traceback
from typing import Any, AsyncIterator, Callable, Protocol, Set, TypeVar

from fastapi.encoders import jsonable_encoder

from docent._log_util import get_logger
from docent.data_models import AgentRun
from docent_core._server._broker.redis_client import (
    STATE_KEY_FORMAT,
    STREAM_KEY_FORMAT,
    SUBSCRIPTIONS_KEY_FORMAT,
    get_redis_client,
)
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.investigator.db.contexts import WorkspaceContext
from docent_core.investigator.tools.common.types import ExperimentStatus

logger = get_logger(__name__)


class ExperimentResultSummaryProtocol(Protocol):
    """Protocol for experiment result summaries."""

    subscribed_agent_runs: dict[str, AgentRun] | None


# Protocol for experiment results that support signatures
class ExperimentResultProtocol(Protocol):
    """Protocol for experiment results."""

    experiment_status: ExperimentStatus
    agent_runs: dict[str, AgentRun] | None

    def compute_signature(self, subscribed_run_ids: set[str]) -> bytes:
        """Compute signature for change detection."""
        ...

    def summary(self) -> ExperimentResultSummaryProtocol:
        """Get a lightweight summary for streaming."""
        ...


# Protocol for experiments that can run
class ExperimentProtocol(Protocol):
    """Protocol for experiments."""

    def run(self) -> AsyncIterator[ExperimentResultProtocol]:
        """Run the experiment, yielding results.

        Note: This should be implemented as an async generator:
        async def run(self) -> AsyncIterator[ExperimentResultProtocol]:
            yield result

        Protocols don't support async def, so we use the return type annotation.
        """
        ...


# Protocol for experiment services
class ExperimentServiceProtocol(Protocol):
    """Protocol for experiment services."""

    async def build_experiment_config(self, experiment_config_id: str) -> Any:
        """Load experiment configuration."""
        ...

    async def store_experiment_result(
        self, experiment_config_id: str, result: Any, user: Any
    ) -> str:
        """Store experiment result."""
        ...


TConfig = TypeVar("TConfig")
TExperiment = TypeVar("TExperiment", bound=ExperimentProtocol)


async def run_experiment_job(
    ctx: WorkspaceContext,
    job: SQLAJob,
    service: ExperimentServiceProtocol,
    experiment_factory: Callable[[TConfig], TExperiment],
    summary_type: type,
    job_name: str,
) -> None:
    """
    Generic experiment worker that handles state streaming and result storage.

    Args:
        ctx: Workspace context
        job: Job definition
        service: Service for loading config and storing results
        experiment_factory: Function to create experiment from config
        summary_type: Type for deserializing summaries
        job_name: Name for logging (e.g. "counterfactual", "simple_rollout")
    """
    # Get experiment config from job metadata
    experiment_config_id = job.job_json["experiment_config_id"]

    logger.info(f"Starting {job_name} experiment job for config {experiment_config_id}")

    # Load the experiment configuration
    config = await service.build_experiment_config(experiment_config_id)

    if config is None:
        raise ValueError(f"Experiment config {experiment_config_id} not found")

    # Set up Redis streaming
    REDIS = await get_redis_client()
    stream_key = STREAM_KEY_FORMAT.format(job_id=job.id)
    state_key = STATE_KEY_FORMAT.format(job_id=job.id)

    # State publishing configuration
    last_state_signature: bytes | None = None
    PUBLISH_INTERVAL_S: float = 0.25

    # 250ms cache for subscribed run IDs to avoid frequent SMEMBERS
    cached_subscribed_run_ids: Set[str] = set()
    last_subscribed_fetch_monotonic: float = 0.0
    SUBSCRIBED_REFRESH_INTERVAL_S: float = 0.25

    async def _get_subscribed_runs() -> Set[str]:
        """Get the set of agent run IDs that are subscribed for streaming."""
        nonlocal last_subscribed_fetch_monotonic, cached_subscribed_run_ids
        try:
            now = time.monotonic()
            if now - last_subscribed_fetch_monotonic < SUBSCRIBED_REFRESH_INTERVAL_S:
                return cached_subscribed_run_ids

            subscribed = await REDIS.smembers(SUBSCRIPTIONS_KEY_FORMAT.format(job_id=job.id))  # type: ignore
            cached_subscribed_run_ids = {
                s.decode() if isinstance(s, bytes) else s for s in subscribed  # type: ignore
            }
            last_subscribed_fetch_monotonic = now
            return cached_subscribed_run_ids
        except Exception:
            logger.error(f"Failed to get subscribed runs: {traceback.format_exc()}")
            return set()

    async def _publish_state(result: ExperimentResultProtocol, *, force: bool = False):
        """Publish the current experiment state to Redis if it has changed.

        Uses signature-based deduplication to avoid publishing unchanged states.

        Args:
            result: The experiment result to publish
            force: If True, publish even if signature hasn't changed (for final states)
        """
        nonlocal last_state_signature
        try:
            # Get subscribed runs and compute signature
            subscribed_run_ids = await _get_subscribed_runs()
            signature = result.compute_signature(subscribed_run_ids)

            # Skip if unchanged from last published state (unless forced)
            if not force and last_state_signature is not None and signature == last_state_signature:
                return

            # Build payload
            summary = result.summary()

            # Add full agent run data for subscribed runs
            if subscribed_run_ids and result.agent_runs:
                summary.subscribed_agent_runs = {}
                for run_id in sorted(subscribed_run_ids):
                    if run_id in result.agent_runs:
                        summary.subscribed_agent_runs[run_id] = result.agent_runs[run_id]

            payload = json.dumps(jsonable_encoder(summary), sort_keys=True, separators=(",", ":"))
            payload_size_bytes = len(payload.encode("utf-8"))

            if payload_size_bytes > 5 * 1024 * 1024:
                logger.warning(
                    f"Payload size for job {job.id} is {payload_size_bytes / 1024 / 1024:.2f} MB (> 5MB)"
                )

            # Publish to Redis
            await REDIS.set(state_key, payload, ex=1800)  # type: ignore
            await REDIS.xadd(stream_key, {"event": "state_updated"}, maxlen=200)  # type: ignore

            # Update signature tracking
            last_state_signature = signature

        except Exception:
            logger.error(f"Failed to publish state for job {job.id}: {traceback.format_exc()}")

    # Run the experiment
    experiment = experiment_factory(config)
    final_result: ExperimentResultProtocol | None = None
    experiment_done = False
    publisher_task = None

    async def _background_publisher():
        """Background task to ensure periodic state updates even during slow experiment operations."""
        nonlocal final_result
        while not experiment_done:
            await asyncio.sleep(PUBLISH_INTERVAL_S)
            if final_result is not None:
                await _publish_state(final_result)

    try:
        logger.info(f"Starting experiment run for job {job.id}")

        # Start background publisher to handle subscription changes during slow periods
        publisher_task = asyncio.create_task(_background_publisher())

        # Stream results as they come in
        last_update_time = time.monotonic()
        async for result in experiment.run():
            # Update the latest result; background task will publish periodically
            final_result = result

            # Log time since last update
            now = time.monotonic()
            time_since_last_update_ms = (now - last_update_time) * 1000

            if time_since_last_update_ms > 1000:
                logger.info(f"Experiment update received after {time_since_last_update_ms:.0f}ms")

            last_update_time = now

        logger.info(f"Experiment rollouts complete for job {job.id}; storing results")
        experiment_done = True
        await publisher_task  # Wait for background task to finish

        # Store the final result in the database with agent runs in a collection
        if final_result:
            try:
                assert ctx.user is not None, "User is required to store experiment results"

                # Mark experiment as completed before storing so DB captures completion
                if final_result.experiment_status.status != "error":
                    final_result.experiment_status.status = "completed"

                result_id = await service.store_experiment_result(
                    experiment_config_id=experiment_config_id,
                    result=final_result,
                    user=ctx.user,
                )
                logger.info(
                    f"Stored experiment result {result_id} for config {experiment_config_id}"
                )
                # Stream the final state with collection_id one last time
                await _publish_state(final_result, force=True)
            except Exception as e:
                logger.error(f"Failed to store experiment result: {e}\n{traceback.format_exc()}")
                # Don't fail the whole job if storage fails

        # Mark as finished only after attempting to store and publish final state
        await REDIS.xadd(stream_key, {"event": "finished"}, maxlen=200)  # type: ignore

    except Exception as e:
        # Uncaught exception in experiment; mark as errored and store result
        logger.error(f"Experiment failed for job {job.id}: {e}\n{traceback.format_exc()}")

        if final_result and final_result.experiment_status.status == "error":
            try:
                assert ctx.user is not None, "User is required to store experiment results"
                result_id = await service.store_experiment_result(
                    experiment_config_id=experiment_config_id,
                    result=final_result,
                    user=ctx.user,
                )
                logger.info(
                    f"Stored errored experiment result {result_id} for config {experiment_config_id}"
                )
                await _publish_state(final_result, force=True)
            except Exception as storage_e:
                logger.error(f"Failed to store errored experiment result: {storage_e}")
        else:
            try:
                # TODO this is a bit hacky...

                state_key = STATE_KEY_FORMAT.format(job_id=job.id)
                raw = await REDIS.get(state_key)  # type: ignore
                if raw:
                    summary = summary_type.model_validate_json(raw)  # type: ignore
                    if summary.agent_run_metadata:  # type: ignore
                        for m in summary.agent_run_metadata.values():  # type: ignore
                            if getattr(m, "state", "in_progress") == "in_progress":  # type: ignore
                                m.state = "errored"  # type: ignore
                    payload = json.dumps(jsonable_encoder(summary))
                    await REDIS.set(state_key, payload, ex=600)  # type: ignore
            except Exception:
                logger.error("Failed to mark runs errored on failure; continuing")

        await REDIS.xadd(stream_key, {"event": "error", "error": "Experiment failed"}, maxlen=200)  # type: ignore
        raise

    finally:
        # Stop background publisher task
        experiment_done = True
        if publisher_task is not None:
            try:
                await asyncio.wait_for(publisher_task, timeout=1.0)
            except asyncio.TimeoutError:
                publisher_task.cancel()
            except Exception:
                pass

        # Cleanup - set shorter TTL on completion and remove subscriptions
        await REDIS.expire(stream_key, 600)  # type: ignore
        await REDIS.expire(state_key, 600)  # type: ignore
        await REDIS.delete(SUBSCRIPTIONS_KEY_FORMAT.format(job_id=job.id))  # type: ignore
        logger.info(f"Cleaned up Redis keys for job {job.id}")
