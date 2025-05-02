from time import perf_counter
from typing import Any, Awaitable, Callable, cast

import anyio
from docent._frames.db.service import DBService, MarginalizationResult
from docent._frames.transcript import TranscriptMetadata
from docent._server._broker.redis_client import publish_to_broker
from log_util import get_logger

logger = get_logger(__name__)


async def _ids_map_fn(ids: list[str], _):
    return ids


async def _intervention_descriptions_map_fn(_, metadata: list[TranscriptMetadata]):
    return list(set(m.intervention_description for m in metadata if m.intervention_description))


async def _stats_map_fn(_, metadata: list[TranscriptMetadata]):
    """Calculate mean score with 95% confidence interval for each score key.

    Returns:
        Dict containing statistics for each score key.
        Each key has mean score, confidence interval half-width, and sample size.
        Returns None if there are no matching indices.
    """
    if not metadata:
        return {"mean": None, "ci": None, "n": 0}

    # First pass: collect all available score keys and their values
    all_outcomes: dict[str, list[float | None]] = {}
    for m in metadata:
        for score_key, score_value in m.scores.items():
            cur_list = all_outcomes.setdefault(score_key, [])
            cur_list.append(float(score_value) if not m.is_loading_messages else None)

    # Calculate statistics for each score key
    results: dict[str, dict[str, float | None]] = {}
    for score_key, outcomes in all_outcomes.items():
        if outcomes and any(outcome is None for outcome in outcomes):
            results[score_key] = {"mean": None, "ci": None, "n": len(outcomes)}
            continue

        # Calculate mean
        outcomes = cast(list[float], outcomes)
        n = len(outcomes)
        mean = sum(outcomes) / n

        # Calculate 95% CI using normal approximation
        # z-score for 95% CI is 1.96
        if n > 1:  # Need at least 2 samples for std
            std = (sum((x - mean) ** 2 for x in outcomes) / (n - 1)) ** 0.5
            ci = 1.96 * std / (n**0.5)
        else:
            # With 1 sample, we can't calculate CI
            ci = 0

        results[score_key] = {"mean": mean, "ci": ci, "n": n}

    # The frontend expects some aggregate data, otherwise it won't show the sample/experiment.
    if not results:
        results["default"] = {"mean": None, "ci": None, "n": len(metadata)}

    return results


def _format_bin_combination(bin_combination: tuple[tuple[str, str], ...]) -> str:
    return "|".join(",".join(pair) for pair in bin_combination)


async def publish_dims(db: DBService, fg_id: str):
    await publish_to_broker(
        fg_id,
        {
            "action": "dimensions",
            "payload": await db.get_dims(fg_id),
        },
    )


async def publish_marginals(
    db: DBService, fg_id: str, dim_ids: list[str] | None = None, ensure_fresh: bool = True
):
    async def _publish_dim_callback(_):
        await publish_dims(db, fg_id)

    marginals = await db.get_marginals(
        fg_id,
        keep_dim_ids=dim_ids,
        ensure_fresh=ensure_fresh,
        publish_dim_callback=_publish_dim_callback,
    )
    await publish_to_broker(
        fg_id,
        {
            "action": "marginals",
            "payload": marginals,
        },
    )


async def publish_base_filter(db: DBService, fg_id: str):
    base_filter = await db.get_base_filter(fg_id)
    await publish_to_broker(
        fg_id,
        {
            "action": "base_filter",
            "payload": base_filter,
        },
    )


async def publish_datapoints_updated(fg_id: str, datapoint_ids: list[str] | None):
    await publish_to_broker(
        fg_id,
        {
            "action": "datapoints_updated",
            "payload": datapoint_ids,
        },
    )


async def publish_homepage_marginals(db: DBService, fg_id: str):
    sample_dim_id = await db.get_sample_dim_id(fg_id)
    experiment_dim_id = await db.get_experiment_dim_id(fg_id)

    if sample_dim_id is None or experiment_dim_id is None:
        raise ValueError("Sample or experiment dimension not found")

    # Gather base data, as this is needed for map functions
    metadata_with_ids = await db.get_metadata_with_ids(fg_id, base_data_only=True)
    metadata_dict = {id: md for id, md in metadata_with_ids}

    # Get all required marginals once
    marginals = await db.get_marginals(fg_id, keep_dim_ids=[sample_dim_id, experiment_dim_id])
    # Marginalize using cached marginals; prevents multile duplicate requests
    sample_exp_marginals = await db.marginalize(
        fg_id,
        keep_dim_ids=[sample_dim_id, experiment_dim_id],
        return_dims_and_filters=True,
        _marginals=marginals,
    )
    sample_marginals = await db.marginalize(
        fg_id,
        keep_dim_ids=[sample_dim_id],
        _marginals=marginals,
    )
    experiment_marginals = await db.marginalize(
        fg_id,
        keep_dim_ids=[experiment_dim_id],
        _marginals=marginals,
    )

    async def _apply_fn(
        marginal: MarginalizationResult,
        map_fn: Callable[[list[str], list[TranscriptMetadata]], Awaitable[Any]],
    ):
        to_send = dict(marginal)
        to_send["marginals"] = {
            _format_bin_combination(bin_combination): await map_fn(
                [j.data_id for j in judgments],
                [metadata_dict[j.data_id] for j in judgments],
            )
            for bin_combination, judgments in marginal["marginals"].items()
        }
        return to_send

    # Apply map functions to get processed marginals
    sample_exp_stat_marginals = await _apply_fn(sample_exp_marginals, _stats_map_fn)
    sample_exp_ids_marginals = await _apply_fn(sample_exp_marginals, _ids_map_fn)
    sample_stat_marginals = await _apply_fn(sample_marginals, _stats_map_fn)
    experiment_stat_marginals = await _apply_fn(experiment_marginals, _stats_map_fn)
    experiment_intervention_description_marginals = await _apply_fn(
        experiment_marginals, _intervention_descriptions_map_fn
    )

    # Send all processed marginals at once
    async with anyio.create_task_group() as tg:
        tg.start_soon(
            publish_to_broker,
            fg_id,
            {
                "action": "specific_marginals",
                "payload": {
                    "request_type": "exp_stats",
                    "result": sample_exp_stat_marginals,
                },
            },
        )
        tg.start_soon(
            publish_to_broker,
            fg_id,
            {
                "action": "specific_marginals",
                "payload": {
                    "request_type": "exp_ids",
                    "result": sample_exp_ids_marginals,
                },
            },
        )
        tg.start_soon(
            publish_to_broker,
            fg_id,
            {
                "action": "specific_marginals",
                "payload": {
                    "request_type": "per_sample_stats",
                    "result": sample_stat_marginals,
                },
            },
        )
        tg.start_soon(
            publish_to_broker,
            fg_id,
            {
                "action": "specific_marginals",
                "payload": {
                    "request_type": "per_experiment_stats",
                    "result": experiment_stat_marginals,
                },
            },
        )
        tg.start_soon(
            publish_to_broker,
            fg_id,
            {
                "action": "specific_marginals",
                "payload": {
                    "request_type": "intervention_descriptions",
                    "result": experiment_intervention_description_marginals,
                },
            },
        )


async def publish_state(
    db: DBService,
    fg_id: str,
    profile: bool = False,
):
    # Define coroutines and their names
    coroutines = [
        (publish_base_filter, "publish_base_filter", [db, fg_id]),
        # Don't need to push all marginals, I think
        # (publish_all_marginals, "publish_all_marginals", [db, fg_id, True]),
        (publish_dims, "publish_dims", [db, fg_id]),
        (publish_homepage_marginals, "publish_homepage_marginals", [db, fg_id]),
        # (publish_datapoints_updated, "publish_datapoints_updated", [fg_id, None]),
    ]

    for coro_func, coro_name, args in coroutines:
        if profile:
            start_time = perf_counter()
            await coro_func(*args)
            logger.info(f"{coro_name} took {perf_counter() - start_time:.4f} seconds")
        else:
            await coro_func(*args)
