from typing import Any

from sqlalchemy import text
from sqlalchemy.inspection import inspect as sqla_inspect

from docent._db_service.contexts import ViewContext
from docent._db_service.schemas.tables import SQLAAgentRun
from docent._db_service.service import DBService
from docent._log_util import get_logger
from docent._server._broker.redis_client import (
    publish_to_broker,
    publish_view_update,
)
from docent.data_models.metadata import FrameDimension

logger = get_logger(__name__)


async def publish_binnable_keys(db: DBService, ctx: ViewContext):
    """Publish keys that can be set as the io bin keys"""

    bin_keys = await db.get_binnable_keys(ctx)

    # Convert to FrameDimension objects
    dimensions = [
        FrameDimension(
            id=key,
            name=key,
            search_query=None,
            metadata_key=key,
            maintain_mece=None,
            loading_clusters=False,
            loading_bins=False,
            binIds=None,
        )
        for key in sorted(bin_keys)
    ]

    # Publish to frontend
    await publish_view_update(
        ctx.fg_id,
        ctx.view_id,
        {
            "action": "dimensions",
            "payload": dimensions,
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


async def publish_io_bin_keys(db: DBService, ctx: ViewContext):
    io_dims = await db.get_io_bin_keys(ctx)
    inner_bin_key, outer_bin_key = io_dims if io_dims is not None else (None, None)

    await publish_view_update(
        ctx.fg_id,
        ctx.view_id,
        {
            "action": "io_dims_updated",
            "payload": {
                "inner_bin_key": inner_bin_key,
                "outer_bin_key": outer_bin_key,
            },
        },
    )

    return inner_bin_key, outer_bin_key


async def publish_searches(db: DBService, ctx: ViewContext):
    await publish_view_update(
        ctx.fg_id,
        ctx.view_id,
        {
            "action": "searches",
            "payload": await db.get_searches_with_result_counts(ctx),
        },
    )


async def publish_bin_stats_and_agent_runs(
    db: DBService,
    ctx: ViewContext,
    inner_bin_key: str | None,
    outer_bin_key: str | None,
):
    """Publish homepage binStats and agentRunIds"""

    # Get all agent run IDs for this view
    all_agent_run_ids = await db.get_agent_run_ids(ctx)

    # If no bin keys are set, we still need to publish agent run IDs for the frontend
    # if no agent runs, we publish empty binStats and agentRunIds
    if (inner_bin_key is None and outer_bin_key is None) or len(all_agent_run_ids) == 0:
        payload: dict[str, Any] = {
            "request_type": "comb_stats",
            "result": {
                "binStats": {},
                "agentRunIds": all_agent_run_ids,
            },
        }
        await publish_view_update(
            ctx.fg_id,
            ctx.view_id,
            {
                "action": "specific_bins",
                "payload": payload,
            },
        )

        return

    # Get the bin keys that are set
    bin_keys = [bin_key for bin_key in [inner_bin_key, outer_bin_key] if bin_key is not None]

    # Build the WHERE clause for the base filter
    # Convert the SQLAlchemy where clause to a string representation
    base_where = ctx.get_base_where_clause(SQLAAgentRun)

    from sqlalchemy.dialects import postgresql

    compiled_where = base_where.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    where_clause = str(compiled_where)

    # Build the SQL query to compute statistics directly
    async with db.session() as session:
        # Build the GROUP BY clause based on the number of bins
        if len(bin_keys) == 1:
            # 1D case: group by single dimension
            dim_key = bin_keys[0]
            group_by_clause = f"metadata_json->>'{dim_key}'"
            # Format bin key as dim_key,value
            bin_key_format = f"CONCAT('{dim_key},', metadata_json->>'{dim_key}')"
        elif len(bin_keys) == 2:
            # 2D case: group by both bins
            inner_key, outer_key = bin_keys
            group_by_clause = f"metadata_json->>'{inner_key}', metadata_json->>'{outer_key}'"
            # Format bin key as inner_key,inner_value|outer_key,outer_value
            bin_key_format = f"CONCAT('{inner_key},', metadata_json->>'{inner_key}', '|{outer_key},', metadata_json->>'{outer_key}')"
        else:
            logger.error(
                f"_publish_homepage_bins_optimized: unexpected number of bin keys: {len(bin_keys)}"
            )
            return

        # Create the query that computes statistics
        query = f"""
        WITH bin_groups AS (
            SELECT
                {bin_key_format} as bin_key,
                COUNT(*) as n
            FROM agent_runs
            WHERE {where_clause}
            GROUP BY {group_by_clause}
        ),
        score_stats AS (
            SELECT
                {bin_key_format} as bin_key,
                scores.key as score_key,
                COUNT(*) as n,
                AVG(
                    CASE
                        WHEN scores.value ~ '^[0-9]+\\.?[0-9]*$' THEN scores.value::float
                        WHEN LOWER(scores.value) IN ('true', 'false') THEN
                            CASE WHEN LOWER(scores.value) = 'true' THEN 1.0 ELSE 0.0 END
                        ELSE NULL
                    END
                ) as mean,
                STDDEV(
                    CASE
                        WHEN scores.value ~ '^[0-9]+\\.?[0-9]*$' THEN scores.value::float
                        WHEN LOWER(scores.value) IN ('true', 'false') THEN
                            CASE WHEN LOWER(scores.value) = 'true' THEN 1.0 ELSE 0.0 END
                        ELSE NULL
                    END
                ) as stddev
            FROM agent_runs
            CROSS JOIN LATERAL jsonb_each_text(metadata_json->'scores') as scores(key, value)
            WHERE {where_clause}
            AND metadata_json->'scores' IS NOT NULL
            AND metadata_json->'scores' != 'null'::jsonb
            AND (
                -- Handle numeric values
                scores.value ~ '^[0-9]+\\.?[0-9]*$'
                OR
                -- Handle boolean values (convert to 0/1)
                LOWER(scores.value) IN ('true', 'false')
            )
            GROUP BY {group_by_clause}, scores.key
        )
        SELECT
            bg.bin_key,
            COALESCE(ss.score_key, 'default') as score_key,
            COALESCE(ss.n, bg.n) as n,
            ss.mean,
            CASE
                WHEN COALESCE(ss.n, bg.n) > 1 AND ss.stddev IS NOT NULL THEN 1.96 * ss.stddev / SQRT(COALESCE(ss.n, bg.n))
                ELSE 0
            END as ci
        FROM bin_groups bg
        LEFT JOIN score_stats ss ON bg.bin_key = ss.bin_key
        ORDER BY bg.bin_key, score_key
        """

        # Execute the query
        result = await session.execute(text(query))

        # Process the results
        processed_stats = {}
        row_count = 0

        for row in result:
            row_count += 1
            bin_key = row.bin_key
            score_key = row.score_key
            n = row.n
            mean = row.mean
            ci = row.ci

            logger.debug(
                f"_publish_homepage_bins_optimized: processing row {row_count}: bin={bin_key}, score={score_key}, n={n}, mean={mean}, ci={ci}"
            )

            if bin_key not in processed_stats:
                processed_stats[bin_key] = {}

            processed_stats[bin_key][score_key] = {
                "mean": float(mean) if mean is not None else None,
                "ci": float(ci) if ci is not None else None,
                "n": int(n) if n is not None else 0,
            }

    # Publish the state with both agent run IDs and bin statistics
    payload = {
        "request_type": "comb_stats",
        "result": {
            "binStats": processed_stats,  # Statistics for table/graph
            "agentRunIds": all_agent_run_ids,  # Agent run IDs for the list
        },
    }

    await publish_view_update(
        ctx.fg_id,
        ctx.view_id,
        {
            "action": "specific_bins",
            "payload": payload,
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

    # Publish base filter
    await publish_base_filter(db, ctx)

    # Publish dimensions
    await publish_binnable_keys(db, ctx)

    # Publish current bin keys
    inner_bin_key, outer_bin_key = await publish_io_bin_keys(db, ctx)

    # Publish bin stats and agent runs
    await publish_bin_stats_and_agent_runs(db, ctx, inner_bin_key, outer_bin_key)

    # Publish searches
    await publish_searches(db, ctx)
