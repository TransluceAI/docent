from dataclasses import dataclass
from enum import Enum
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Numeric

from docent._log_util import get_logger
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.filters import ComplexFilter
from docent_core.docent.db.schemas.chart import SQLAChart
from docent_core.docent.db.schemas.rubric import (
    SQLAJudgeResult,
    SQLARubric,
)
from docent_core.docent.db.schemas.tables import (
    SQLAAgentRun,
)

logger = get_logger(__name__)


class ChartSpec(BaseModel):
    """Response model for chart data, matching TypeScript ChartSpec interface."""

    id: str
    name: str
    series_key: str | None
    x_key: str | None
    y_key: str | None
    x_label: str | None = None
    y_label: str | None = None
    series_label: str | None = None
    runs_filter: ComplexFilter | None
    chart_type: str

    @classmethod
    def from_sqla_chart(cls, chart: SQLAChart) -> "ChartSpec":
        """Create ChartSpec from SQLAlchemy model without labels."""
        return cls(
            id=chart.id,
            name=chart.name,
            series_key=chart.series_key,
            x_key=chart.x_key,
            y_key=chart.y_key,
            chart_type=chart.chart_type,
            runs_filter=chart.runs_filter,
        )


class ChartDimensionDataType(Enum):
    """
    The data type of a chart dimension determines:
    - Whether we cast x/series dimensions to numeric in SQL for sort-by-value (numeric only)
    - Whether a dimension can go on the y-axis (numeric, numeric_or_boolean)

    The numeric_or_boolean type exists because types can be mixed together in run metadata and we can handle a combo of numbers and booleans on the y-axis.
    """

    # Numeric values are cast
    NUMERIC = "numeric"
    NUMERIC_OR_BOOLEAN = "numeric_or_boolean"
    TEXT = "text"

    @classmethod
    def from_json_schema_type(cls, json_schema_type: str) -> "ChartDimensionDataType":
        if json_schema_type in ("number", "integer"):
            return cls.NUMERIC
        elif json_schema_type == "boolean":
            return cls.NUMERIC_OR_BOOLEAN
        else:
            return cls.TEXT

    def is_valid_measure(self) -> bool:
        return self in (self.NUMERIC, self.NUMERIC_OR_BOOLEAN)


class ChartDimensionKind(Enum):
    RUN_METADATA = "run_metadata"
    JUDGE_OUTPUT = "judge_output"
    AGGREGATION = "aggregation"


class ChartDimension(BaseModel):
    key: str
    name: str
    short_name: str | None = None
    expression: ColumnElement[Any] = Field(
        exclude=True
    )  # SQLAlchemy expression, excluded from JSON
    data_type: ChartDimensionDataType = Field(default=ChartDimensionDataType.TEXT)
    kind: ChartDimensionKind

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        key: str,
        name: str | None = None,
        short_name: str | None = None,
        expression: Any = None,
        **kwargs: Any,
    ):
        if name is None:
            name = key
        if short_name is None:
            short_name = name

        super().__init__(
            key=key,
            name=name,
            short_name=short_name,
            expression=expression,
            **kwargs,
        )

        # Validate that expression is provided for new instances
        if expression is None:
            raise ValueError(
                f"ChartDimension '{key}' must have an expression. Use create_field() or create_json_field() instead."
            )


def _build_json_expr_key_shortname(
    base_expr: Any,
    json_path: str,
    key_prefix: str,
    data_type: ChartDimensionDataType,
):
    path_parts = json_path.split(".")

    if len(path_parts) == 1:
        expression = base_expr.op("->>")(path_parts[0])
        key = f"{key_prefix}->>{path_parts[0]}"
    else:
        nested_expr = base_expr
        for part in path_parts[:-1]:
            nested_expr = nested_expr.op("->")(part)
        expression = nested_expr.op("->>")(path_parts[-1])
        parts_except_last = path_parts[:-1]
        last_part = path_parts[-1]
        parts_except_last_joined = "->".join(parts_except_last)
        key = f"{key_prefix}->{parts_except_last_joined}->>{last_part}"

    if data_type == ChartDimensionDataType.NUMERIC:
        expression = expression.cast(Numeric)

    short_name = path_parts[-1]
    return expression, key, short_name


class RunMetadataDimension(ChartDimension):
    json_path: str
    kind: ChartDimensionKind = ChartDimensionKind.RUN_METADATA

    def __init__(
        self,
        json_path: str,
        name: str,
        data_type: ChartDimensionDataType = ChartDimensionDataType.TEXT,
    ):
        expression, key, short_name = _build_json_expr_key_shortname(
            SQLAAgentRun.metadata_json,
            json_path,
            "ar.metadata_json",
            data_type,
        )

        super().__init__(
            key=key,
            name=name,
            short_name=short_name,
            expression=expression,
            json_path=json_path,
            data_type=data_type,
        )


class JudgeOutputDimension(ChartDimension):
    kind: ChartDimensionKind = ChartDimensionKind.JUDGE_OUTPUT
    judge_id: str
    judge_name: str
    judge_version: int

    def __init__(
        self,
        *,
        judge_id: str,
        judge_name: str,
        judge_version: int,
        name: str,
        json_path: str,
        data_type: ChartDimensionDataType = ChartDimensionDataType.TEXT,
        **kwargs: Any,
    ):
        # Include rubric/judge ID in the key prefix so fields from different
        # rubrics don't collide (e.g., two rubrics both with "score").
        # Keep the prefix starting with "jr.output" for frontend grouping.
        key_prefix = f"jr.output.{judge_id}"

        expression, key, short_name = _build_json_expr_key_shortname(
            SQLAJudgeResult.output,
            json_path,
            key_prefix,
            data_type,
        )

        super().__init__(
            key=key,
            name=name or f"Output: {json_path}",
            short_name=short_name,
            expression=expression,
            data_type=data_type,
            judge_id=judge_id,
            judge_name=judge_name,
            judge_version=judge_version,
            **kwargs,
        )


class CountRunDimension(ChartDimension):
    kind: ChartDimensionKind = ChartDimensionKind.AGGREGATION

    def __init__(
        self,
        **kwargs: Any,
    ):
        super().__init__(
            data_type=ChartDimensionDataType.NUMERIC,
            **kwargs,
        )


@dataclass
class ChartKeysCache:
    dimensions: list[ChartDimension]
    measures: list[ChartDimension]


static_measures = [
    CountRunDimension(
        key="COUNT(ar.id)",
        expression=func.count(SQLAAgentRun.id),
        name="Count runs",
        short_name="Runs",
    ),
]


@dataclass
class AvailableKeysCache:
    dimensions: list[ChartDimension]
    measures: list[ChartDimension]


class ChartsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        # Request-scoped cache for available dimensions + measures
        self._available_keys_cache: dict[str, AvailableKeysCache] = {}

    async def _populate_chart_labels(self, ctx: ViewContext, chart_spec: ChartSpec) -> ChartSpec:
        """Populate x_label, y_label, and series_label from ChartDimension short_name."""
        # Get labels for dimensions
        x_label = None
        y_label = None
        series_label = None

        if chart_spec.x_key:
            x_dimension = await self._get_dimension_by_key(ctx, chart_spec.x_key)
            x_label = x_dimension.short_name if x_dimension else chart_spec.x_key

        if chart_spec.y_key:
            y_dimension = await self._get_measure_by_key(ctx, chart_spec.y_key)
            y_label = y_dimension.short_name if y_dimension else chart_spec.y_key

        if chart_spec.series_key:
            series_dimension = await self._get_dimension_by_key(ctx, chart_spec.series_key)
            series_label = (
                series_dimension.short_name if series_dimension else chart_spec.series_key
            )

        # Return new ChartSpec with labels populated
        return ChartSpec(
            id=chart_spec.id,
            name=chart_spec.name,
            series_key=chart_spec.series_key,
            x_key=chart_spec.x_key,
            y_key=chart_spec.y_key,
            x_label=x_label,
            y_label=y_label,
            series_label=series_label,
            runs_filter=chart_spec.runs_filter,
            chart_type=chart_spec.chart_type,
        )

    async def get_charts(self, ctx: ViewContext) -> list[ChartSpec]:
        """Get all charts for a collection."""
        result = await self.session.execute(
            select(SQLAChart)
            .where(SQLAChart.collection_id == ctx.collection_id)
            .order_by(SQLAChart.created_at.asc())
        )
        charts = list(result.scalars().all())

        # Convert to ChartSpec and populate labels
        chart_specs: list[ChartSpec] = []
        for chart in charts:
            chart_spec = ChartSpec.from_sqla_chart(chart)
            chart_spec_with_labels = await self._populate_chart_labels(ctx, chart_spec)
            chart_specs.append(chart_spec_with_labels)

        return chart_specs

    async def create_chart(
        self,
        ctx: ViewContext,
        name: str | None = None,
        series_key: str | None = None,
        x_key: str | None = None,
        y_key: str | None = None,
        chart_type: str = "bar",
    ) -> str:
        """Create a new chart and return its ID."""
        chart_id = str(uuid4())

        if ctx.user is None:
            raise PermissionError("User must be authenticated to create charts")

        corrected_x_key, corrected_series_key, corrected_y_key = (
            await self._validate_and_correct_chart_keys(ctx, x_key, series_key, y_key)
        )

        # Generate default name if not provided
        if name is None:
            result = await self.session.execute(
                select(SQLAChart.name).where(SQLAChart.collection_id == ctx.collection_id)
            )
            existing_names = [row[0] for row in result.fetchall()]

            # Find the highest number among existing "Chart X" names
            max_num = 0
            for existing_name in existing_names:
                if existing_name.startswith("Chart "):
                    try:
                        num = int(existing_name[6:])  # Extract number after "Chart "
                        max_num = max(max_num, num)
                    except ValueError:
                        continue

            name = f"Chart {max_num + 1}"

        chart = SQLAChart(
            id=chart_id,
            collection_id=ctx.collection_id,
            name=name,
            series_key=corrected_series_key,
            x_key=corrected_x_key,
            y_key=corrected_y_key,
            chart_type=chart_type,
            created_by=ctx.user.id,
        )
        self.session.add(chart)

        return chart_id

    async def update_chart(
        self,
        ctx: ViewContext,
        chart_id: str,
        updates: dict[str, str | None],
    ) -> None:
        """Update an existing chart with the provided parameters.

        Only updates fields that are present in the updates dictionary.
        Validates and auto-corrects chart keys.
        """
        result = await self.session.execute(select(SQLAChart).where(SQLAChart.id == chart_id))
        chart = result.scalar_one_or_none()

        if not chart:
            raise ValueError(f"Chart with ID {chart_id} not found")

        # Get current values, using updates if provided, otherwise existing values
        current_x_key = updates.get("x_key", chart.x_key)
        current_series_key = updates.get("series_key", chart.series_key)
        current_y_key = updates.get("y_key", chart.y_key)

        corrected_x_key, corrected_series_key, corrected_y_key = (
            await self._validate_and_correct_chart_keys(
                ctx, current_x_key, current_series_key, current_y_key
            )
        )

        # Update the corrections in the updates dict
        updates["x_key"] = corrected_x_key
        updates["series_key"] = corrected_series_key
        updates["y_key"] = corrected_y_key

        # Only update fields that are present in the updates dictionary
        if updates:
            await self.session.execute(
                update(SQLAChart).where(SQLAChart.id == chart_id).values(**updates)
            )

    async def delete_chart(self, ctx: ViewContext, chart_id: str):
        """Delete a chart.

        Only the creator of the chart can delete it.
        """
        result = await self.session.execute(select(SQLAChart).where(SQLAChart.id == chart_id))
        chart = result.scalar_one_or_none()

        if not chart:
            raise ValueError(f"Chart with ID {chart_id} not found")

        await self.session.execute(delete(SQLAChart).where(SQLAChart.id == chart_id))

    async def _fetch_run_metadata_chart_keys_from_db(
        self, collection_id: str
    ) -> list[ChartDimension]:
        """Fetch metadata keys (including nested) and measure-eligible numeric keys in one query.

        Dimension data types allow nulls when determining numeric/boolean types.
        Measure eligibility is true if all occurrences are number/boolean/null.
        """
        query = text(
            """
            WITH RECURSIVE json_paths AS (
                -- Base case: top-level keys
                SELECT
                    key AS path,
                    value,
                    id AS agent_run_id
                FROM agent_runs
                CROSS JOIN LATERAL jsonb_each(metadata_json) AS t(key, value)
                WHERE metadata_json IS NOT NULL
                AND metadata_json != 'null'::jsonb
                AND metadata_json != '{}'::jsonb
                AND collection_id = :collection_id

                UNION ALL

                -- Recursive case: nested keys
                SELECT
                    jp.path || '.' || nested.key AS path,
                    nested.value,
                    jp.agent_run_id
                FROM json_paths jp
                CROSS JOIN LATERAL jsonb_each(jp.value) AS nested(key, value)
                WHERE jsonb_typeof(jp.value) = 'object'
            ),
            total_runs AS (
                SELECT COUNT(id)::int AS total_runs
                FROM agent_runs
                WHERE collection_id = :collection_id
            ),
            agg AS (
                SELECT
                    path,
                    COUNT(DISTINCT agent_run_id) FILTER (WHERE jsonb_typeof(value) <> 'null') AS present_count,
                    CASE
                        WHEN bool_and(jsonb_typeof(value) = 'null') THEN 'null'
                        WHEN bool_and(jsonb_typeof(value) IN ('number','null')) THEN 'numeric'
                        WHEN bool_and(jsonb_typeof(value) IN ('number','boolean','null')) THEN 'numeric_or_boolean'
                        WHEN bool_and(jsonb_typeof(value) IN ('number','boolean','string','null')) THEN 'text'
                        ELSE 'unknown'
                    END AS data_type
                FROM json_paths
                WHERE NOT (
                    path IN ('_field_descriptions', 'allow_fields_without_descriptions')
                    OR path LIKE '_field_descriptions.%'
                    OR path LIKE 'allow_fields_without_descriptions.%'
                )
                GROUP BY path
            )
            SELECT
                agg.path AS path,
                agg.data_type AS data_type
            FROM agg, total_runs
            WHERE (agg.present_count::numeric / NULLIF(total_runs.total_runs::numeric, 0)) >= :min_presence_ratio
            ORDER BY agg.path
            """
        )

        try:
            result = await self.session.execute(
                query,
                {
                    "collection_id": collection_id,
                    "min_presence_ratio": 0.5,
                },
            )

            rows = list(result)

            dimensions: list[ChartDimension] = []
            for row in rows:
                if row.data_type == "numeric":
                    dt = ChartDimensionDataType.NUMERIC
                elif row.data_type == "numeric_or_boolean":
                    dt = ChartDimensionDataType.NUMERIC_OR_BOOLEAN
                elif row.data_type == "text":
                    dt = ChartDimensionDataType.TEXT
                else:
                    continue

                dimensions.append(
                    RunMetadataDimension(
                        json_path=row.path,
                        name=row.path,
                        data_type=dt,
                    )
                )

            return dimensions
        except Exception as e:
            logger.error(f"Failed to get chart keys for collection {collection_id}: {str(e)}")
            return []

    async def _fetch_rubric_chart_keys(self, collection_id: str) -> dict[str, list[ChartDimension]]:
        dimensions: list[ChartDimension] = []
        measures: list[ChartDimension] = []

        # Fetch latest version of each rubric for the collection
        result = await self.session.execute(
            select(SQLARubric).where(SQLARubric.collection_id == collection_id)
        )
        rubrics = list(result.scalars().all())
        latest_by_id: dict[str, SQLARubric] = {}
        for r in rubrics:
            existing = latest_by_id.get(r.id)
            if existing is None or r.version > existing.version:
                latest_by_id[r.id] = r

        def _traverse_rubric_schema(
            rubric: SQLARubric,
            schema: dict[str, Any],
            prefix: str = "",
        ):
            schema_type = schema.get("type")

            if "properties" in schema:
                props_any = schema.get("properties")
                props = (
                    cast(dict[str, dict[str, Any]], props_any)
                    if isinstance(props_any, dict)
                    else {}
                )
                for key, subschema in props.items():
                    new_prefix = f"{prefix}.{key}" if prefix else key
                    _traverse_rubric_schema(rubric, subschema, new_prefix)
            elif schema_type in ("integer", "number", "boolean", "string"):
                json_path = prefix
                data_type = ChartDimensionDataType.from_json_schema_type(schema_type)

                if data_type.is_valid_measure():
                    measures.append(
                        JudgeOutputDimension(
                            judge_id=rubric.id,
                            judge_name=rubric.short_name,
                            judge_version=rubric.version,
                            json_path=json_path,
                            name=json_path,
                            data_type=data_type,
                        )
                    )

                is_valid_dimension = "enum" in schema or schema_type in (
                    "integer",
                    "number",
                    "boolean",
                )
                if is_valid_dimension:
                    dimensions.append(
                        JudgeOutputDimension(
                            judge_id=rubric.id,
                            judge_name=rubric.short_name,
                            judge_version=rubric.version,
                            json_path=json_path,
                            name=json_path,
                            data_type=data_type,
                        )
                    )
            elif schema_type == "array":
                return

        for rubric in latest_by_id.values():
            _traverse_rubric_schema(rubric, rubric.output_schema)

        return {
            "dimensions": dimensions,
            "measures": measures,
        }

    async def get_available_dimensions_and_measures(self, ctx: ViewContext) -> AvailableKeysCache:
        """Get available dimensions and measures for a table type, including metadata and rubric fields."""
        if ctx.collection_id in self._available_keys_cache:
            return self._available_keys_cache[ctx.collection_id]

        metadata_dims = await self._fetch_run_metadata_chart_keys_from_db(ctx.collection_id)
        rubric_keys = await self._fetch_rubric_chart_keys(ctx.collection_id)
        metadata_measures = [key for key in metadata_dims if key.data_type.is_valid_measure()]

        self._available_keys_cache[ctx.collection_id] = AvailableKeysCache(
            dimensions=metadata_dims + rubric_keys["dimensions"],
            measures=static_measures + metadata_measures + rubric_keys["measures"],
        )
        return self._available_keys_cache[ctx.collection_id]

    async def _validate_and_correct_chart_keys(
        self,
        ctx: ViewContext,
        x_key: str | None,
        series_key: str | None,
        y_key: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Validate chart keys against the base table and auto-correct invalid ones.

        Returns corrected (x_key, series_key, y_key) tuple.
        """
        # Get available fields for this table type
        available = await self.get_available_dimensions_and_measures(ctx)
        available_dimension_keys = [dimension.key for dimension in available.dimensions]
        available_metadata_keys = [
            dimension.key
            for dimension in available.dimensions
            if isinstance(dimension, RunMetadataDimension)
        ]

        if series_key not in available_dimension_keys:
            series_key = None

        if x_key not in available_dimension_keys:
            if available_metadata_keys:
                x_key = available_metadata_keys[0]
            elif available.dimensions:
                x_key = available_dimension_keys[0]
            else:
                x_key = None

        available_measure_keys = [measure.key for measure in available.measures]

        if y_key not in available_measure_keys:
            if available.measures:
                y_key = available_measure_keys[0]
            else:
                y_key = None

        return x_key, series_key, y_key

    async def get_chart(self, ctx: ViewContext, chart_id: str) -> ChartSpec | None:
        """Get a specific chart by ID."""
        result = await self.session.execute(select(SQLAChart).where(SQLAChart.id == chart_id))
        chart = result.scalar_one_or_none()

        if not chart:
            return None

        chart_spec = ChartSpec.from_sqla_chart(chart)
        return await self._populate_chart_labels(ctx, chart_spec)

    async def _get_dimension_by_key(self, ctx: ViewContext, key: str) -> ChartDimension | None:
        """Get a ChartDimension by key, searching both static and dynamic dimensions."""
        available_dimensions = (await self.get_available_dimensions_and_measures(ctx)).dimensions
        for dimension in available_dimensions:
            if dimension.key == key:
                return dimension
        return None

    async def _get_measure_by_key(self, ctx: ViewContext, key: str) -> ChartDimension | None:
        """Get a ChartDimension by key, searching both static and dynamic measures."""
        available_measures = (await self.get_available_dimensions_and_measures(ctx)).measures
        for measure in available_measures:
            if measure.key == key:
                return measure
        return None

    async def get_chart_data(self, ctx: ViewContext, chart: ChartSpec) -> dict[str, Any]:
        """Get chart data (binStats) for a specific chart."""
        # Import here to avoid circular imports
        from docent_core.docent.db.chart_sql import generate_chart_query

        # Extract dimensions and measures from chart specification
        chart_dimensions: list[ChartDimension] = []
        if chart.x_key:
            x_dimension = await self._get_dimension_by_key(ctx, chart.x_key)
            if x_dimension:
                chart_dimensions.append(x_dimension)
        if chart.series_key:
            series_dimension = await self._get_dimension_by_key(ctx, chart.series_key)
            if series_dimension:
                chart_dimensions.append(series_dimension)

        # Get measure dimension
        if not chart.y_key:
            raise ValueError("No y dimension specified for chart")
        measure_dimension = await self._get_measure_by_key(ctx, chart.y_key)
        if not measure_dimension:
            raise ValueError(f"No measure dimension found for key: {chart.y_key}")

        # Generate SQL query for chart data
        query = generate_chart_query(
            dimensions=chart_dimensions,
            measure=measure_dimension,
            runs_filter=chart.runs_filter,
            collection_id=ctx.collection_id,
        )

        # Execute the query
        result = await self.session.execute(query)
        rows = result.fetchall()

        # Convert results to binStats format
        bin_stats: dict[str, Any] = {}

        for row in rows:
            # Build the bin key from dimensions
            bin_key_parts: list[str] = []
            for i, dim in enumerate(chart_dimensions):
                if hasattr(row, dim.key):
                    bin_key_parts.append(f"{dim.key},{getattr(row, dim.key)}")
                else:
                    # Fallback: use the index
                    bin_key_parts.append(f"{dim.key},{row[i]}")

            bin_key = (
                "|".join(bin_key_parts)
                if len(bin_key_parts) > 1
                else bin_key_parts[0] if bin_key_parts else "default"
            )

            # Get the measure value
            measure_value = (
                getattr(row, "measure_value", None) if hasattr(row, "measure_value") else row[-1]
            )

            # Get the count value based on measure type
            measure_count = (
                getattr(row, "measure_count", None) if hasattr(row, "measure_count") else None
            )

            # Get the confidence interval value for average-metadata measures
            measure_ci = getattr(row, "measure_ci", None) if hasattr(row, "measure_ci") else None

            # Create TaskStats-like structure
            bin_stats[bin_key] = {
                "mean": float(measure_value) if measure_value is not None else None,
                "ci": float(measure_ci) if measure_ci is not None else None,
                "n": int(measure_count) if measure_count is not None else None,
            }

        return {
            "request_type": "comb_stats",
            "result": {
                "binStats": bin_stats,
            },
        }
