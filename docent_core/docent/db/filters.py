from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, Sequence, Type, Union
from uuid import uuid4

from pydantic import BaseModel, Discriminator, Field, field_validator
from sqlalchemy import (
    Boolean,
    ColumnElement,
    Float,
    String,
    and_,
    case,
    cast,
    func,
    or_,
    select,
    type_coerce,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import aliased

from docent._log_util import get_logger
from docent.judges import ResultType

if TYPE_CHECKING:
    from docent_core.docent.db.schemas.rubric import SQLAJudgeResult
    from docent_core.docent.db.schemas.tables import SQLAAgentRun

logger = get_logger(__name__)


@dataclass(frozen=True)
class FilterJoinSpec:
    """Describes a join that must be applied for filters that reference related tables."""

    alias: Any
    onclause: ColumnElement[bool]


class FilterSQLContext:
    """Tracks join requirements while compiling filters to SQLAlchemy clauses."""

    def __init__(
        self,
        base_table: Type["SQLAAgentRun"],
    ) -> None:
        self._base_table = base_table
        self._rubric_aliases: dict[tuple[str, tuple[str, ...]], FilterJoinSpec] = {}
        self._tag_alias: FilterJoinSpec | None = None
        self._label_aliases: dict[str, FilterJoinSpec] = {}

    def ensure_rubric_join(self, rubric_id: str, json_path: Sequence[str]) -> FilterJoinSpec:
        key = (rubric_id, tuple(json_path))
        spec = self._rubric_aliases.get(key)
        if spec is not None:
            return spec

        from docent_core.docent.db.schemas.rubric import SQLAJudgeResult, SQLARubric

        if not json_path:
            raise ValueError("Rubric filters must include a JSON field path.")

        field_expr = SQLAJudgeResult.output
        for part in json_path[:-1]:
            field_expr = field_expr.op("->")(part)
        field_expr = cast(field_expr.op("->>")(json_path[-1]), String)

        latest_version_subquery = (
            select(func.max(SQLARubric.version))
            .where(
                SQLARubric.id == rubric_id,
                SQLARubric.collection_id == getattr(self._base_table, "collection_id"),
            )
            .correlate(self._base_table)
            .scalar_subquery()
        )

        rubric_counts = (
            select(
                SQLAJudgeResult.agent_run_id.label("agent_run_id"),
                self._base_table.collection_id.label("collection_id"),
                field_expr.label("value"),
                func.count().label("value_count"),
            )
            .select_from(SQLAJudgeResult)
            .join(self._base_table, SQLAJudgeResult.agent_run_id == self._base_table.id)
            .where(
                SQLAJudgeResult.rubric_id == rubric_id,
                SQLAJudgeResult.rubric_version == latest_version_subquery,
                SQLAJudgeResult.result_type == ResultType.DIRECT_RESULT,
            )
            .group_by(
                SQLAJudgeResult.agent_run_id,
                self._base_table.collection_id,
                field_expr,
            )
            .subquery()
        )
        rubric_ranked = select(
            rubric_counts.c.agent_run_id,
            rubric_counts.c.collection_id,
            rubric_counts.c.value.label("rubric_value"),
            func.row_number()
            .over(
                partition_by=(
                    rubric_counts.c.agent_run_id,
                    rubric_counts.c.collection_id,
                ),
                order_by=(
                    rubric_counts.c.value_count.desc(),
                    rubric_counts.c.value.asc().nulls_last(),
                ),
            )
            .label("value_rank"),
        ).subquery()
        rubric_modal = (
            select(
                rubric_ranked.c.agent_run_id,
                rubric_ranked.c.collection_id,
                rubric_ranked.c.rubric_value,
            )
            .where(rubric_ranked.c.value_rank == 1)
            .subquery(f"rubric_value_{len(self._rubric_aliases)}")
        )

        onclause = and_(
            rubric_modal.c.agent_run_id == getattr(self._base_table, "id"),
            rubric_modal.c.collection_id == getattr(self._base_table, "collection_id"),
        )
        spec = FilterJoinSpec(alias=rubric_modal, onclause=onclause)
        self._rubric_aliases[key] = spec
        return spec

    def get_rubric_alias(self, rubric_id: str, json_path: Sequence[str]) -> FilterJoinSpec:
        return self.ensure_rubric_join(rubric_id, json_path)

    def ensure_tag_join(self) -> FilterJoinSpec:
        if self._tag_alias is not None:
            return self._tag_alias

        from docent_core.docent.db.schemas.label import SQLATag

        alias = aliased(SQLATag, name="tag_filter")
        onclause = and_(
            getattr(alias, "agent_run_id") == getattr(self._base_table, "id"),
            getattr(alias, "collection_id") == getattr(self._base_table, "collection_id"),
        )
        self._tag_alias = FilterJoinSpec(alias=alias, onclause=onclause)
        return self._tag_alias

    def get_tag_alias(self) -> FilterJoinSpec:
        return self.ensure_tag_join()

    def ensure_label_join(self, label_set_id: str) -> FilterJoinSpec:
        spec = self._label_aliases.get(label_set_id)
        if spec is not None:
            return spec

        from docent_core.docent.db.schemas.label import SQLALabel

        alias = aliased(SQLALabel, name=f"label_{len(self._label_aliases)}")
        onclause = and_(
            getattr(alias, "agent_run_id") == getattr(self._base_table, "id"),
            getattr(alias, "label_set_id") == label_set_id,
        )
        spec = FilterJoinSpec(alias=alias, onclause=onclause)
        self._label_aliases[label_set_id] = spec
        return spec

    def get_label_alias(self, label_set_id: str) -> FilterJoinSpec:
        return self.ensure_label_join(label_set_id)

    def required_joins(self) -> tuple[FilterJoinSpec, ...]:
        joins: list[FilterJoinSpec] = list(self._rubric_aliases.values())
        if self._tag_alias is not None:
            joins.append(self._tag_alias)
        joins.extend(self._label_aliases.values())
        return tuple(joins)


def safe_bool(col: Any) -> Any:
    """Safely cast a column to boolean using regex validation."""
    return case(
        (cast(col, String).op("~*")("^(true|false|t|f|1|0|yes|no|on|off)$"), cast(col, Boolean)),
        else_=None,
    )


def safe_float(col: Any) -> Any:
    """Safely cast a column to float using regex validation."""
    # SQLAlchemy's cast() returns Cast[Unknown] when col is Any; this is a type stub limitation
    return case(
        (
            cast(col, String).op("~")("^[+-]?(\\d+\\.?\\d*|\\.\\d+)([eE][+-]?\\d+)?$"),
            cast(col, Float),  # pyright: ignore[reportUnknownArgumentType]
        ),
        else_=None,
    )


def safe_text(col: Any) -> Any:
    if hasattr(col, "as_string"):
        try:
            return col.as_string()
        except InvalidRequestError:
            return cast(col, String)
    return cast(col, String)


def _build_null_check_clause(sqla_value: Any, value: str) -> ColumnElement[bool]:
    normalized_value = value.strip().lower()
    if normalized_value == "null":
        return sqla_value.is_(None)
    if normalized_value == "not null":
        return sqla_value.is_not(None)
    raise ValueError("Use 'null' or 'not null' with the 'is' operator")


def apply_comparison(
    sqla_value: Any,
    value: Any,
    op: Literal[">", ">=", "<", "<=", "==", "!=", "~*", "!~*", "is"],
) -> ColumnElement[bool]:
    """Apply a comparison operator to a SQLAlchemy column."""
    if op == "is":
        if not isinstance(value, str):
            raise ValueError("The 'is' operator requires a string value")
        return _build_null_check_clause(sqla_value, value)
    elif op == "==":
        return sqla_value == value
    elif op == "!=":
        return sqla_value != value
    elif op == ">":
        return sqla_value > value
    elif op == ">=":
        return sqla_value >= value
    elif op == "<":
        return sqla_value < value
    elif op == "<=":
        return sqla_value <= value
    elif op == "~*":
        return sqla_value.op("~*")(value)
    elif op == "!~*":
        return sqla_value.op("!~*")(value)
    else:
        raise ValueError(f"Unsupported operation: {op}")


def _build_containment_dict(json_keys: list[str], value: Any) -> dict[str, Any]:
    """Build a nested dict for JSONB containment query."""
    result: Any = value
    for key in reversed(json_keys):
        result = {key: result}
    return result


def _containment_clause(json_column: Any, json_keys: list[str], value: Any) -> ColumnElement[bool]:
    """Build a single @> containment clause."""
    containment_dict = _build_containment_dict(json_keys, value)
    return json_column.op("@>")(type_coerce(containment_dict, JSONB))


def _build_gin_prefilter(
    json_column: Any,
    json_keys: list[str],
    value: Any,
) -> ColumnElement[bool]:
    """Build a GIN pre-filter that covers all JSONB types the legacy text
    comparison could match.

    The legacy path uses ->> (text extraction) with type coercion, so a filter
    value of "42" matches JSONB string "42", number 42, and number 42.0.
    Since @> is type-strict, we OR together containment checks for each
    possible JSONB representation.
    """
    candidates: list[ColumnElement[bool]] = [_containment_clause(json_column, json_keys, value)]

    if isinstance(value, str):
        lower = value.strip().lower()

        # Numeric: "42" should match both JSONB "42" and JSONB 42
        try:
            as_float = float(value)
            as_int = int(as_float)
            if as_float == as_int:
                # Integer-like: add int form (JSONB stores 42 and 42.0 identically)
                candidates.append(_containment_clause(json_column, json_keys, as_int))
            else:
                candidates.append(_containment_clause(json_column, json_keys, as_float))
        except (ValueError, OverflowError):
            pass

        # Boolean: "true"/"false" should match JSONB true/false
        if lower in ("true", "t", "1", "yes", "on"):
            candidates.append(_containment_clause(json_column, json_keys, True))
        elif lower in ("false", "f", "0", "no", "off"):
            candidates.append(_containment_clause(json_column, json_keys, False))

    elif isinstance(value, bool):
        # Bool filter value: match JSONB bool and string representations
        candidates.append(_containment_clause(json_column, json_keys, str(value).lower()))

    elif isinstance(value, (int, float)):
        # Numeric filter value: match JSONB string form too
        candidates.append(_containment_clause(json_column, json_keys, str(value)))
        # int vs float: 42 should match 42.0 and vice versa
        if isinstance(value, int):
            candidates.append(_containment_clause(json_column, json_keys, float(value)))
        elif value == float(int(value)):
            candidates.append(_containment_clause(json_column, json_keys, int(value)))

    if len(candidates) == 1:
        return candidates[0]
    return or_(*candidates)


def build_json_filter_clause(
    json_column: Any,
    json_keys: list[str],
    value: Any,
    op: Literal[">", ">=", "<", "<=", "==", "!=", "~*", "!~*", "is"],
    *,
    use_gin_prefilter: bool = False,
) -> ColumnElement[bool]:
    """Build a WHERE clause for filtering on a JSONB column.

    When use_gin_prefilter is True and the filter is an equality check,
    adds a JSONB containment (@>) pre-filter to leverage the GIN index,
    combined with the legacy type-coerced comparison to preserve existing
    matching behavior. The pre-filter ORs across all JSONB types that the
    legacy text coercion could match, so it never produces false negatives.
    """
    sqla_value = json_column
    for key in json_keys:
        sqla_value = sqla_value[key]

    if op == "is":
        if not isinstance(value, str):
            raise ValueError("The 'is' operator requires a string value")
        sqla_value = sqla_value.as_string()
        return apply_comparison(sqla_value, value, op)

    if isinstance(value, str):
        sqla_value = sqla_value.as_string()
    elif isinstance(value, bool):
        sqla_value = safe_bool(sqla_value)
    elif isinstance(value, (int, float)):
        sqla_value = safe_float(sqla_value)
    else:
        raise ValueError(f"Unsupported value type: {type(value)}")

    legacy_clause = apply_comparison(sqla_value, value, op)

    if use_gin_prefilter and op == "==":
        gin_clause = _build_gin_prefilter(json_column, json_keys, value)
        return and_(gin_clause, legacy_clause)

    return legacy_clause


class BaseCollectionFilter(BaseModel):
    """Base class for all collection filters."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    supports_sql: bool = True  # All filters must support SQL
    disabled: bool = False

    def to_sqla_where_clause(
        self,
        table: Type["SQLAAgentRun"],
        *,
        context: FilterSQLContext | None = None,
    ) -> ColumnElement[bool] | None:
        """Convert this filter to a SQLAlchemy WHERE clause.

        All filters must implement this method to support SQL execution.
        """
        raise NotImplementedError(
            f"Filter {self.__class__.__name__} must implement to_sqla_where_clause"
        )


class PrimitiveFilter(BaseCollectionFilter):
    """Filter that applies a primitive operation to a metadata field."""

    type: Literal["primitive"] = "primitive"
    key_path: list[str]
    value: Any
    op: Literal[">", ">=", "<", "<=", "==", "!=", "~*", "!~*", "is"]

    def to_sqla_where_clause(
        self,
        table: Type["SQLAAgentRun"],
        *,
        context: FilterSQLContext | None = None,
    ) -> ColumnElement[bool] | None:
        """Convert this filter to a SQLAlchemy WHERE clause."""

        if self.disabled:
            return None

        mode = self.key_path[0]
        json_keys: list[str] | None = None

        # Extract value from appropriate source
        if mode == "created_at":
            sqla_value = cast(table.created_at, String)  # type: ignore
        elif mode == "agent_run_id":
            sqla_value = cast(table.id, String)  # type: ignore
        elif mode == "metadata":
            sqla_value = table.metadata_json  # type: ignore
            json_keys = self.key_path[1:]
        elif mode == "rubric":
            if context is None:
                raise ValueError("Rubric filters require a SQL compilation context.")
            if len(self.key_path) < 3:
                raise ValueError("Rubric filters must include a JSON field path.")
            json_keys = self.key_path[2:]
            join_spec = context.get_rubric_alias(self.key_path[1], json_keys)
            sqla_value = join_spec.alias.c.rubric_value
            json_keys = None
        elif mode == "tag":
            if context is None:
                raise ValueError("Tag filters require a SQL compilation context.")
            if len(self.key_path) != 1:
                raise ValueError("Tag filters do not support nested paths.")
            join_spec = context.get_tag_alias()
            sqla_value = join_spec.alias.value  # type: ignore[attr-defined]
        elif mode == "label":
            if context is None:
                raise ValueError("Label filters require a SQL compilation context.")
            if len(self.key_path) < 3:
                raise ValueError("Label filters must include a JSON field path.")
            join_spec = context.get_label_alias(self.key_path[1])
            sqla_value = join_spec.alias.label_value  # type: ignore[attr-defined]
            json_keys = self.key_path[2:]
        else:
            raise ValueError(f"Unsupported mode: {mode}")

        if json_keys is not None:
            if not json_keys:
                raise ValueError(f"JSON path required for mode '{mode}'.")
            for key in json_keys:
                sqla_value = sqla_value[key]

        if mode in {"metadata", "rubric", "label"}:
            if self.op == "is":
                if not isinstance(self.value, str):
                    raise ValueError("The 'is' operator requires a string value")
                sqla_value = safe_text(sqla_value)
            elif isinstance(self.value, str):
                sqla_value = safe_text(sqla_value)
            elif isinstance(self.value, bool):
                sqla_value = safe_bool(sqla_value)
            elif isinstance(self.value, (int, float)):
                sqla_value = safe_float(sqla_value)
            else:
                raise ValueError(f"Unsupported value type: {type(self.value)}")

        legacy_clause = apply_comparison(sqla_value, self.value, self.op)

        # Add GIN-indexed containment pre-filter for metadata equality
        if mode == "metadata" and self.op == "==" and json_keys:
            gin_clause = _build_gin_prefilter(
                table.metadata_json,
                json_keys,
                self.value,  # type: ignore
            )
            return and_(gin_clause, legacy_clause)

        return legacy_clause


class ComplexFilter(BaseCollectionFilter):
    """Filter that combines multiple filters with AND/OR/NOT logic."""

    type: Literal["complex"] = "complex"
    filters: list[CollectionFilter]
    op: Literal["and", "or"] = "and"

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, v: list[CollectionFilter]) -> list[CollectionFilter]:
        if not v:
            raise ValueError("ComplexFilter must have at least one filter")
        return v

    def to_sqla_where_clause(
        self,
        table: Type["SQLAAgentRun"],
        *,
        context: FilterSQLContext | None = None,
    ) -> ColumnElement[bool] | None:
        """Convert this filter to a SQLAlchemy WHERE clause."""

        if self.disabled:
            return None

        # Get WHERE clauses for all sub-filters
        where_clauses: list[ColumnElement[bool]] = []
        for filter_obj in self.filters:
            where_clause = filter_obj.to_sqla_where_clause(table, context=context)
            if where_clause is not None:
                where_clauses.append(where_clause)

        if not where_clauses:
            return None

        # Apply the operation
        if self.op == "and":
            result = and_(*where_clauses)
        elif self.op == "or":
            result = or_(*where_clauses)
        else:
            raise ValueError(f"Unsupported operation: {self.op}")

        return result


class AgentRunIdFilter(BaseCollectionFilter):
    """Filter that matches specific agent run IDs."""

    type: Literal["agent_run_id"] = "agent_run_id"
    agent_run_ids: list[str]

    @field_validator("agent_run_ids")
    @classmethod
    def validate_agent_run_ids(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("AgentRunIdFilter must have at least one agent run ID")
        return v

    def to_sqla_where_clause(
        self,
        table: Type["SQLAAgentRun"],
        *,
        context: FilterSQLContext | None = None,
    ) -> ColumnElement[bool] | None:
        """Convert to SQLAlchemy WHERE clause for agent run ID filtering."""
        if self.disabled:
            return None
        return table.id.in_(self.agent_run_ids)


CollectionFilter = Annotated[
    Union[
        PrimitiveFilter,
        ComplexFilter,
        AgentRunIdFilter,
    ],
    Discriminator("type"),
]


def parse_filter_dict(filter_dict: dict[str, Any]) -> CollectionFilter:
    """Parse a filter dictionary into a CollectionFilter object."""
    filter_type = filter_dict.get("type")

    if filter_type == "primitive":
        return PrimitiveFilter(**filter_dict)
    elif filter_type == "complex":
        # Recursively parse nested filters
        nested_filters = [parse_filter_dict(f) for f in filter_dict.get("filters", [])]
        complex_filter_dict: dict[str, Any] = {**filter_dict, "filters": nested_filters}
        return ComplexFilter(**complex_filter_dict)
    elif filter_type == "agent_run_id":
        return AgentRunIdFilter(**filter_dict)
    else:
        raise ValueError(f"Unknown filter type: {filter_type}")


def filter_uses_tags(filter_obj: CollectionFilter) -> bool:
    """Check if a filter tree contains any tag filters."""
    if filter_obj.disabled:
        return False

    if isinstance(filter_obj, PrimitiveFilter):
        return filter_obj.key_path[0] == "tag"
    elif isinstance(filter_obj, ComplexFilter):
        return any(filter_uses_tags(f) for f in filter_obj.filters)
    elif isinstance(filter_obj, AgentRunIdFilter):  # type: ignore[unreachable]
        return False

    return False


def filter_uses_labels(filter_obj: CollectionFilter) -> bool:
    """Check if a filter tree contains any label filters."""
    if filter_obj.disabled:
        return False

    if isinstance(filter_obj, PrimitiveFilter):
        return filter_obj.key_path[0] == "label"
    elif isinstance(filter_obj, ComplexFilter):
        return any(filter_uses_labels(f) for f in filter_obj.filters)
    elif isinstance(filter_obj, AgentRunIdFilter):  # type: ignore[unreachable]
        return False

    return False


def collect_label_set_ids(filter_obj: CollectionFilter) -> set[str]:
    """Collect label set IDs referenced by label filters."""
    if filter_obj.disabled:
        return set()

    if isinstance(filter_obj, PrimitiveFilter):
        if filter_obj.key_path[0] != "label":
            return set()
        if len(filter_obj.key_path) < 2:
            return set()
        return {filter_obj.key_path[1]}
    elif isinstance(filter_obj, ComplexFilter):
        label_set_ids: set[str] = set()
        for sub_filter in filter_obj.filters:
            label_set_ids.update(collect_label_set_ids(sub_filter))
        return label_set_ids
    elif isinstance(filter_obj, AgentRunIdFilter):  # type: ignore[unreachable]
        return set()

    return set()


def build_judge_result_filter_clause(
    filter_obj: CollectionFilter,
    rubric_id: str,
    judge_result_table: Type["SQLAJudgeResult"],
    agent_run_table: Type["SQLAAgentRun"],
    tag_table: Any | None = None,
    label_tables: dict[str, Any] | None = None,
) -> ColumnElement[bool] | None:
    """Build WHERE clause for judge result queries.

    Unlike the generic FilterSQLContext, this applies filters directly to tables
    already present in the query, avoiding aliased joins that don't constrain by version.

    Supports:
      - rubric.{rubric_id}.* filters -> applied to judge_result_table.output
      - metadata.* filters -> applied to agent_run_table.metadata_json
      - tag filters -> applied to tag_table.value
      - label.{label_set_id}.* filters -> applied to label_tables[label_set_id].label_value
      - agent_run_id mode -> applied to agent_run_table.id
      - created_at mode -> applied to agent_run_table.created_at
      - AgentRunIdFilter type -> applied to agent_run_table.id

    Args:
        filter_obj: The filter to apply
        rubric_id: The rubric ID to match for rubric filters
        judge_result_table: The SQLAJudgeResult table/alias in the query
        agent_run_table: The SQLAAgentRun table/alias in the query
        tag_table: The SQLATag table/alias for tag filters
        label_tables: Dict mapping label_set_id to SQLALabel table/alias for label filters

    Returns:
        A SQLAlchemy WHERE clause, or None if the filter is disabled

    Raises:
        ValueError: If the filter references unsupported modes
    """
    if filter_obj.disabled:
        return None

    if isinstance(filter_obj, PrimitiveFilter):
        mode = filter_obj.key_path[0]

        if mode == "rubric":
            if len(filter_obj.key_path) < 3:
                raise ValueError("Rubric filters must include a JSON field path.")
            filter_rubric_id = filter_obj.key_path[1]
            if filter_rubric_id != rubric_id:
                raise ValueError(
                    f"Filter references rubric '{filter_rubric_id}' but query is for rubric '{rubric_id}'"
                )
            json_keys = filter_obj.key_path[2:]
            return build_json_filter_clause(
                judge_result_table.output,  # type: ignore[attr-defined]
                json_keys,
                filter_obj.value,
                filter_obj.op,
            )
        elif mode == "metadata":
            if len(filter_obj.key_path) < 2:
                raise ValueError("Metadata filters must include a JSON field path.")
            json_keys = filter_obj.key_path[1:]
            return build_json_filter_clause(
                agent_run_table.metadata_json,  # type: ignore[attr-defined]
                json_keys,
                filter_obj.value,
                filter_obj.op,
                use_gin_prefilter=True,
            )
        elif mode == "tag":
            if len(filter_obj.key_path) != 1:
                raise ValueError("Tag filters do not support nested paths.")
            return apply_comparison(tag_table.value, filter_obj.value, filter_obj.op)  # type: ignore[attr-defined]
        elif mode == "label":
            if len(filter_obj.key_path) < 3:
                raise ValueError("Label filters must include a JSON field path.")
            label_set_id = filter_obj.key_path[1]
            if label_tables is None or label_set_id not in label_tables:
                raise ValueError(
                    f"Label filter references label set '{label_set_id}' but no table provided for it."
                )
            json_keys = filter_obj.key_path[2:]
            return build_json_filter_clause(
                label_tables[label_set_id].label_value,  # type: ignore[attr-defined]
                json_keys,
                filter_obj.value,
                filter_obj.op,
            )
        elif mode == "agent_run_id":
            sqla_value = cast(agent_run_table.id, String)  # type: ignore[attr-defined]
            return apply_comparison(sqla_value, filter_obj.value, filter_obj.op)
        elif mode == "created_at":
            sqla_value = cast(agent_run_table.created_at, String)  # type: ignore[attr-defined]
            return apply_comparison(sqla_value, filter_obj.value, filter_obj.op)
        else:
            raise ValueError(
                f"Unsupported filter mode '{mode}' in judge result context. "
                f"Only 'rubric', 'metadata', 'tag', 'label', 'agent_run_id', and 'created_at' filters are supported."
            )

    elif isinstance(filter_obj, ComplexFilter):
        where_clauses: list[ColumnElement[bool]] = []
        for sub_filter in filter_obj.filters:
            clause = build_judge_result_filter_clause(
                sub_filter, rubric_id, judge_result_table, agent_run_table, tag_table, label_tables
            )
            if clause is not None:
                where_clauses.append(clause)

        if not where_clauses:
            return None

        if filter_obj.op == "and":
            return and_(*where_clauses)
        elif filter_obj.op == "or":
            return or_(*where_clauses)
        else:
            raise ValueError(f"Unsupported operation: {filter_obj.op}")

    elif isinstance(filter_obj, AgentRunIdFilter):  # type: ignore[unreachable]
        return agent_run_table.id.in_(filter_obj.agent_run_ids)  # type: ignore[attr-defined]

    else:
        raise ValueError(f"Unknown filter type: {type(filter_obj)}")
