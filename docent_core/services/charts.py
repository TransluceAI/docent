from dataclasses import dataclass
from enum import Enum
from typing import Any, List
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Numeric

from docent._log_util import get_logger
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.filters import ComplexFilter
from docent_core._db_service.schemas.chart import SQLAChart
from docent_core._db_service.schemas.rubric import (
    SQLAJudgeResult,
    SQLAJudgeResultCentroid,
    SQLARubric,
    SQLARubricCentroid,
)
from docent_core._db_service.schemas.tables import (
    SQLAAgentRun,
)
from docent_core._db_service.service import MonoService

logger = get_logger(__name__)


class MetadataFieldType(str, Enum):
    """Data types for fields in metadata JSON objects."""

    NUMERIC = "numeric"
    TEXT = "text"
    BOOLEAN = "boolean"


@dataclass
class ChartKeys:
    """Container for metadata/score keys in a collection that can be used in charts."""

    metadata_keys: List[tuple[str, MetadataFieldType]]
    score_keys: List[str]


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
    rubric_filter: str | None
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
            rubric_filter=chart.rubric_filter,
            chart_type=chart.chart_type,
            runs_filter=chart.runs_filter,
        )


class ChartDimension(BaseModel):
    key: str
    name: str
    short_name: str | None = None
    expression: Any = Field(exclude=True)  # SQLAlchemy expression, excluded from JSON
    is_aggregation: bool = Field(
        default=False, exclude=True
    )  # Whether this represents an aggregate measure
    extra: dict[str, Any] = {}

    def __init__(
        self,
        key: str,
        name: str | None = None,
        short_name: str | None = None,
        expression: Any = None,
        is_aggregation: bool = False,
        **extra: Any,
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
            is_aggregation=is_aggregation,
            extra=extra,
        )

        # Validate that expression is provided for new instances
        if expression is None:
            raise ValueError(
                f"ChartDimension '{key}' must have an expression. Use create_field() or create_json_field() instead."
            )

    @classmethod
    def create_json_field(
        cls,
        base_field: str,
        json_path: str,
        name: str | None = None,
        short_name: str | None = None,
        data_type: MetadataFieldType | None = None,
    ):
        """Create a ChartDimension for JSON field access (supports nested paths)."""
        # Handle nested JSON paths like 'scores.correct' -> ['scores', 'correct']
        path_parts = json_path.split(".")

        # Get the base SQLAlchemy column
        base_expressions = {
            "ar.metadata_json": SQLAAgentRun.metadata_json,
        }

        if base_field not in base_expressions:
            raise ValueError(f"Unknown base field: {base_field}")

        base_expr = base_expressions[base_field]

        # Build the JSON path expression
        if len(path_parts) == 1:
            # Simple case: ar.metadata_json->>'key'
            expression = base_expr.op("->>")(path_parts[0])
            key = f"{base_field}->>{path_parts[0]}"
        else:
            # Nested case: ar.metadata_json->'scores'->>'correct'
            # First navigate to the nested object
            nested_expr = base_expr
            for part in path_parts[:-1]:
                nested_expr = nested_expr.op("->")(part)

            # Then extract the final value
            expression = nested_expr.op("->>")(path_parts[-1])

            # Give it a key that resembles the SQL expression
            parts_except_last = path_parts[:-1]
            last_part = path_parts[-1]
            parts_except_last_joined = "->".join(parts_except_last)
            key = f"{base_field}->{parts_except_last_joined}->>{last_part}"

        if data_type == MetadataFieldType.NUMERIC:
            expression = expression.cast(Numeric)  # type: ignore

        return cls(
            key=key,
            name=name or f"Metadata: {json_path}",
            short_name=short_name,
            expression=expression,
            is_aggregation=False,
            data_type=data_type,
            metadata_key=json_path,
        )


static_dimensions = [
    ChartDimension(
        key="rc.centroid",
        expression=func.split_part(SQLARubricCentroid.centroid, ":", 1),
        name="Rubric centroid",
        short_name="Centroid",
    ),
    ChartDimension(
        key="r.high_level_description",
        expression=SQLARubric.high_level_description,
        name="Rubric description",
        short_name="Rubric",
    ),
]
static_measures = [
    ChartDimension(
        key="COUNT(ar.id)",
        expression=func.count(SQLAAgentRun.id),
        name="Count runs",
        short_name="Runs",
        is_aggregation=True,
    ),
    ChartDimension(
        key="COUNT(jr.id)",
        expression=func.count(SQLAJudgeResult.id),
        name="Count judge results",
        short_name="Judge results",
        is_aggregation=True,
    ),
    ChartDimension(
        key="COUNT(jrc.id)",
        expression=func.count(SQLAJudgeResultCentroid.id),
        name="Count centroid assignments",
        short_name="Centroid assignments",
        is_aggregation=True,
    ),
    ChartDimension(
        key="COUNT(jrc.id)_normalize_by_run",
        expression=func.count(SQLAJudgeResultCentroid.id),
        name="Average centroid assignments per run",
        short_name="Avg. centroid assignments per run",
        normalize_by_run=True,
        is_aggregation=True,
    ),
    ChartDimension(
        key="COUNT(jr.id)_normalize_by_run",
        expression=func.count(SQLAJudgeResult.id),
        name="Average judge results per run",
        short_name="Avg. judge results per run",
        normalize_by_run=True,
        is_aggregation=True,
    ),
    ChartDimension(
        key="COUNT(ar.id)_normalize_by_run",
        expression=func.count(SQLAAgentRun.id),
        name="Fraction of runs",
        short_name="Fraction of runs",
        normalize_by_run=True,
        is_aggregation=True,
    ),
]


class ChartsService:
    def __init__(self, session: AsyncSession, service: MonoService):
        self.session = session
        self.service = service
        # Request-scoped cache for chart keys
        self._chart_keys_cache: dict[str, ChartKeys] = {}

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
            rubric_filter=chart_spec.rubric_filter,
            runs_filter=chart_spec.runs_filter,
            chart_type=chart_spec.chart_type,
        )

    async def get_charts(self, ctx: ViewContext) -> list[ChartSpec]:
        """Get all charts for a collection."""
        result = await self.session.execute(
            select(SQLAChart).where(SQLAChart.collection_id == ctx.collection_id)
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
        rubric_filter: str | None = None,
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
            rubric_filter=rubric_filter,
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

    async def _fetch_metadata_keys_from_db(
        self, collection_id: str
    ) -> List[tuple[str, MetadataFieldType]]:
        """Fetch metadata keys directly from database."""
        query = text(
            """
            SELECT
                key,
                CASE
                    WHEN bool_and(jsonb_typeof(value) = 'number') THEN 'numeric'
                    WHEN bool_and(jsonb_typeof(value) = 'boolean') THEN 'boolean'
                    ELSE 'text'
                END as data_type
            FROM (
                SELECT
                    key,
                    value
                FROM agent_runs,
                LATERAL jsonb_each(metadata_json)
                WHERE metadata_json IS NOT NULL
                AND metadata_json != 'null'::jsonb
                AND metadata_json != '{}'::jsonb
                AND collection_id = :collection_id
            ) subquery
            WHERE key != 'scores'
            AND jsonb_typeof(value) != 'object'
            GROUP BY key
            ORDER BY key
            """
        )

        try:
            result = await self.session.execute(query, {"collection_id": collection_id})
            excluded = {"_field_descriptions", "allow_fields_without_descriptions"}
            return [
                (row.key, MetadataFieldType(row.data_type))
                for row in result
                if row.key not in excluded
            ]
        except Exception as e:
            logger.error(f"Failed to get metadata keys for collection {collection_id}: {str(e)}")
            return []

    async def _fetch_score_keys_from_db(self, collection_id: str) -> List[str]:
        """Fetch score keys directly from database."""

        # Only include score keys whose values are numeric or boolean across *all* occurrences
        # in the collection. This is enforced by checking the jsonb_typeof for every value
        # associated with each key and requiring that it is always either "number" or "boolean".
        query = text(
            """
            SELECT key
            FROM (
                SELECT key, value
                FROM agent_runs
                CROSS JOIN LATERAL jsonb_each(metadata_json->'scores') AS t(key, value)
                WHERE metadata_json IS NOT NULL
                AND metadata_json != 'null'::jsonb
                AND metadata_json->'scores' IS NOT NULL
                AND metadata_json->'scores' != 'null'::jsonb
                AND collection_id = :collection_id
            ) subquery
            GROUP BY key
            HAVING bool_and(jsonb_typeof(value) IN ('number', 'boolean', 'null'))
            ORDER BY key
            """
        )

        try:
            result = await self.session.execute(query, {"collection_id": collection_id})
            return [row.key for row in result]
        except Exception as e:
            logger.error(f"Failed to get score keys for collection {collection_id}: {str(e)}")
            return []

    async def _get_chart_keys(self, ctx: ViewContext) -> ChartKeys:
        """Get all chart keys for a collection with request-scoped caching."""
        if ctx.collection_id in self._chart_keys_cache:
            return self._chart_keys_cache[ctx.collection_id]

        metadata_keys = await self._fetch_metadata_keys_from_db(ctx.collection_id)
        score_keys = await self._fetch_score_keys_from_db(ctx.collection_id)

        chart_keys = ChartKeys(metadata_keys=metadata_keys, score_keys=score_keys)
        self._chart_keys_cache[ctx.collection_id] = chart_keys
        return chart_keys

    async def get_available_dimensions(self, ctx: ViewContext) -> List[ChartDimension]:
        """Get available dimensions for a table type, including dynamic metadata fields."""
        # Add dynamic metadata fields with detected data types
        chart_keys = await self._get_chart_keys(ctx)
        dynamic_metadata: List[ChartDimension] = []
        for key, data_type in chart_keys.metadata_keys:
            dimension = ChartDimension.create_json_field(
                "ar.metadata_json",
                key,
                data_type=data_type,
                short_name=key,
            )
            dynamic_metadata.append(dimension)

        return static_dimensions + dynamic_metadata

    async def get_available_measures(self, ctx: ViewContext) -> List[ChartDimension]:
        """Get available measures for a table type, including dynamic score fields."""
        chart_keys = await self._get_chart_keys(ctx)
        dynamic_scores: List[ChartDimension] = []
        for key in chart_keys.score_keys:
            dimension = ChartDimension.create_json_field(
                "ar.metadata_json",
                f"scores.{key}",
                name=f"Score: {key}",
                short_name=key,
            )
            dynamic_scores.append(dimension)

        return static_measures + dynamic_scores

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
        available_dimensions = await self.get_available_dimensions(ctx)
        available_dimension_keys = [dimension.key for dimension in available_dimensions]
        available_metadata_keys = [
            dimension.key
            for dimension in available_dimensions
            if dimension.extra.get("metadata_key")
        ]

        if series_key not in available_dimension_keys:
            series_key = None

        if x_key not in available_dimension_keys:
            if available_metadata_keys:
                x_key = available_metadata_keys[0]
            elif available_dimensions:
                x_key = available_dimension_keys[0]
            else:
                x_key = None

        available_measures = await self.get_available_measures(ctx)
        available_measure_keys = [measure.key for measure in available_measures]

        if y_key not in available_measure_keys:
            if available_measures:
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
        available_dimensions = await self.get_available_dimensions(ctx)
        for dimension in available_dimensions:
            if dimension.key == key:
                return dimension
        return None

    async def _get_measure_by_key(self, ctx: ViewContext, key: str) -> ChartDimension | None:
        """Get a ChartDimension by key, searching both static and dynamic measures."""
        available_measures = await self.get_available_measures(ctx)
        for measure in available_measures:
            if measure.key == key:
                return measure
        return None

    async def get_chart_data(self, ctx: ViewContext, chart: ChartSpec) -> dict[str, Any]:
        """Get chart data (binStats) for a specific chart."""
        # Import here to avoid circular imports
        from docent_core._db_service.chart_sql import generate_chart_query

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
            normalize_by_run=measure_dimension.extra.get("normalize_by_run", False),
            rubric_filter=chart.rubric_filter,
            runs_filter=chart.runs_filter,
            visible_collection_ids=[ctx.collection_id],
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

            # Determine n value based on measure type
            should_normalize = measure_dimension.extra.get("normalize_by_run", False)

            if should_normalize or measure_count is not None:
                # For normalized measures or averaged measures, use the count
                n_value = int(measure_count) if measure_count is not None else None
            else:
                # Default fallback
                n_value = None

            # Create TaskStats-like structure
            bin_stats[bin_key] = {
                "mean": float(measure_value) if measure_value is not None else None,
                "ci": float(measure_ci) if measure_ci is not None else None,
                "n": n_value,
            }

        return {
            "request_type": "comb_stats",
            "result": {
                "binStats": bin_stats,
            },
        }
