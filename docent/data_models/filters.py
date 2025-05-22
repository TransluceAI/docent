from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, Sequence, Type, cast
from uuid import uuid4

from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator
from sqlalchemy import ColumnElement, and_, or_

from docent._ai_tools.attribute_extraction import Attribute
from docent._ai_tools.clustering.cluster_assigner import (
    DEFAULT_ASSIGNER,
    AssignerType,
    assign_with_backend,
)
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.metadata import BaseMetadata

if TYPE_CHECKING:
    from docent._db_service.schemas.tables import SQLAAgentRun

logger = get_logger(__name__)


FilterLiteral = Literal[
    "primitive",
    "predicate",
    "complex",
    "agent_run_id",
]


class Judgment(BaseModel):
    """Represents a filtering decision for a specific agent run.

    A Judgment records whether a specific filter matched an agent run, along with
    optional reasoning information.

    Attributes:
        id: Unique identifier for the judgment.
        agent_run_id: ID of the agent run this judgment applies to.
        filter_id: ID of the filter that produced this judgment.
        attribute: Optional attribute name that was evaluated.
        attribute_idx: Optional index of the attribute that was evaluated.
        matches: Whether the filter matched the agent run.
        reason: Optional explanation for the judgment.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_id: str
    filter_id: str
    attribute: str | None = None
    attribute_idx: int | None = None

    matches: bool
    reason: str | None = None


class JudgmentStreamingCallback(Protocol):
    """Protocol for callbacks that receive streaming judgment results.

    Implementations of this protocol are used to process judgments as they are produced,
    allowing for real-time updates during filtering operations.
    """

    async def __call__(self, judgment: Judgment) -> None: ...


class BaseFrameFilter(BaseModel):
    """Base class for all filters that can be applied to agent runs.

    This abstract class defines the interface for all filter types. Concrete filter
    implementations should inherit from this class and implement the apply method.

    Attributes:
        id: Unique identifier for the filter.
        name: Optional human-readable name for the filter.
        type: The type of filter, as defined in FilterLiteral.
        supports_sql: Whether this filter can be converted to SQL for database filtering.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    type: FilterLiteral

    supports_sql: bool = False

    def to_sqla_where_clause(self, SQLAAgentRun: Type[SQLAAgentRun]) -> ColumnElement[bool] | None:
        """Converts the filter to a SQLAlchemy where clause for database filtering.

        Args:
            SQLAAgentRun: The SQLAlchemy model class for agent runs.

        Returns:
            A SQLAlchemy column element that represents this filter as a where clause,
            or None if this filter doesn't support SQL conversion.
        """
        return None

    async def apply(
        self,
        agent_runs: list[AgentRun],
        attributes: list[Attribute] | None = None,
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ) -> list[Judgment]:
        """
        Applies this filter to the data.

        Args:
            agent_runs: The list of agent runs to filter.
            attributes: Optional list of attributes for the agent runs.
            judgment_callback: Optional callback for streaming judgment updates.
            return_all: If True, return judgments for all agent runs, not just matches.

        Returns:
            A list of Judgment objects for each data point, indicating
            whether it matches (with an optional reason).
        """
        raise NotImplementedError


class AgentRunIdFilter(BaseFrameFilter):
    """A filter that checks if a datapoint's ID matches a specified ID.

    This simple filter matches agent runs by their unique ID.

    Attributes:
        type: Always "agent_run_id" for this filter.
        value: The agent run ID to match against.
    """

    type: Literal["agent_run_id"] = "agent_run_id"  # type: ignore
    value: str

    async def apply(
        self,
        agent_runs: list[AgentRun],
        attributes: list[Attribute] | None = None,
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ) -> list[Judgment]:
        """Checks if agent run IDs match the specified value.

        Args:
            agent_runs: The list of agent runs to filter.
            attributes: Optional list of attributes (not used by this filter).
            judgment_callback: Optional callback for streaming judgment updates.
            return_all: If True, return judgments for all agent runs, not just matches.

        Returns:
            A list of Judgment objects for each matching agent run.
        """
        return [
            Judgment(
                matches=b,
                reason=f"agent_run_id {'matches' if b else 'does not match'} {self.value}",
                agent_run_id=ar.id,
                filter_id=self.id,
            )
            for ar in agent_runs
            if (b := ar.id == self.value) or return_all
        ]


class PrimitiveFilter(BaseFrameFilter):
    """A filter that checks if a datapoint's metadata matches a specified key-value pair.

    This filter evaluates agent runs based on the value of a specific field, using
    various comparison operators.

    Attributes:
        type: Always "primitive" for this filter.
        key_path: Tuple of strings representing the path to the value to check.
        value: The value to compare against.
        op: The comparison operator to use.
        supports_sql: Whether this filter can be converted to SQL (default True).
    """

    type: Literal["primitive"] = "primitive"  # type: ignore

    key_path: tuple[str, ...]
    value: bool | int | float | str
    op: Literal["==", "!=", "<", "<=", ">", ">=", "~*"] = "=="

    supports_sql: bool = True

    @model_validator(mode="after")
    def _validate_op_with_value(self):
        """Validates that the operator is compatible with the value type.

        For regex operations (~*), the value must be a string.

        Returns:
            The validated model instance.

        Raises:
            ValueError: If the value is not a string when using the ~* operator.
        """
        if self.op == "~*":
            if not isinstance(self.value, str):
                raise ValueError("value must be a string for ~* operation")
        return self

    @staticmethod
    def _get_value(key_path: tuple[str, ...], agent_run: AgentRun):
        """Extracts a value from an agent run using the specified key path.

        Args:
            key_path: Tuple of strings representing the path to the value.
            agent_run: The agent run to extract the value from.

        Returns:
            The extracted value.

        Raises:
            ValueError: If the extracted value is not a string, bool, int, or float.
        """
        ans = agent_run
        for k in key_path:
            if isinstance(ans, AgentRun):
                ans = getattr(ans, k)
            elif isinstance(ans, BaseMetadata):
                ans = ans.get(k)
            elif isinstance(ans, dict):
                ans = cast(dict[str, Any], ans)[k]
            else:
                raise ValueError(
                    f"Invalid key path {'.'.join(key_path)}: Cannot access key '{k}' on value of type {type(ans)}. Value must be an AgentRun or dict. Got: {ans}"
                )
        if not isinstance(ans, (str, bool, int, float)):
            raise ValueError(f"Value must be a string, bool, int, or float. Got {type(ans)}: {ans}")

        return ans

    def to_sqla_where_clause(self, SQLAAgentRun: Type[SQLAAgentRun]) -> ColumnElement[bool]:
        """Converts the filter to a SQLAlchemy where clause for database filtering.

        This method handles different data types and comparison operators to build
        the appropriate SQL condition.

        Args:
            SQLAAgentRun: The SQLAlchemy model class for agent runs.

        Returns:
            A SQLAlchemy column element that represents this filter as a where clause.

        Raises:
            ValueError: If the operation is unsupported.
        """
        mode = "text" if self.key_path[0] == "text" else "metadata"

        # Extract value from JSONB
        sqla_value = (
            SQLAAgentRun.text_for_search  # type: ignore
            if mode == "text"
            else SQLAAgentRun.metadata_json  # type: ignore
        )
        for key in self.key_path[1:]:
            sqla_value = sqla_value[key]

        # Cast the extracted value to the correct type
        # This is only necessary for metadata which is JSONB
        if mode == "metadata":
            if isinstance(self.value, str):
                sqla_value = sqla_value.as_string()
            elif isinstance(self.value, bool):
                sqla_value = sqla_value.as_boolean()
            elif isinstance(self.value, int):
                sqla_value = sqla_value.as_integer()
            else:
                sqla_value = sqla_value.as_float()

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

    async def apply(
        self,
        agent_runs: list[AgentRun],
        attributes: list[Attribute] | None = None,
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ):
        """Applies metadata filtering to the data.

        Args:
            agent_runs: The list of agent runs to filter.
            attributes: Optional list of attributes (not used by this filter).
            judgment_callback: Optional callback for streaming judgment updates.
            return_all: If True, return judgments for all agent runs, not just matches.

        Returns:
            A list of Judgment objects for each matching agent run.
        """

        def _matches(ar: AgentRun):
            v = PrimitiveFilter._get_value(self.key_path, ar)
            return (
                (v == self.value)
                if self.op == "=="
                else (
                    (v != self.value)
                    if self.op == "!="
                    else (
                        (float(v) < float(self.value))
                        if self.op == "<"
                        else (
                            (float(v) <= float(self.value))
                            if self.op == "<="
                            else (
                                (float(v) > float(self.value))
                                if self.op == ">"
                                else (float(v) >= float(self.value))
                            )
                        )
                    )
                )
            )

        return [
            Judgment(
                agent_run_id=ar.id,
                filter_id=self.id,
                matches=b,
                reason=f"metadata {'.'.join(self.key_path)} {self.op} {self.value}",
            )
            for ar in agent_runs
            if (b := _matches(ar)) or return_all
        ]


class PredicateFilter(BaseFrameFilter):
    """A filter that uses an LLM to evaluate text against a predicate.

    This filter uses an LLM to determine which agent runs satisfy a given predicate,
    based on the values of a specified attribute.

    Attributes:
        type: Always "predicate" for this filter.
        predicate: The predicate to evaluate against each attribute value.
        attribute: The name of the attribute to evaluate.
        backend: The LLM backend to use for evaluation.
        llm_api_keys: Optional API keys for the LLM.
    """

    type: Literal["predicate"] = "predicate"  # type: ignore

    predicate: str
    attribute: str
    backend: AssignerType = DEFAULT_ASSIGNER

    async def apply(
        self,
        agent_runs: list[AgentRun],
        attributes: list[Attribute] | None = None,
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ):
        """Uses an LLM to determine which data points satisfy the predicate.

        Args:
            agent_runs: The list of agent runs to filter.
            attributes: The list of attributes to evaluate against the predicate.
            judgment_callback: Optional callback for streaming judgment updates.
            return_all: If True, return judgments for all agent runs, not just matches.

        Returns:
            A list of Judgment objects for each evaluated attribute.

        Raises:
            ValueError: If attributes are missing or not computed.
        """
        # Validate attributes
        assert attributes is not None, "Attributes must be provided for FramePredicate"
        agent_runs_with_computed_attributes = set(attr.agent_run_id for attr in attributes)
        for ar in agent_runs:
            if ar.id not in agent_runs_with_computed_attributes:
                raise ValueError(
                    f"At least one datapoint is missing attribute {self.attribute}. These must be computed ahead of time."
                )

        # Collect attributes that need assignment
        strings_to_assign: list[str] = []
        index_map: list[tuple[str, int]] = []
        for attr in attributes:
            if attr.value is not None and attr.attribute_idx is not None:
                strings_to_assign.append(attr.value)
                index_map.append((attr.agent_run_id, attr.attribute_idx))

        # One judgment for each attribute to assign
        judgments: list[Judgment] = []

        async def _assignment_callback(batch_index: int, assignment: tuple[bool, str] | None):
            """Stream judgments as they're computed."""
            nonlocal judgments, index_map

            m = assignment  # Rename for simplicity
            agent_run_id, attr_index = index_map[batch_index]
            judgment = (
                Judgment(
                    matches=m[0],
                    reason=m[1],
                    agent_run_id=agent_run_id,
                    filter_id=self.id,
                    attribute=self.attribute,
                    attribute_idx=attr_index,
                )
                if m is not None
                else Judgment(
                    matches=False,
                    reason="API error; default false",
                    agent_run_id=agent_run_id,
                    filter_id=self.id,
                    attribute=self.attribute,
                    attribute_idx=attr_index,
                )
            )
            judgments.append(judgment)

            if judgment_callback is not None:
                await judgment_callback(judgment)

        await assign_with_backend(
            backend=self.backend,
            items=strings_to_assign,
            clusters=[self.predicate for _ in strings_to_assign],
            assignment_callback=_assignment_callback,
        )

        return judgments


class ComplexFilter(BaseFrameFilter):
    """A filter that combines multiple filters using logical operations.

    This filter allows combining other filters with logical AND/OR operations
    to create more complex filtering conditions.

    Attributes:
        type: Always "complex" for this filter.
        id: Unique identifier for the filter.
        filters: Sequence of filters to combine.
        op: The logical operation to use ("and" or "or").
    """

    type: Literal["complex"] = "complex"  # type: ignore

    id: str = Field(default_factory=lambda: str(uuid4()))
    filters: Sequence[FrameFilter]
    op: Literal["and", "or"]

    @model_validator(mode="after")
    def _validate_supports_sql(self):
        """Determine whether this complex filter supports SQL or not.

        A complex filter supports SQL only if all its component filters do.

        Returns:
            The validated model instance with supports_sql set appropriately.
        """
        for f in self.filters:
            if not f.supports_sql:
                self.supports_sql = False
                return self

        self.supports_sql = True
        return self

    @field_validator("filters")
    def _validate_filters(cls, v: list[FrameFilter]):
        """Validates the filters sequence.

        Args:
            v: The sequence of filters to validate.

        Returns:
            The validated filters sequence.

        Raises:
            ValueError: If the filters sequence is empty.
        """
        if not v:
            raise ValueError("ComplexFrameFilter must have at least one filter")
        return v

    def to_sqla_where_clause(self, SQLAAgentRun: Type[SQLAAgentRun]):
        """Converts the filter to a SQLAlchemy where clause for database filtering.

        This method combines the where clauses from all component filters using
        the appropriate logical operation.

        Args:
            SQLAAgentRun: The SQLAlchemy model class for agent runs.

        Returns:
            A SQLAlchemy column element that represents this filter as a where clause,
            or None if this filter doesn't support SQL conversion.

        Raises:
            ValueError: If the operation is invalid.
            AssertionError: If a component filter unexpectedly doesn't support SQL.
        """
        if not self.supports_sql:
            return None

        # Recursively get where clauses from all child filters
        where_clauses: list[ColumnElement[bool]] = []
        for filter in self.filters:
            clause = filter.to_sqla_where_clause(SQLAAgentRun)
            assert (
                clause is not None
            ), f"Filter {filter} does not support SQL, but ComplexFrameFilter.supports_sql == True. This should never happen!"
            where_clauses.append(clause)

        # Combine the where clauses using the appropriate operator
        if self.op == "and":
            return and_(*where_clauses)
        elif self.op == "or":
            return or_(*where_clauses)
        else:
            raise ValueError(f"Invalid operation: {self.op}")

    async def apply(
        self,
        agent_runs: list[AgentRun],
        attributes: list[Attribute] | None = None,
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ):
        """Applies multiple filters to the data using the specified operation.

        Args:
            agent_runs: The list of agent runs to filter.
            attributes: Optional list of attributes for the agent runs.
            judgment_callback: Optional callback for streaming judgment updates.
            return_all: If True, return judgments for all agent runs, not just matches.

        Returns:
            A list of Judgment objects for each agent run.
        """
        if not self.filters:
            return list[Judgment]()

        # Gather judgments from each subfilter
        matching_agent_run_ids: list[set[str]] = []
        for f in self.filters:
            judgments = await f.apply(agent_runs, attributes, judgment_callback, return_all)
            cur_matching_run_ids = set(j.agent_run_id for j in judgments if j.matches)
            matching_agent_run_ids.append(cur_matching_run_ids)

        return _combine_filter_judgments_partial(
            matching_agent_run_ids,
            self.op,
            self.id,
            return_all,
            [ar.id for ar in agent_runs] if return_all else None,
        )


class FrameDimension(BaseModel):
    """Represents a dimension for organizing and filtering agent runs.

    A dimension can be used to group agent runs into bins based on various criteria,
    such as metadata values or predicate evaluations.

    Attributes:
        id: Unique identifier for the dimension.
        name: Optional human-readable name for the dimension.
        bins: Optional list of filters that define the bins of this dimension.
        attribute: Optional attribute name for predicate dimensions.
        backend: The LLM backend to use for predicate dimensions.
        metadata_key: Optional metadata key for metadata dimensions.
        maintain_mece: Optional flag to maintain mutually exclusive and collectively
            exhaustive bins.
        loading_clusters: Flag indicating whether the dimension is loading clusters.
        loading_marginals: Flag indicating whether the dimension is loading marginals.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    bins: list[FrameFilter] | None = None

    # For predicate dimensions
    attribute: str | None = None
    backend: AssignerType = DEFAULT_ASSIGNER

    # For metadata dimensions
    metadata_key: str | None = None
    maintain_mece: bool | None = None

    # Loading state
    loading_clusters: bool = False
    loading_marginals: bool = False

    @model_validator(mode="after")
    def _validate_bins(self):
        """Validates that all bins have unique IDs.

        Returns:
            The validated model instance.

        Raises:
            ValueError: If bins have duplicate IDs.
        """
        if self.bins is not None:
            bin_ids = [bin.id for bin in self.bins]
            if len(bin_ids) != len(set(bin_ids)):
                raise ValueError(f"Bins must have unique IDs, got: {bin_ids}")

        return self


# Type union that allows the type system to infer the correct type based on the 'type' field
FrameFilter = Annotated[
    PrimitiveFilter | PredicateFilter | ComplexFilter | AgentRunIdFilter,
    Discriminator("type"),
]


def _combine_filter_judgments_partial(
    matching_ids_FN: list[set[str]],
    op: Literal["and", "or"],
    filter_id: str,
    return_all: bool = False,
    all_agent_run_ids: list[str] | None = None,
):
    """Combines the results of multiple filters using a logical operation.

    Args:
        matching_ids_FN: List of sets, where each set contains the IDs of agent runs
            that matched a particular filter.
        op: The logical operation to use ("and" or "or").
        filter_id: The ID of the complex filter.
        return_all: If True, return judgments for all agent runs, not just matches.
        all_agent_run_ids: List of all agent run IDs, required if return_all is True.

    Returns:
        A list of Judgment objects for the agent runs.

    Raises:
        ValueError: If op is invalid or if all_agent_run_ids is missing when return_all
            is True.
    """
    if op == "and":
        matching_ids = set[str].intersection(*matching_ids_FN)
    elif op == "or":
        matching_ids = set[str].union(*matching_ids_FN)
    else:
        raise ValueError(f"Invalid operation: {op}")

    # Normal case: return only matching judgments
    if not return_all:
        return [
            Judgment(
                matches=True,
                reason=f"Matched {op} of filters",
                agent_run_id=i,
                filter_id=filter_id,
            )
            for i in matching_ids
        ]
    # When return_all is True, return judgments for all datapoints
    else:
        if all_agent_run_ids is None:
            raise ValueError("all_agent_run_ids must be provided if return_all is True")

        return [
            Judgment(
                matches=i in matching_ids,
                reason=f"{'Matched' if i in matching_ids else 'Did not match'} {op} of filters",
                agent_run_id=i,
                filter_id=filter_id,
            )
            for i in all_agent_run_ids
        ]


def parse_filter_dict(filter_dict: dict[str, Any]) -> FrameFilter:
    """Parses a dictionary representation of a filter into a FrameFilterTypes object.

    This function allows creating filter objects from serialized dictionary representations,
    handling the appropriate filter type based on the 'type' field.

    Args:
        filter_dict: Dictionary containing the filter specification.

    Returns:
        The parsed filter object.

    Raises:
        ValueError: If the dictionary doesn't contain a 'type' field or if the type
            is unknown.
    """
    if "type" not in filter_dict:
        raise ValueError("Filter dictionary must contain 'type' field")
    filter_type = filter_dict["type"]

    if filter_type == "primitive":
        return PrimitiveFilter(**filter_dict)
    elif filter_type == "predicate":
        return PredicateFilter(**filter_dict)
    elif filter_type == "complex":
        # Recursively parse nested filters
        nested_filters = [parse_filter_dict(f) for f in filter_dict["filters"]]
        return ComplexFilter(
            filters=nested_filters,
            op=filter_dict["op"],
            **({"id": filter_dict["id"]} if "id" in filter_dict else {}),
        )
    elif filter_type == "agent_run_id":
        return AgentRunIdFilter(**filter_dict)
    else:
        raise ValueError(f"Unknown filter type: {filter_type}")
