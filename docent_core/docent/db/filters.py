from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal, Type, Union
from uuid import uuid4

from pydantic import BaseModel, Discriminator, Field, field_validator
from sqlalchemy import Boolean, ColumnElement, Float, String, and_, case, cast, or_

from docent._log_util import get_logger

if TYPE_CHECKING:
    from docent_core.docent.db.schemas.tables import SQLAAgentRun

logger = get_logger(__name__)


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


class BaseCollectionFilter(BaseModel):
    """Base class for all collection filters."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    supports_sql: bool = True  # All filters must support SQL
    disabled: bool = False

    def to_sqla_where_clause(self, table: Type["SQLAAgentRun"]) -> ColumnElement[bool] | None:
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

    def to_sqla_where_clause(self, table: Type["SQLAAgentRun"]) -> ColumnElement[bool] | None:
        """Convert this filter to a SQLAlchemy WHERE clause."""

        if self.disabled:
            return None

        mode = self.key_path[0]

        # Extract value from JSONB using the table parameter
        # if mode == "text":
        #     sqla_value = table.text_for_search  # type: ignore
        if mode == "created_at":
            sqla_value = cast(table.created_at, String)  # type: ignore
        elif mode == "agent_run_id":
            sqla_value = cast(table.id, String)  # type: ignore
        elif mode == "metadata":
            sqla_value = table.metadata_json  # type: ignore
        else:
            raise ValueError(f"Unsupported mode: {mode}")

        for key in self.key_path[1:]:
            sqla_value = sqla_value[key]

        # Cast the extracted value to the correct type
        # This is only necessary for metadata which is JSONB
        if mode == "metadata":
            if isinstance(self.value, str):
                sqla_value = sqla_value.as_string()
            elif isinstance(self.value, bool):
                sqla_value = safe_bool(sqla_value)
            elif isinstance(self.value, float) or isinstance(self.value, int):  # type: ignore warning about unnecessary comparison
                # if self.value is an int, we may still need to do sql comparisons with floats
                sqla_value = safe_float(sqla_value)
            else:
                raise ValueError(f"Unsupported value type: {type(self.value)}")

        # Handle different operations using SQLAlchemy expressions
        if self.op == "==":
            return sqla_value == self.value
        elif self.op == "!=":
            return sqla_value != self.value
        elif self.op == ">":
            return sqla_value > self.value
        elif self.op == ">=":
            return sqla_value >= self.value
        elif self.op == "<":
            return sqla_value < self.value
        elif self.op == "<=":
            return sqla_value <= self.value
        elif self.op == "~*":
            return sqla_value.op("~*")(self.value)
        else:
            raise ValueError(f"Unsupported operation: {self.op}")


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

    def to_sqla_where_clause(self, table: Type["SQLAAgentRun"]) -> ColumnElement[bool] | None:
        """Convert this filter to a SQLAlchemy WHERE clause."""

        if self.disabled:
            return None

        # Get WHERE clauses for all sub-filters
        where_clauses: list[ColumnElement[bool]] = []
        for filter_obj in self.filters:
            where_clause = filter_obj.to_sqla_where_clause(table)
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

    def to_sqla_where_clause(self, table: Type["SQLAAgentRun"]) -> ColumnElement[bool] | None:
        """Convert to SQLAlchemy WHERE clause for agent run ID filtering."""
        if self.disabled:
            return None
        return table.id.in_(self.agent_run_ids)


class SearchResultPredicateFilter(BaseCollectionFilter):
    """Filter that applies a predicate to search results."""

    type: Literal["search_result_predicate"] = "search_result_predicate"
    predicate: str
    search_query: str

    def to_sqla_where_clause(self, table: Type["SQLAAgentRun"]) -> ColumnElement[bool] | None:
        """Convert to SQLAlchemy WHERE clause for search result filtering."""
        if self.disabled:
            return None
        # This filter requires joining with search results table
        # For now, we'll return None to indicate it needs special handling
        # In practice, this would join with the search_results table
        return None


class SearchResultExistsFilter(BaseCollectionFilter):
    """Filter that checks if search results exist."""

    type: Literal["search_result_exists"] = "search_result_exists"
    search_query: str

    def to_sqla_where_clause(self, table: Type["SQLAAgentRun"]) -> ColumnElement[bool] | None:
        """Convert to SQLAlchemy WHERE clause for search result existence filtering."""
        if self.disabled:
            return None
        # This filter requires joining with search results table
        # For now, we'll return None to indicate it needs special handling
        # In practice, this would join with the search_results table
        return None


CollectionFilter = Annotated[
    Union[
        PrimitiveFilter,
        ComplexFilter,
        AgentRunIdFilter,
        SearchResultPredicateFilter,
        SearchResultExistsFilter,
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
        filter_dict["filters"] = nested_filters
        return ComplexFilter(**filter_dict)
    elif filter_type == "agent_run_id":
        return AgentRunIdFilter(**filter_dict)
    elif filter_type == "search_result_predicate":
        return SearchResultPredicateFilter(**filter_dict)
    elif filter_type == "search_result_exists":
        return SearchResultExistsFilter(**filter_dict)
    else:
        raise ValueError(f"Unknown filter type: {filter_type}")
