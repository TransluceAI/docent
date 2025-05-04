from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Sequence, Type, cast
from uuid import uuid4

from docent._frames.clustering.cluster_assigner import ASSIGNERS, DEFAULT_ASSIGNER, AssignerType
from docent._frames.db.schemas.base import SQLABase
from docent._frames.types import Datapoint, Judgment, JudgmentStreamingCallback, RegexSnippet
from docent._llm_util.types import LLMApiKeys
from docent._log_util import get_logger
from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator
from sqlalchemy import Boolean, ColumnElement, Double, Integer, String, and_, or_

PG_TYPES = {
    "str": String,
    "int": Integer,
    "float": Double,
    "bool": Boolean,
}

logger = get_logger(__name__)


FilterLiteral = Literal[
    "primitive",
    "predicate",
    "complex",
    "datapoint_id",
    "transcript_contains",
]


class FrameFilter(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    type: FilterLiteral

    supports_sql: bool = False

    def to_sqla_where_clause(self, SQLADatapoint: Type[SQLABase]) -> ColumnElement[bool] | None:
        return None

    async def apply(
        self,
        data: list[Datapoint],
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ) -> list[list[Judgment]]:
        """
        Applies this filter to the data.

        Args:
            data: The list of datapoints to filter.
            attribute_callback: Optional callback for streaming attribute extraction updates.
            judgment_callback: Optional callback for streaming judgment updates.
        Returns:
            A list of Judgment objects for each data point, indicating
            whether it matches (with an optional reason).
        """
        raise NotImplementedError


class DatapointIdFilter(FrameFilter):
    """A filter that checks if a datapoint's ID matches a specified ID."""

    type: Literal["datapoint_id"] = "datapoint_id"
    value: str

    async def apply(
        self,
        data: list[Datapoint],
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ) -> list[list[Judgment]]:
        return [
            [
                Judgment(
                    matches=b,
                    reason=f"datapoint_id {'matches' if b else 'does not match'} {self.value}",
                    data_id=d.id,
                )
            ]
            for d in data
            if (b := d.id == self.value) or return_all
        ]


class PrimitiveFilter(FrameFilter):
    """A filter that checks if a datapoint's metadata matches a specified key-value pair."""

    type: Literal["primitive"] = "primitive"

    key_path: tuple[str, ...]
    value: bool | int | float | str
    op: Literal["==", "!=", "<", "<=", ">", ">=", "~*"] = "=="

    supports_sql: bool = True

    @model_validator(mode="after")
    def validate_op_with_value(self):
        if self.op == "~*":
            if not isinstance(self.value, str):
                raise ValueError("value must be a string for ~* operation")
        return self

    @field_validator("key_path")
    def validate_key_path(cls, v: tuple[str, ...]):
        """
        Key path must either be:
        - `text`
        - `metadata.*`
        - `metadata.scores.*`
        """
        if not v:
            raise ValueError("key_path cannot be empty")

        # Check if it's the 'text' option
        if v == ("text",):
            return v

        # Check if it starts with 'metadata'
        if v[0] == "metadata" and len(v) >= 2:
            # Check for 'metadata.scores.*' pattern
            if len(v) == 3 and v[1] == "scores":
                return v
            # Check for 'metadata.*' pattern
            if len(v) == 2 and v[1] != "scores":
                return v

        raise ValueError(f"key_path must be 'text', 'metadata.*', or 'metadata.scores.*'. Got {v}")

    @staticmethod
    def get_value(key_path: tuple[str, ...], datapoint: Datapoint):
        ans = datapoint
        for k in key_path:
            ans = getattr(ans, k)

        if not isinstance(ans, (str, bool, int, float)):
            raise ValueError(f"Value must be a string, bool, int, or float. Got {type(ans)}: {ans}")
        return ans

    def to_sqla_where_clause(self, SQLADatapoint: Type[SQLABase]) -> ColumnElement[bool]:
        mode = "text" if self.key_path[0] == "text" else "metadata"

        # Extract value from JSONB
        sqla_value = (
            SQLADatapoint.text_for_search  # type: ignore
            if mode == "text"
            else SQLADatapoint.metadata_json  # type: ignore
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
            elif isinstance(self.value, float):
                sqla_value = sqla_value.as_float()
            else:
                raise ValueError(f"Unsupported value type: {type(self.value)}")

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
        data: list[Datapoint],
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ) -> list[list[Judgment]]:
        """Applies metadata filtering to the data.

        Args:
            data: The list of datapoints to filter.
        Returns:
            A list of Judgment objects for each data point, indicating
            whether it matches based on metadata comparison.
        """

        def _matches(d: Datapoint):
            v = PrimitiveFilter.get_value(self.key_path, d)
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
            [
                Judgment(
                    matches=b,
                    reason=f"metadata {'.'.join(self.key_path)} {self.op} {self.value}",
                    data_id=d.id,
                )
            ]
            for d in data
            if (b := _matches(d)) or return_all
        ]

    @staticmethod
    def get_regex_snippets(text: str, pattern: str, window_size: int = 50):
        # Find all matches
        try:
            matches = list(re.compile(pattern, re.IGNORECASE | re.DOTALL).finditer(text))
            if not matches:
                logger.warning(f"No regex matches found for `{pattern}`: this shouldn't happen!")

            if not matches:
                return []

            snippets = []
            for match in matches:
                start, end = match.span()

                # Calculate window around the match
                snippet_start = max(0, start - window_size)
                snippet_end = min(len(text), end + window_size)

                # Create the snippet with the match indices adjusted for the window
                snippets.append(
                    RegexSnippet(
                        snippet=text[snippet_start:snippet_end],
                        match_start=start - snippet_start,
                        match_end=end - snippet_start,
                    )
                )

            return snippets
        except re.error as e:
            logger.error(f"Got regex error: {e}")
            return []


class FramePredicate(FrameFilter):
    type: Literal["predicate"] = "predicate"

    predicate: str
    attribute: str
    backend: AssignerType = DEFAULT_ASSIGNER
    llm_api_keys: LLMApiKeys | None = None

    async def apply(
        self,
        data: list[Datapoint],
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ):
        """Uses an LLM to determine which data points satisfy the predicate.

        Args:
            data: The list of datapoints to filter.
            attribute_callback: Optional callback for streaming attribute extraction updates.
            assignment_callback: Optional callback for streaming assignment updates.
        Returns:
            A list of Judgment objects for each data point, indicating
            whether it matches (with an optional reason).
        """
        if any(self.attribute not in d.attributes for d in data):
            raise ValueError(
                f"At least one datapoint is missing attribute {self.attribute}. These must be computed ahead of time."
            )
        to_check_NA = [d.attributes[self.attribute] for d in data]

        # Flatten for the API call & keep track of indices
        to_check_flat: list[str] = []
        index_map: list[tuple[int, int]] = []
        # Create unflattened 2D results structure
        judgments_NA: list[list[Judgment | None]] = []
        for i, sublist in enumerate(to_check_NA):
            judgments_NA.append([])
            for j, item in enumerate(sublist):
                to_check_flat.append(item)
                index_map.append((i, j))
                judgments_NA[i].append(None)

        async def _assignment_callback(batch_index: int, assignment: tuple[bool, str] | None):
            """Stream judgments as they're computed."""
            m = assignment  # Rename for simplicity
            i, j = index_map[batch_index]
            judgment = (
                Judgment(
                    matches=m[0],
                    reason=m[1],
                    data_id=data[i].id,
                    attribute=self.attribute,
                    attribute_idx=j,
                )
                if m is not None
                else Judgment(
                    matches=False,
                    reason="API error; default false",
                    data_id=data[i].id,
                    attribute=self.attribute,
                    attribute_idx=j,
                )
            )
            judgments_NA[i][j] = judgment

            if judgment_callback is not None:
                await judgment_callback(i, j, judgment)

        await ASSIGNERS[self.backend].assign(
            to_check_flat,
            [self.predicate for _ in to_check_flat],
            assignment_callback=_assignment_callback,
            llm_api_keys=self.llm_api_keys,
        )

        for i, sublist in enumerate(judgments_NA):
            for j, item in enumerate(sublist):
                assert item is not None

        return cast(list[list[Judgment]], judgments_NA)


class ComplexFrameFilter(FrameFilter):
    type: Literal["complex"] = "complex"

    id: str = Field(default_factory=lambda: str(uuid4()))
    filters: Sequence[FrameFilterTypes]
    op: Literal["and", "or"]

    @model_validator(mode="after")
    def validate_supports_sql(self):
        """Determine whether this complex filter supports SQL or not."""
        for f in self.filters:
            if not f.supports_sql:
                self.supports_sql = False
                return self

        self.supports_sql = True
        return self

    @field_validator("filters")
    def validate_filters(cls, v):
        if not v:
            raise ValueError("ComplexFrameFilter must have at least one filter")
        return v

    def to_sqla_where_clause(self, SQLADatapoint: Type[SQLABase]):
        if not self.supports_sql:
            return None

        # Recursively get where clauses from all child filters
        where_clauses = []
        for filter in self.filters:
            clause = filter.to_sqla_where_clause(SQLADatapoint)
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
        data: list[Datapoint],
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ) -> list[list[Judgment]]:
        """Applies multiple filters to the data using the specified operation.

        Args:
            data: The list of datapoints to filter.
            attribute_callback: Optional callback for streaming attribute extraction updates.
            judgment_callback: Optional callback for streaming judgment updates.
        Returns:
            A list of Judgment objects for each data point, indicating
            whether it matches (with an optional reason).
        """
        if not self.filters:
            return []

        # Gather judgments from each subfilter
        # Each filter could target a different set of attributes, so A is variable
        matching_datapoint_ids: list[set[str]] = []
        for f in self.filters:
            judgments_NA = await f.apply(data, judgment_callback, return_all)
            cur_matching_set: set[str] = set()
            for judgments_A in judgments_NA:
                if any(judgment.matches for judgment in judgments_A):
                    cur_matching_set.add(judgments_A[0].data_id)
            matching_datapoint_ids.append(cur_matching_set)

        return _combine_filter_judgments_partial(
            matching_datapoint_ids,
            self.op,
            return_all,
            [d.id for d in data] if return_all else None,
        )


async def _cli_callback(proposals: list[list[str]]):
    print("\nProposed clusters:")
    if len(proposals) == 0:
        return None

    for idx, proposal in enumerate(proposals, 0):
        print(f"\nProposal {idx}:")
        print("\n".join([f"- {cluster}" for cluster in proposal]))

    while True:
        choice = (
            input(
                "\nSelect a proposal number (0-4), enter 'feedback' to provide custom grouping, or 'retry' for new proposals: "
            )
            .strip()
            .lower()
        )

        if choice == "feedback":
            feedback = input("\nPlease provide your feedback on how the items should be grouped: ")
            return feedback
        elif choice == "retry":
            return None
        elif choice == "stop":
            raise Exception("Stopping")
        else:
            try:
                choice_idx = int(choice)
                if 0 <= choice_idx < len(proposals):
                    return choice_idx
                else:
                    print(f"Please enter a valid number between 0 and {len(proposals) - 1}")
            except ValueError:
                print("Please enter a valid number, 'feedback', 'retry', or 'stop'")


class FrameDimension(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    bins: list[FrameFilterTypes] | None = None

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
    def validate_bins(self):
        if self.bins is not None:
            bin_ids = [bin.id for bin in self.bins]
            if len(bin_ids) != len(set(bin_ids)):
                raise ValueError(f"Bins must have unique IDs, got: {bin_ids}")

        return self


# Type union that allows the type system to infer the correct type based on the 'type' field
FrameFilterTypes = Annotated[
    PrimitiveFilter | FramePredicate | ComplexFrameFilter | DatapointIdFilter,
    Discriminator("type"),
]


def _combine_filter_judgments_partial(
    matching_ids_FN: list[set[str]],
    op: Literal["and", "or"],
    return_all: bool = False,
    all_data_ids: list[str] | None = None,
):
    if op == "and":
        matching_ids = set[str].intersection(*matching_ids_FN)
    elif op == "or":
        matching_ids = set[str].union(*matching_ids_FN)
    else:
        raise ValueError(f"Invalid operation: {op}")

    # Normal case: return only matching judgments
    if not return_all:
        return [
            [Judgment(matches=True, reason=f"Matched {op} of filters", data_id=i)]
            for i in matching_ids
        ]
    # When return_all is True, return judgments for all datapoints
    else:
        if all_data_ids is None:
            raise ValueError("all_data_ids must be provided if return_all is True")

        return [
            [
                Judgment(
                    matches=i in matching_ids,
                    reason=f"{'Matched' if i in matching_ids else 'Did not match'} {op} of filters",
                    data_id=i,
                )
            ]
            for i in all_data_ids
        ]


def parse_filter_dict(filter_dict: dict[str, Any]) -> FrameFilterTypes:
    if "type" not in filter_dict:
        raise ValueError("Filter dictionary must contain 'type' field")
    filter_type = filter_dict["type"]

    if filter_type == "primitive":
        return PrimitiveFilter(**filter_dict)
    elif filter_type == "predicate":
        return FramePredicate(**filter_dict)
    elif filter_type == "complex":
        # Recursively parse nested filters
        nested_filters = [parse_filter_dict(f) for f in filter_dict["filters"]]
        return ComplexFrameFilter(
            filters=nested_filters,
            op=filter_dict["op"],
            **({"id": filter_dict["id"]} if "id" in filter_dict else {}),
        )
    elif filter_type == "datapoint_id":
        return DatapointIdFilter(**filter_dict)
    else:
        raise ValueError(f"Unknown filter type: {filter_type}")
