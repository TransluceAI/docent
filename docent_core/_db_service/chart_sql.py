import logging
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import Numeric, and_, case, cast, func, select, text
from sqlalchemy.sql import Select
from sqlalchemy.sql.sqltypes import Text

from docent_core._db_service.filters import ComplexFilter
from docent_core._db_service.schemas.rubric import (
    SQLAJudgeResult,
    SQLAJudgeResultCentroid,
    SQLARubric,
    SQLARubricCentroid,
)
from docent_core._db_service.schemas.tables import (
    SQLAAgentRun,
)

if TYPE_CHECKING:
    from docent_core.docent.services.charts import ChartDimension

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Aggregate-related helpers
# ----------------------------------------------------------------------------


def _extract_constituent_fields(expr: Any) -> List[Any]:
    """Extract constituent fields from aggregate expressions.

    * For aggregate expressions like ``COUNT(DISTINCT ar.id)`` this returns
      a list containing the underlying column(s) with *no* DISTINCT wrapper.
    * For non-aggregate expressions, it returns the expression itself (again
      stripped of any DISTINCT modifier).

    Removing DISTINCT here prevents the generator from producing SQL that
    contains both a query-level ``DISTINCT`` and a column-level ``DISTINCT``,
    a combination that Postgres rejects.
    """

    fields: List[Any] = []

    # Handle func-based aggregates (e.g. ``func.count(col.distinct())``)
    if hasattr(expr, "clause_expr"):
        clause_expr = expr.clause_expr
        fields.append(clause_expr)

    # Handle ClauseList aggregates (e.g. multiple arguments)
    if hasattr(expr, "clauses") and expr.clauses is not None:
        for clause in expr.clauses:
            # Nested ClauseList – recurse into its elements first
            if hasattr(clause, "clauses") and clause.clauses:
                for nested in clause.clauses:  # type: ignore[attr-defined]
                    fields.append(nested)
            else:
                fields.append(clause)

    if not fields:
        fields.append(expr)

    # Deduplicate while preserving order.
    seen: set[Any] = set()
    unique_fields: List[Any] = []
    for f in fields:
        if f not in seen:
            unique_fields.append(f)
            seen.add(f)

    return unique_fields


def _get_table_references(expr: Any) -> set[str]:
    """Extract table references from SQLAlchemy expressions.

    Returns a set of table aliases that the expression references.
    """
    references: set[str] = set()

    # Handle None or primitive types safely
    if expr is None or isinstance(expr, (str, int, float, bool)):
        return references

    try:
        # Handle column references
        if hasattr(expr, "table") and expr.table is not None:
            table_name = expr.table.name
            # Map table names to aliases used in the original string implementation
            references.add(table_name)

        # Handle JSON operators (->>, ->) - these are BinaryExpression with left/right
        if hasattr(expr, "left") and hasattr(expr, "right"):
            # For JSON expressions like ar.metadata_json->>'scores', check the left side
            references.update(_get_table_references(expr.left))
            # Also check right side in case it contains references
            if hasattr(expr.right, "table") or hasattr(expr.right, "left"):
                references.update(_get_table_references(expr.right))

        # Handle function calls - recursively check arguments
        if hasattr(expr, "clause_expr"):
            references.update(_get_table_references(expr.clause_expr))

        if hasattr(expr, "clauses") and expr.clauses is not None:
            for clause in expr.clauses:
                references.update(_get_table_references(clause))

        # Handle .distinct() and similar modifiers
        if hasattr(expr, "element"):
            references.update(_get_table_references(expr.element))

    except (TypeError, AttributeError) as e:
        # Log and continue if we encounter unexpected expression types
        logger.debug(f"Unable to extract table references from expression {type(expr)}: {e}")

    return references


class ChartSQLValidationError(Exception):
    """Raised when chart SQL parameters fail validation."""


def _apply_run_normalization(
    base_query: Select[Any],
    dimensions: List["ChartDimension"],
    visible_collection_ids: List[str],
) -> Select[Any]:
    """Apply run normalization using explicit column construction."""

    # Get agent run dimensions for run counting
    ar_dimensions = [dim for dim in dimensions if dim.key.startswith("ar.")]

    # Create a subquery from the base query first
    base_subquery = base_query.subquery()

    # Build run count subquery - either total count or grouped by dimensions
    run_count_select = [func.count(SQLAAgentRun.id.distinct()).label("run_count")]
    run_count_group_by: List[Any] = []

    # Add grouping columns if we have agent run dimensions
    for dim in ar_dimensions:
        field_expr = dim.expression
        run_count_select.append(field_expr.label(dim.key))
        run_count_group_by.append(field_expr)

    run_count_query = (
        select(*run_count_select)
        .select_from(SQLAAgentRun)
        .where(SQLAAgentRun.collection_id.in_(visible_collection_ids))
    )

    # Only add group by if we have dimensions to group by
    if run_count_group_by:
        run_count_query = run_count_query.group_by(*run_count_group_by)

    run_count_subquery = run_count_query.subquery()

    # Build join conditions - cross join if no dimensions, equi-join if dimensions exist
    if ar_dimensions:
        join_conditions: List[Any] = []
        for dim in ar_dimensions:
            join_conditions.append(base_subquery.c[dim.key] == run_count_subquery.c[dim.key])

        joined_query = base_subquery.join(run_count_subquery, and_(*join_conditions))
    else:
        # Cross join for the simple case (no grouping dimensions)
        joined_query = base_subquery.join(run_count_subquery, text("1=1"))

    # Create final query with normalization
    final_select: List[Any] = []
    for column in base_subquery.c:
        if column.name == "measure_value":
            normalized_measure = column / run_count_subquery.c.run_count
            final_select.append(normalized_measure.label("measure_value"))
            final_select.append(run_count_subquery.c.run_count.label("measure_count"))
        else:
            final_select.append(column)

    return select(*final_select).select_from(joined_query)


# -----------------------------------------------------------------------------
# Stage 1 – build the joined base query with static filters
# -----------------------------------------------------------------------------


def _build_base_query(
    visible_collection_ids: List[str],
    runs_filter: Optional[ComplexFilter],
    rubric_filter: Optional[str],
) -> Select[Any]:
    """Return foundational SELECT with all necessary joins & static filters."""

    base = (
        select()
        .select_from(
            SQLAAgentRun.__table__.join(
                SQLAJudgeResult.__table__,
                and_(
                    SQLAJudgeResult.agent_run_id == SQLAAgentRun.id,
                    SQLAJudgeResult.value.isnot(None),
                ),
                isouter=True,
            )
            .join(
                SQLARubric.__table__,
                and_(
                    SQLAJudgeResult.rubric_id == SQLARubric.id,
                    SQLAJudgeResult.rubric_version == SQLARubric.version,
                ),
                isouter=True,
            )
            .join(
                SQLAJudgeResultCentroid.__table__,
                SQLAJudgeResultCentroid.judge_result_id == SQLAJudgeResult.id,
                isouter=True,
            )
            .join(
                SQLARubricCentroid.__table__,
                and_(
                    SQLAJudgeResultCentroid.centroid_id == SQLARubricCentroid.id,
                    SQLAJudgeResultCentroid.decision == True,
                ),
                isouter=True,
            )
        )
        .where(SQLAAgentRun.collection_id.in_(visible_collection_ids))
    )

    # Optional runs filter
    if runs_filter:
        runs_filter_clause = runs_filter.to_sqla_where_clause(SQLAAgentRun)
        if runs_filter_clause is not None:
            base = base.where(runs_filter_clause)

    # Optional user-supplied search-query filter
    if rubric_filter:
        # Constrain to the latest version of the requested rubric ID
        latest_version_subq = (
            select(func.max(SQLARubric.version))
            .where(SQLARubric.id == rubric_filter)
            .scalar_subquery()
        )
        base = base.where(
            and_(
                SQLAJudgeResult.rubric_id == rubric_filter,
                SQLAJudgeResult.rubric_version == latest_version_subq,
            )
        )

    return base


# -----------------------------------------------------------------------------
# Stage 2 – DISTINCT de-duplication to collapse fan-out joins
# -----------------------------------------------------------------------------


# Return type is `Any` because SQLAlchemy's Subquery type is not a Select.
def _deduplicate(
    base_query: Select[Any], dimensions: List["ChartDimension"], measure: "ChartDimension"
) -> Any:
    """Produce a sub-query that holds *unique* rows for the dimension/measures."""

    dedup_select: List[Any] = []
    group_by_exprs: List[Any] = []

    # --------------------------------------
    # 2a. Dimension columns
    # --------------------------------------
    for dim in dimensions:
        field_expr = dim.expression
        dedup_select.append(field_expr.label(dim.key))  # type: ignore[arg-type]
        group_by_exprs.append(field_expr)

    # --------------------------------------
    # 2b. Measure helper columns – raw or constituent fields
    # --------------------------------------
    if not measure.is_aggregation:
        # Non-aggregate measures need the raw value for AVG later **only** when
        # we have dimensions (otherwise we can aggregate directly).
        if group_by_exprs:
            dedup_select.append(measure.expression.label("raw_measure"))  # type: ignore[arg-type]
    else:
        # Extract underlying columns so outer aggregation can reconstruct the fn.
        for idx, field in enumerate(_extract_constituent_fields(measure.expression)):
            label = f"measure_field_{idx}"
            actual_field = field.element if hasattr(field, "element") else field
            if hasattr(actual_field, "label"):
                dedup_select.append(actual_field.label(label))  # type: ignore[arg-type]
            else:
                from sqlalchemy import literal_column

                dedup_select.append(literal_column(str(actual_field)).label(label))  # type: ignore[arg-type]

    # --------------------------------------
    # 2c. Include primary IDs of *referenced* tables to guarantee uniqueness
    # --------------------------------------
    referenced_tables: set[str] = set()
    for dim in dimensions:
        referenced_tables.update(_get_table_references(dim.expression))
    referenced_tables.update(_get_table_references(measure.expression))

    if measure.is_aggregation:
        for field in _extract_constituent_fields(measure.expression):
            referenced_tables.update(_get_table_references(field))
    table_id_map = {
        "agent_runs": SQLAAgentRun.id.label("ar_id"),
        "judge_results": SQLAJudgeResult.id.label("jr_id"),
        "rubrics": SQLARubric.id.label("r_id"),
        "rubric_centroids": SQLARubricCentroid.id.label("rc_id"),
        "judge_result_centroids": SQLAJudgeResultCentroid.id.label("jrc_id"),
    }
    for name in referenced_tables:
        if name in table_id_map:
            dedup_select.append(table_id_map[name])  # type: ignore[arg-type]

    # --------------------------------------
    # 2d. DISTINCT to collapse duplicates
    # --------------------------------------
    dedup_query = base_query.add_columns(*dedup_select).distinct()  # type: ignore[arg-type]
    return dedup_query.subquery()


# -----------------------------------------------------------------------------
# Stage 3 – outer aggregation on top of deduplication
# -----------------------------------------------------------------------------


def _convert_to_numeric(raw: Any) -> Any:
    # Create text representation of raw measure for compatibility
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


def _aggregate(
    dedup_subquery: Any, dimensions: List["ChartDimension"], measure: "ChartDimension"
) -> Select[Any]:
    """Apply the final aggregation/group-by layer taken from the original code."""

    outer_select: List[Any] = []
    outer_group_by: List[Any] = []

    # Dimension columns pass through
    for dim in dimensions:
        col_ref = dedup_subquery.c[dim.key]

        outer_select.append(col_ref.label(dim.key))  # type: ignore[arg-type]
        outer_group_by.append(col_ref)

    if not measure.is_aggregation:
        numeric_value = _convert_to_numeric(dedup_subquery.c.raw_measure)

        avg_measure = func.avg(numeric_value)
        count_measure = func.count(numeric_value)
        stddev_measure = func.stddev(numeric_value)

        # Calculate confidence interval: 1.96 * stddev / sqrt(n)
        # Only calculate CI when we have more than 1 observation and stddev is not null
        ci_measure = case(
            (
                func.coalesce(count_measure, 0) > 1,
                1.96 * func.coalesce(stddev_measure, 0) / func.sqrt(count_measure),
            ),
            else_=0,
        )

        outer_select.append(avg_measure.label("measure_value"))  # type: ignore[arg-type]
        outer_select.append(count_measure.label("measure_count"))  # type: ignore[arg-type]
        outer_select.append(ci_measure.label("measure_ci"))  # type: ignore[arg-type]
    else:
        # Reconstruct aggregate
        if measure.expression.name and measure.expression.name.lower() == "count":
            if len(_extract_constituent_fields(measure.expression)) > 0:
                constituent = dedup_subquery.c.measure_field_0
                reconstructed = func.count(constituent)
            else:
                reconstructed = func.count()
        else:
            raise ChartSQLValidationError(f"Unsupported aggregate: {measure.expression.name}")
        outer_select.append(reconstructed.label("measure_value"))  # type: ignore[arg-type]

    query = select(*outer_select).select_from(dedup_subquery)  # type: ignore[arg-type]
    if outer_group_by:
        query = query.group_by(*outer_group_by).order_by(*outer_group_by)  # type: ignore[arg-type]

    # Filter out rows where any dimension is null
    if dimensions:
        null_filters = [dedup_subquery.c[dim.key].isnot(None) for dim in dimensions]
        query = query.where(and_(*null_filters))

    return query


def generate_chart_query(
    dimensions: List["ChartDimension"],
    measure: "ChartDimension",
    normalize_by_run: bool,
    rubric_filter: Optional[str],
    runs_filter: Optional[ComplexFilter],
    visible_collection_ids: List[str],
) -> Select[Any]:
    """Generate SQL query for chart data using ChartDimension objects.

    Args:
        dimensions: List of ChartDimension objects for grouping
        measure: ChartDimension object for the measure
        normalize_by_run: Whether to normalize measures by run count
        rubric_filter: Optional rubric ID filter
        visible_collection_ids: List of collection IDs to include

    Returns:
        Complete SQL query string

    Raises:
        ChartSQLValidationError: If any parameters fail validation
    """

    if not visible_collection_ids:
        raise ChartSQLValidationError("At least one collection ID must be provided")

    # Deduplicate dimensions; SQL will get mad if we try to use the same label twice
    seen: set[str] = set()
    unique_dimensions = [dim for dim in dimensions if dim.key not in seen and not seen.add(dim.key)]

    try:
        # Stage 1: Build the base query with static filters
        base_query = _build_base_query(visible_collection_ids, runs_filter, rubric_filter)

        # Stage 2: Apply DISTINCT de-duplication
        dedup_subquery = _deduplicate(base_query, unique_dimensions, measure)

        # Stage 3: Apply outer aggregation
        final_query = _aggregate(dedup_subquery, unique_dimensions, measure)

        # Apply run normalization if requested
        if normalize_by_run:
            final_query = _apply_run_normalization(
                final_query, unique_dimensions, visible_collection_ids
            )

        return final_query

    except Exception as e:
        logger.error(f"Error building chart query: {str(e)}", exc_info=True)
        raise ChartSQLValidationError(f"Failed to build chart query: {str(e)}") from e
