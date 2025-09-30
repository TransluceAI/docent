"""Worker for running simple rollout experiments."""

import json
import time
import traceback
from typing import Any, Set, Tuple

from fastapi.encoders import jsonable_encoder

from docent._log_util import get_logger
from docent_core._server._broker.redis_client import (
    STATE_KEY_FORMAT,
    STREAM_KEY_FORMAT,
    get_redis_client,
)
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.investigator.db.contexts import WorkspaceContext
from docent_core.investigator.services.monoservice import InvestigatorMonoService
from docent_core.investigator.services.simple_rollout_service import SimpleRolloutService
from docent_core.investigator.tools.simple_rollout import (
    SimpleRolloutExperiment,
    SimpleRolloutExperimentResult,
    SimpleRolloutExperimentSummary,
)

logger = get_logger(__name__)


async def simple_rollout_experiment_job(ctx: WorkspaceContext, job: SQLAJob):
    """
    Run a simple rollout experiment and stream results to Redis.

    This worker:
    1. Loads the experiment configuration from the database
    2. Creates a SimpleRolloutExperiment instance
    3. Runs the experiment, streaming updates to Redis
    4. Publishes state updates that can be consumed by the frontend
    """

    investigator_svc = await InvestigatorMonoService.init()
    simple_rollout_svc = SimpleRolloutService(investigator_svc)

    # Get experiment config from job metadata
    experiment_config_id = job.job_json["experiment_config_id"]

    logger.info(f"Starting simple rollout experiment job for config {experiment_config_id}")

    # Load the experiment configuration
    config = await simple_rollout_svc.build_experiment_config(experiment_config_id)

    if config is None:
        raise ValueError(f"Experiment config {experiment_config_id} not found")

    # Set up Redis streaming
    REDIS = await get_redis_client()
    stream_key = STREAM_KEY_FORMAT.format(job_id=job.id)
    state_key = STATE_KEY_FORMAT.format(job_id=job.id)

    # In-memory publish deduplication and subscription caching
    last_publish_monotonic: float = 0.0
    last_state_signature: Tuple[Any, ...] | None = None
    # Throttle interval for publishes (seconds)
    THROTTLE_INTERVAL_S: float = 0.25
    # Pending signature to coalesce updates during throttle windows
    pending_signature: Tuple[Any, ...] | None = None

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

            subscribed = await REDIS.smembers(f"agent_run:subscriptions:{job.id}")  # type: ignore
            cached_subscribed_run_ids = {
                s.decode() if isinstance(s, bytes) else s for s in subscribed  # type: ignore
            }
            last_subscribed_fetch_monotonic = now
            return cached_subscribed_run_ids
        except Exception:
            logger.error(f"Failed to get subscribed runs: {traceback.format_exc()}")
            return set()

    def _compute_state_signature(
        result: SimpleRolloutExperimentResult, subscribed_run_ids: Set[str]
    ) -> Tuple[Any, ...]:
        """
        Compute a cheap, comparable signature over relevant fields.

        Avoids JSON serialization. Captures:
        - experiment status (status, progress rounded, error message presence)
        - agent_run_metadata: per-run (state, grade)
        - collection id
        - subscribed runs lightweight transcript signal
        """
        status = result.experiment_status
        status_sig: Tuple[str, float, bool] = (
            status.status,
            round(status.progress or 0.0, 3),
            bool(status.error_message),
        )

        meta = result.agent_run_metadata or {}
        # Only include lightweight per-run signals
        meta_sig: Tuple[Tuple[str, Any | None, Any | None], ...] = tuple(
            (run_id, m.state, m.grade.grade if m.grade else None)
            for run_id, m in sorted(meta.items())
        )

        # Subscribed runs lightweight transcript signal
        runs = result.agent_runs or {}
        subscribed_sig: list[Tuple[str, int, Tuple[Tuple[str, int, int], ...]]] = []
        for run_id in sorted(subscribed_run_ids):
            run = runs.get(run_id)
            if not run:
                continue
            # transcripts is a list, not a dict
            transcripts = run.transcripts
            # Build per-transcript cheap signal: message count and last msg tail length
            t_sigs: list[Tuple[str, int, int]] = []
            for t in transcripts:
                msgs = t.messages
                last_tail_len = 0
                if msgs:
                    last = msgs[-1]
                    content = last.content
                    if isinstance(content, str):
                        last_tail_len = len(content[-32:])
                t_sigs.append((t.id, len(msgs), last_tail_len))
            subscribed_sig.append((run_id, len(transcripts), tuple(t_sigs)))
        subscribed_sig_t: Tuple[Tuple[str, int, Tuple[Tuple[str, int, int], ...]], ...] = tuple(
            subscribed_sig
        )

        return (
            status_sig,
            meta_sig,
            result.docent_collection_id,
            subscribed_sig_t,
        )

    async def _maybe_publish_state(result: SimpleRolloutExperimentResult, *, force: bool = False):
        """
        Publish the current experiment state to Redis, de-duplicating identical states.

        Uses a lightweight signature and a throttle window to avoid expensive work.
        """
        nonlocal last_publish_monotonic, last_state_signature, pending_signature
        try:
            # Determine subscription set for signature and payload
            subscribed_run_ids = await _get_subscribed_runs()

            # Compute cheap signature and skip early if unchanged
            signature = _compute_state_signature(result, subscribed_run_ids)
            if last_state_signature is not None and signature == last_state_signature:
                # Clear any pending since we're already up-to-date
                pending_signature = None
                return

            now = time.monotonic()
            if not force and (now - last_publish_monotonic) < THROTTLE_INTERVAL_S:
                # Coalesce updates during the throttle window without doing heavy work
                pending_signature = signature
                return

            # Convert to SimpleRolloutExperimentSummary for frontend
            summary = result.summary()

            # Add full agent run data for subscribed runs (payload only)
            if subscribed_run_ids and result.agent_runs:
                summary.subscribed_agent_runs = {}
                for run_id in sorted(subscribed_run_ids):
                    if run_id in result.agent_runs:
                        summary.subscribed_agent_runs[run_id] = result.agent_runs[run_id]

            to_serialize = jsonable_encoder(summary)
            payload = json.dumps(to_serialize, sort_keys=True, separators=(",", ":"))

            await REDIS.set(state_key, payload, ex=1800)  # type: ignore
            await REDIS.xadd(stream_key, {"event": "state_updated"}, maxlen=200)  # type: ignore

            last_state_signature = signature
            last_publish_monotonic = time.monotonic()
            pending_signature = None

            logger.debug(
                f"Published state update for job {job.id} with {len(subscribed_run_ids)} subscribed runs"
            )
        except Exception:
            logger.error(f"Failed to publish state for job {job.id}: {traceback.format_exc()}")

    # Run the experiment
    experiment = SimpleRolloutExperiment(config)
    final_result = None

    try:
        logger.info(f"Starting experiment run for job {job.id}")

        # Stream results as they come in
        async for result in experiment.run():
            # Stream each update to Redis
            await _maybe_publish_state(result)
            # Keep track of the final result
            final_result = result

        logger.info(f"Experiment rollouts complete for job {job.id}; storing results")

        # Store the final result in the database with agent runs in a collection
        if final_result:
            try:
                assert ctx.user is not None, "User is required to store experiment results"

                # Mark experiment as completed before storing so DB captures completion
                if final_result.experiment_status.status != "error":
                    final_result.experiment_status.status = "completed"

                result_id = await simple_rollout_svc.store_experiment_result(
                    experiment_config_id=experiment_config_id,
                    result=final_result,
                    user=ctx.user,
                )
                logger.info(
                    f"Stored experiment result {result_id} for config {experiment_config_id}"
                )
                # Stream the final state with collection_id one last time
                await _maybe_publish_state(final_result, force=True)
            except Exception as e:
                logger.error(f"Failed to store experiment result: {e}\n{traceback.format_exc()}")
                # Don't fail the whole job if storage fails

        # Mark as finished only after attempting to store and publish final state
        await REDIS.xadd(stream_key, {"event": "finished"}, maxlen=200)  # type: ignore

    except Exception as e:
        logger.error(f"Experiment failed for job {job.id}: {e}\n{traceback.format_exc()}")

        if final_result:
            # Mark as error since we're in the exception handler
            final_result.experiment_status.status = "error"
            try:
                assert ctx.user is not None, "User is required to store experiment results"
                result_id = await simple_rollout_svc.store_experiment_result(
                    experiment_config_id=experiment_config_id,
                    result=final_result,
                    user=ctx.user,
                )
                logger.info(
                    f"Stored errored experiment result {result_id} for config {experiment_config_id}"
                )
                await _maybe_publish_state(final_result, force=True)
            except Exception as storage_e:
                logger.error(f"Failed to store errored experiment result: {storage_e}")
        else:
            # Mark any in-progress runs as errored
            try:
                raw = await REDIS.get(state_key)  # type: ignore
                if raw:
                    summary = SimpleRolloutExperimentSummary.model_validate_json(raw)
                    if summary.agent_run_metadata:
                        for m in summary.agent_run_metadata.values():
                            if getattr(m, "state", "in_progress") == "in_progress":
                                m.state = "errored"
                    payload = json.dumps(jsonable_encoder(summary))
                    await REDIS.set(state_key, payload, ex=600)  # type: ignore
            except Exception:
                logger.error("Failed to mark runs errored on failure; continuing")

        await REDIS.xadd(stream_key, {"event": "error", "error": "Experiment failed"}, maxlen=200)  # type: ignore
        raise

    finally:
        # Cleanup - set shorter TTL on completion and remove subscriptions
        await REDIS.expire(stream_key, 600)  # type: ignore
        await REDIS.expire(state_key, 600)  # type: ignore
        await REDIS.delete(f"agent_run:subscriptions:{job.id}")  # type: ignore
        logger.info(f"Cleaned up Redis keys for job {job.id}")
