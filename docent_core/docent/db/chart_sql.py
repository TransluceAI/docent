import logging
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Numeric, and_, case, cast, func, select
from sqlalchemy.sql import Select
from sqlalchemy.sql.sqltypes import Text

from docent_core.docent.db.filters import ComplexFilter
from docent_core.docent.db.schemas.rubric import (
    SQLAJudgeResult,
    SQLARubric,
)
from docent_core.docent.db.schemas.tables import (
    SQLAAgentRun,
)
from docent_core.docent.services.charts import (
    CountRunDimension,
    JudgeOutputDimension,
    RunMetadataDimension,
)

if TYPE_CHECKING:
    from docent_core.docent.services.charts import ChartDimension

logger = logging.getLogger(__name__)


class ChartSQLValidationError(Exception):
    """Raised when chart SQL parameters fail validation."""


def _convert_to_numeric(raw: Any) -> Any:
    """Convert raw measure values to numeric for aggregation."""
    raw_text = cast(raw, Text)

    return case(
        (
            # If it was a number originally, cast it back to number
            # Note: if measure were a numeric string originally, it wouldn't be available in the menu
            raw_text.op("~")(r"^[0-9]+\.?[0-9]*$"),  # type: ignore[attr-defined]
            cast(raw, Numeric),
        ),
        (
            # Handle boolean values - convert to 1.0/0.0
            func.lower(raw_text) == "true",
            1.0,
        ),
        (
            func.lower(raw_text) == "false",
            0.0,
        ),
        else_=None,  # Silently drop non-numeric strings
    )


def generate_chart_query(
    dimensions: list["ChartDimension"],
    measure: "ChartDimension",
    runs_filter: Optional[ComplexFilter],
    collection_id: str,
) -> Select[Any]:
    """Generate SQL query for chart data using ChartDimension objects.

    Builds a single-level SELECT with proper joins, filters, and aggregation.

    Args:
        dimensions: List of ChartDimension objects for grouping
        measure: ChartDimension object for the measure
        runs_filter: Optional filter for agent runs
        collection_id: Collection to query

    Returns:
        Complete SQL query for chart data

    Raises:
        ChartSQLValidationError: If any parameters fail validation
    """

    all_dimensions = dimensions + [measure]
    unique_dimensions = list({dim.key: dim for dim in all_dimensions}.values())

    # Only get runs that are in the collection and match the filter
    where_clause = SQLAAgentRun.collection_id == collection_id
    if runs_filter:
        runs_filter_clause = runs_filter.to_sqla_where_clause(SQLAAgentRun)
        if runs_filter_clause is not None:
            where_clause = and_(where_clause, runs_filter_clause)

    from_clause: Any = SQLAAgentRun.__table__

    column_map: dict[str, Any] = {"id": SQLAAgentRun.id}
    metadata_dims = [d for d in unique_dimensions if isinstance(d, RunMetadataDimension)]
    for dim in metadata_dims:
        column_map[dim.key] = dim.expression

    judge_results_table = SQLAJudgeResult.__table__.join(
        SQLARubric.__table__,
        and_(
            SQLAJudgeResult.rubric_id == SQLARubric.id,
            SQLAJudgeResult.rubric_version == SQLARubric.version,
        ),
    )

    # Join one judge subquery per judge dimension
    judge_dims = [d for d in unique_dimensions if isinstance(d, JudgeOutputDimension)]
    for idx, dim in enumerate(judge_dims):
        judge_subquery = (
            select(SQLAJudgeResult.agent_run_id, dim.expression.label(dim.key))
            .select_from(judge_results_table)
            .where(
                and_(
                    SQLAJudgeResult.rubric_id == dim.judge_id,
                    SQLAJudgeResult.rubric_version == dim.judge_version,
                )
            )
            .subquery(name=f"judge_subquery_{idx}")
        )

        from_clause = from_clause.join(
            judge_subquery, SQLAAgentRun.id == judge_subquery.c.agent_run_id
        )
        column_map[dim.key] = judge_subquery.c[dim.key]

    # Build SELECT and GROUP BY clauses for aggregation
    outer_select: list[Any] = []
    outer_group_by: list[Any] = []

    for dim in dimensions:
        if isinstance(dim, (RunMetadataDimension, JudgeOutputDimension)):
            dim_expr = column_map[dim.key]
            outer_select.append(dim_expr.label(dim.key))
            outer_group_by.append(dim_expr)
        else:
            raise TypeError(f"Unsupported dimension type: {type(dim)}")

    if isinstance(measure, CountRunDimension):
        outer_select.append(func.count(column_map["id"]).label("measure_value"))
    else:
        numeric_value = _convert_to_numeric(column_map[measure.key])

        avg_measure = func.avg(numeric_value)
        count_measure = func.count(numeric_value)
        stddev_measure = func.stddev(numeric_value)

        ci_measure = case(
            (
                func.coalesce(count_measure, 0) > 1,
                1.96 * func.coalesce(stddev_measure, 0) / func.sqrt(count_measure),
            ),
            else_=0,
        )

        outer_select.append(avg_measure.label("measure_value"))
        outer_select.append(count_measure.label("measure_count"))
        outer_select.append(ci_measure.label("measure_ci"))

    return (
        select(*outer_select)
        .select_from(from_clause)
        .where(where_clause)
        .group_by(*outer_group_by)
        .order_by(*outer_group_by)
    )
