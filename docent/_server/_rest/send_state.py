from typing import Any, Awaitable, Callable, cast

import anyio
from sqlalchemy.inspection import inspect as sqla_inspect

from docent._db_service.contexts import ViewContext
from docent._db_service.service import DBService, MarginalizationResult
from docent._log_util import get_logger
from docent._server._broker.redis_client import (
    publish_framegrid_update,
    publish_to_broker,
    publish_view_update,
)
from docent.data_models.metadata import BaseAgentRunMetadata

logger = get_logger(__name__)


async def _ids_map_fn(ids: list[str], _: Any):
    return ids


async def _stats_map_fn(_: Any, metadata: list[BaseAgentRunMetadata]):
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
            cur_list.append(float(score_value) if score_value is not None else None)

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


async def publish_dims(db: DBService, ctx: ViewContext):
    await publish_framegrid_update(
        ctx.fg_id,
        {
            "action": "dimensions",
            "payload": await db.get_view_dims(ctx),
        },
    )


async def publish_marginals(
    db: DBService,
    ctx: ViewContext,
    dim_ids: list[str] | None = None,
    ensure_fresh: bool = True,
):
    async def _publish_dim_callback(_: Any):
        await publish_dims(db, ctx)

    marginals = await db.get_marginals(
        ctx,
        keep_dim_ids=dim_ids,
        ensure_fresh=ensure_fresh,
        publish_dim_callback=_publish_dim_callback,
    )

    await publish_framegrid_update(
        ctx.fg_id,
        {
            "action": "marginals",
            "payload": marginals,
        },
    )


async def publish_base_filter(db: DBService, ctx: ViewContext):
    await publish_view_update(
        ctx.fg_id,
        ctx.view_id,
        {
            "action": "base_filter",
            "payload": ctx.base_filter,
        },
    )


async def publish_io_dims(db: DBService, ctx: ViewContext):
    io_dims = await db.get_io_dims(ctx)
    assert (
        io_dims is not None
    ), f"No inner or outer dimension specified for fg_id={ctx.fg_id}, view_id={ctx.view_id}"
    inner_dim_id, outer_dim_id = io_dims

    await publish_view_update(
        ctx.fg_id,
        ctx.view_id,
        {
            "action": "io_dims_updated",
            "payload": {
                "inner_dim_id": inner_dim_id,
                "outer_dim_id": outer_dim_id,
            },
        },
    )


async def publish_searches(db: DBService, ctx: ViewContext):
    await publish_view_update(
        ctx.fg_id,
        ctx.view_id,
        {
            "action": "searches",
            "payload": await db.get_searches_with_result_counts(ctx),
        },
    )


async def _publish_homepage_marginals(
    db: DBService,
    ctx: ViewContext,
    inner_dim_id: str | None,
    outer_dim_id: str | None,
):
    # Gather base data, as this is needed for map functions
    metadata_with_ids = await db.get_metadata_with_ids(ctx)
    metadata_dict = {id: md for id, md in metadata_with_ids}

    # Get all required marginals once
    keep_dim_ids = [dim_id for dim_id in [inner_dim_id, outer_dim_id] if dim_id is not None]
    marginals = await db.get_marginals(ctx, keep_dim_ids=keep_dim_ids)
    # Marginalize using cached marginals; prevents multile duplicate requests
    comb_marginals = await db.marginalize(
        ctx,
        keep_dim_ids,
        return_dims_and_filters=True,
        _marginals=marginals,
    )
    outer_marginals = (
        await db.marginalize(
            ctx,
            [outer_dim_id],
            _marginals=marginals,
        )
        if outer_dim_id
        else None
    )

    async def _apply_fn(
        marginal: MarginalizationResult,
        map_fn: Callable[[list[str], list[BaseAgentRunMetadata]], Awaitable[Any]],
    ):
        to_send = dict(marginal)
        to_send["marginals"] = {
            _format_bin_combination(bin_combination): await map_fn(
                [j.agent_run_id for j in judgments],
                [metadata_dict[j.agent_run_id] for j in judgments],
            )
            for bin_combination, judgments in marginal["marginals"].items()
        }
        return to_send

    # Apply map functions to get processed marginals
    comb_stat_marginals = await _apply_fn(comb_marginals, _stats_map_fn)
    comb_ids_marginals = await _apply_fn(comb_marginals, _ids_map_fn)
    outer_stat_marginals = (
        await _apply_fn(outer_marginals, _stats_map_fn) if outer_marginals else None
    )

    # Send all processed marginals at once
    async with anyio.create_task_group() as tg:
        tg.start_soon(
            publish_view_update,
            ctx.fg_id,
            ctx.view_id,
            {
                "action": "specific_marginals",
                "payload": {
                    "request_type": "comb_stats",
                    "result": comb_stat_marginals,
                },
            },
        )
        tg.start_soon(
            publish_view_update,
            ctx.fg_id,
            ctx.view_id,
            {
                "action": "specific_marginals",
                "payload": {
                    "request_type": "comb_ids",
                    "result": comb_ids_marginals,
                },
            },
        )
        tg.start_soon(
            publish_view_update,
            ctx.fg_id,
            ctx.view_id,
            {
                "action": "specific_marginals",
                "payload": {
                    "request_type": "outer_stats",
                    "result": outer_stat_marginals,
                },
            },
        )


async def publish_framegrids(db: DBService):
    """Publish updated framegrids to all connected clients."""
    sqla_fgs = await db.get_fgs()
    framegrids = [
        # Get all columns from the SQLAlchemy object
        {c.key: getattr(obj, c.key) for c in sqla_inspect(obj).mapper.column_attrs}
        for obj in sqla_fgs
    ]

    await publish_to_broker(
        None,  # Broadcast to the general channel
        {
            "action": "framegrids_updated",
            "payload": framegrids,
        },
    )


async def publish_homepage_state(db: DBService, ctx: ViewContext):
    """Publish homepage state for a specific view. Always requires ViewProvider since base filters are view-scoped."""
    io_dims = await db.get_io_dims(ctx)
    assert io_dims is not None, f"View {ctx.view_id} has no inner or outer dimension specified"
    inner_dim_id, outer_dim_id = io_dims

    await publish_base_filter(db, ctx)
    await publish_dims(db, ctx)
    await publish_io_dims(db, ctx)
    await _publish_homepage_marginals(db, ctx, inner_dim_id, outer_dim_id)
    await publish_searches(db, ctx)
