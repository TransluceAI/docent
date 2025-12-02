from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, Type, Union
from uuid import uuid4

from pydantic import BaseModel, Discriminator, Field, field_validator
from sqlalchemy import Boolean, ColumnElement, Float, String, and_, case, cast, or_
from sqlalchemy.orm import aliased

from docent._log_util import get_logger

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
        self._rubric_aliases: dict[str, FilterJoinSpec] = {}
        self._tag_alias: FilterJoinSpec | None = None

    def ensure_rubric_join(self, rubric_id: str) -> FilterJoinSpec:
        spec = self._rubric_aliases.get(rubric_id)
        if spec is not None:
            return spec

        from docent_core.docent.db.schemas.rubric import SQLAJudgeResult

        alias = aliased(SQLAJudgeResult, name=f"judge_result_{len(self._rubric_aliases)}")
        onclause = and_(
            getattr(alias, "agent_run_id") == getattr(self._base_table, "id"),
            getattr(alias, "rubric_id") == rubric_id,
        )
        spec = FilterJoinSpec(alias=alias, onclause=onclause)
        self._rubric_aliases[rubric_id] = spec
        return spec

    def get_rubric_alias(self, rubric_id: str) -> FilterJoinSpec:
        return self.ensure_rubric_join(rubric_id)

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

    def required_joins(self) -> tuple[FilterJoinSpec, ...]:
        joins: list[FilterJoinSpec] = list(self._rubric_aliases.values())
        if self._tag_alias is not None:
            joins.append(self._tag_alias)
        return tuple(joins)


def safe_bool(col: Any) -> Any:
    """Safely cast a column to boolean using regex validation."""
    return case(
        (cast(col, String).op("~*")("^(true|false|t|f|1|0|yes|no|on|off)$"), cast(col, Boolean)),
        else_=None,
    )


def safe_float(col: Any) -> Any:
    """Safely cast a column to float using regex validation."""
    return case(
        (cast(col, String).op("~")("^[+-]?(\\d+\\.?\\d*|\\.\\d+)([eE][+-]?\\d+)?$"), cast(col, Float)), else_=None  # type: ignore
    )


def apply_comparison(
    sqla_value: Any,
    value: Any,
    op: Literal[">", ">=", "<", "<=", "==", "!=", "~*", "!~*"],
) -> ColumnElement[bool]:
    """Apply a comparison operator to a SQLAlchemy column."""
    if op == "==":
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


def build_json_filter_clause(
    json_column: Any,
    json_keys: list[str],
    value: Any,
    op: Literal[">", ">=", "<", "<=", "==", "!=", "~*", "!~*"],
) -> ColumnElement[bool]:
    """Build a WHERE clause for filtering on a JSONB column."""
    sqla_value = json_column
    for key in json_keys:
        sqla_value = sqla_value[key]

    if isinstance(value, str):
        sqla_value = sqla_value.as_string()
    elif isinstance(value, bool):
        sqla_value = safe_bool(sqla_value)
    elif isinstance(value, (int, float)):
        sqla_value = safe_float(sqla_value)
    else:
        raise ValueError(f"Unsupported value type: {type(value)}")

    return apply_comparison(sqla_value, value, op)


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
    op: Literal[">", ">=", "<", "<=", "==", "!=", "~*", "!~*"]

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
            join_spec = context.get_rubric_alias(self.key_path[1])
            sqla_value = join_spec.alias.output  # type: ignore[attr-defined]
            json_keys = self.key_path[2:]
        elif mode == "tag":
            if context is None:
                raise ValueError("Tag filters require a SQL compilation context.")
            if len(self.key_path) != 1:
                raise ValueError("Tag filters do not support nested paths.")
            join_spec = context.get_tag_alias()
            sqla_value = join_spec.alias.value  # type: ignore[attr-defined]
        else:
            raise ValueError(f"Unsupported mode: {mode}")

        if json_keys is not None:
            if not json_keys:
                raise ValueError(f"JSON path required for mode '{mode}'.")
            for key in json_keys:
                sqla_value = sqla_value[key]

        if mode in {"metadata", "rubric"}:
            if isinstance(self.value, str):
                sqla_value = sqla_value.as_string()
            elif isinstance(self.value, bool):
                sqla_value = safe_bool(sqla_value)
            elif isinstance(self.value, (int, float)):
                sqla_value = safe_float(sqla_value)
            else:
                raise ValueError(f"Unsupported value type: {type(self.value)}")

        return apply_comparison(sqla_value, self.value, self.op)


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


def build_judge_result_filter_clause(
    filter_obj: CollectionFilter,
    rubric_id: str,
    judge_result_table: Type["SQLAJudgeResult"],
    agent_run_table: Type["SQLAAgentRun"],
    tag_table: Any | None = None,
) -> ColumnElement[bool] | None:
    """Build WHERE clause for judge result queries.

    Unlike the generic FilterSQLContext, this applies filters directly to tables
    already present in the query, avoiding aliased joins that don't constrain by version.

    Supports:
      - rubric.{rubric_id}.* filters -> applied to judge_result_table.output
      - metadata.* filters -> applied to agent_run_table.metadata_json
      - tag filters -> applied to tag_table.value
      - agent_run_id mode -> applied to agent_run_table.id
      - created_at mode -> applied to agent_run_table.created_at
      - AgentRunIdFilter type -> applied to agent_run_table.id

    Args:
        filter_obj: The filter to apply
        rubric_id: The rubric ID to match for rubric filters
        judge_result_table: The SQLAJudgeResult table/alias in the query
        agent_run_table: The SQLAAgentRun table/alias in the query
        tag_table: The SQLATag table/alias for tag filters

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
            )
        elif mode == "tag":
            if len(filter_obj.key_path) != 1:
                raise ValueError("Tag filters do not support nested paths.")
            return apply_comparison(tag_table.value, filter_obj.value, filter_obj.op)  # type: ignore[attr-defined]
        elif mode == "agent_run_id":
            sqla_value = cast(agent_run_table.id, String)  # type: ignore[attr-defined]
            return apply_comparison(sqla_value, filter_obj.value, filter_obj.op)
        elif mode == "created_at":
            sqla_value = cast(agent_run_table.created_at, String)  # type: ignore[attr-defined]
            return apply_comparison(sqla_value, filter_obj.value, filter_obj.op)
        else:
            raise ValueError(
                f"Unsupported filter mode '{mode}' in judge result context. "
                f"Only 'rubric', 'metadata', 'tag', 'agent_run_id', and 'created_at' filters are supported."
            )

    elif isinstance(filter_obj, ComplexFilter):
        where_clauses: list[ColumnElement[bool]] = []
        for sub_filter in filter_obj.filters:
            clause = build_judge_result_filter_clause(
                sub_filter, rubric_id, judge_result_table, agent_run_table, tag_table
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
