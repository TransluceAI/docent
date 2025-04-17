from __future__ import annotations

import asyncio
import re
from itertools import chain, product
from time import perf_counter
from typing import Any, Awaitable, Callable, Literal, Sequence, cast
from uuid import uuid4

from frames.attributes import AttributeStreamingCallback, extract_attributes
from frames.clustering.cluster_assigner import ASSIGNERS, DEFAULT_ASSIGNER, AssignerType
from frames.clustering.cluster_generator import ClusterFeedback, propose_clusters
from frames.transcript import TranscriptMetadata
from frames.types import Datapoint, Judgment, JudgmentStreamingCallback
from llm_util.types import ChatMessage, LLMApiKeys
from log_util import get_logger
from pydantic import BaseModel, Field, model_validator

logger = get_logger(__name__)


FilterLiteral = Literal[
    "metadata",
    "predicate",
    "complex",
    "datapoint_id",
    "attribute",
    "transcript_contains",
]


class FrameFilter(BaseModel):
    id: str
    type: FilterLiteral

    async def apply(
        self,
        data: list[Datapoint],
        indexed_matching_data_ids: list[str] | None = None,
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

    type: FilterLiteral = "datapoint_id"
    value: str

    async def apply(
        self,
        data: list[Datapoint],
        indexed_matching_data_ids: list[str] | None = None,
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


class MetadataFilter(FrameFilter):
    """A filter that checks if a datapoint's metadata matches a specified key-value pair."""

    type: FilterLiteral = "metadata"

    key: str
    value: Any
    op: Literal["==", "!=", "<", "<=", ">", ">="] = "=="

    @staticmethod
    def get_value(key: str, datapoint: Datapoint):
        if key.startswith("score."):
            return datapoint.metadata.scores[key[len("score.") :]]
        else:
            return getattr(datapoint.metadata, key)

    async def apply(
        self,
        data: list[Datapoint],
        indexed_matching_data_ids: list[str] | None = None,
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

        # Shortcut if we've already pre-cached the indices
        if indexed_matching_data_ids is not None:
            return [
                [
                    Judgment(
                        matches=True,
                        reason=f"metadata {self.key} {self.op} {self.value}",
                        data_id=id,
                    )
                ]
                for id in indexed_matching_data_ids
            ]

        def _matches(d: Datapoint):
            v = MetadataFilter.get_value(self.key, d)
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
                    reason=f"metadata {self.key} {self.op} {self.value}",
                    data_id=d.id,
                )
            ]
            for d in data
            if (b := _matches(d)) or return_all
        ]


class FramePredicate(FrameFilter):
    type: FilterLiteral = "predicate"

    predicate: str
    attribute: str
    backend: AssignerType = DEFAULT_ASSIGNER
    llm_api_keys: LLMApiKeys | None = None

    async def apply(
        self,
        data: list[Datapoint],
        indexed_matching_data_ids: list[str] | None = None,
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
        await _unlocked_compute_and_set_attributes_if_needed(
            data, self.attribute, llm_api_keys=self.llm_api_keys
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
                    attribute_id=self.attribute,
                    attribute_idx=j,
                )
                if m is not None
                else Judgment(
                    matches=False,
                    reason="API error; default false",
                    data_id=data[i].id,
                    attribute_id=self.attribute,
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
    type: FilterLiteral = "complex"

    id: str = Field(default_factory=lambda: f"_complex_{str(uuid4())}")
    filters: list[FrameFilterTypes]
    op: Literal["and", "or"]

    async def apply(
        self,
        data: list[Datapoint],
        indexed_matching_data_ids: list[str] | None = None,
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
            judgments_NA = await f.apply(data, None, judgment_callback, return_all)
            cur_matching_set: set[str] = set()
            for judgments_A in judgments_NA:
                if any(judgment.matches for judgment in judgments_A):
                    cur_matching_set.add(judgments_A[0].data_id)
            matching_datapoint_ids.append(cur_matching_set)

        return _combine_filter_judgments_partial(
            matching_datapoint_ids,
            self.op,
        )


class AttributeFilter(FrameFilter):
    """A filter that checks if a datapoint has any attribute matching a specified attribute_id."""

    type: FilterLiteral = "attribute"
    attribute_id: str

    async def apply(
        self,
        data: list[Datapoint],
        indexed_matching_data_ids: list[str] | None = None,
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ) -> list[list[Judgment]]:
        """Applies attribute filtering to the data.

        Args:
            data: The list of datapoints to filter.
        Returns:
            A list of Judgment objects for each data point, indicating
            whether it has the specified attribute.
        """
        return [
            [
                Judgment(
                    matches=b,
                    reason=f"datapoint {'has' if b else 'does not have'} attribute {self.attribute_id}",
                    data_id=d.id,
                    attribute_id=self.attribute_id,
                )
            ]
            for d in data
            if (b := len(d.attributes.get(self.attribute_id, [])) > 0) or return_all
        ]


class TranscriptContainsFilter(FrameFilter):
    """Filter frames by regex match on the full transcript text (case-insensitive)."""

    type: Literal["transcript_contains"] = "transcript_contains"
    substring: str

    async def apply(
        self,
        data: list[Datapoint],
        indexed_matching_data_ids: list[str] | None = None,
        judgment_callback: JudgmentStreamingCallback | None = None,
        return_all: bool = False,
    ) -> list[list[Judgment]]:
        """Applies a case insensitive regex filter to the data."""
        pattern = re.compile(self.substring, flags=re.IGNORECASE)
        return [
            [
                Judgment(
                    matches=b,
                    reason=f"transcript matches regex '{self.substring}' (case-insensitive)",
                    data_id=d.id,
                )
            ]
            for d in data
            if (b := bool(pattern.search(d.text))) or return_all
        ]


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
    id: str
    bins: list[FrameFilterTypes] | None = None
    attribute: str | None = None
    metadata_key: str | None = None
    backend: AssignerType = DEFAULT_ASSIGNER

    # Private field for cluster history
    cluster_history: list[ClusterFeedback] = Field(default_factory=list, exclude=True)

    @model_validator(mode="after")
    def validate_bins(self):
        if self.bins is not None:
            bin_ids = [bin.id for bin in self.bins]
            if len(bin_ids) != len(set(bin_ids)):
                raise ValueError(f"Bins must have unique IDs, got: {bin_ids}")

        return self

    async def get_frames(
        self,
        data: list[Datapoint],
    ) -> dict[str, Frame]:
        if self.bins is None:
            raise ValueError("No bins defined")

        assert self.bins is not None
        frames: dict[str, Frame] = {}

        # Create frames without callbacks
        for bin in self.bins:
            frames[bin.id] = Frame(data, bin)

        return frames

    async def compute_clusters(
        self,
        data: list[Datapoint],
        picking_strategy: Literal["first", "check", "callback"] = "first",
        picking_callback: Callable[[list[list[str]]], Awaitable[int | str | None]] = _cli_callback,
        attribute_callback: AttributeStreamingCallback | None = None,
        judgment_callback: JudgmentStreamingCallback | None = None,
        new_feedback: ClusterFeedback | None = None,
        n_clusters: int = 1,
        llm_api_keys: LLMApiKeys | None = None,
    ):
        """Create clusters for this dimension.

        Args:
            data: List of datapoints to cluster
            attribute_callback: Optional callback for streaming attribute extraction updates.
            judgment_callback: Optional callback for streaming judgment updates.
            picking_strategy: Strategy for selecting clusters
            n_clusters: Number of clusters to generate

        Picking callback accepts a list[list] of clusters
        - Returns either an index or feedback
        """

        if self.attribute is None:
            raise ValueError("Cannot compute clusters on a dimension without an attribute")

        # Collect attributes to cluster
        # Use the new streaming callback so that attribute extraction updates are sent as soon as they're available.
        await _unlocked_compute_and_set_attributes_if_needed(
            data,
            self.attribute,
            attribute_callback=attribute_callback,
            llm_api_keys=llm_api_keys,
        )
        to_cluster = list(chain(*[d.attributes[self.attribute] for d in data]))

        # Propose clusters with guidance on what attribute to focus on
        guidance = (
            f"Specifically focus on the following attribute: {self.attribute}"
            if self.attribute
            else None
        )

        # If there is feedback provided, add to history
        if new_feedback is not None:
            self.cluster_history.append(new_feedback)

        selected_proposal = None
        while selected_proposal is None:
            proposals = await propose_clusters(
                to_cluster,
                n_clusters_list=[None],
                extra_instructions_list=[guidance],
                feedback_list=self.cluster_history,
                k=n_clusters,
                llm_api_keys=llm_api_keys,
            )

            if picking_strategy == "callback":
                if len(proposals) == 0:
                    continue  # Retry

                feedback = await picking_callback(proposals)
                if isinstance(feedback, str):
                    self.cluster_history.append({"clusters": proposals[0], "feedback": feedback})
                elif isinstance(feedback, int):
                    selected_proposal = proposals[feedback]
                    self.cluster_history.clear()
            elif picking_strategy == "first":
                selected_proposal = proposals[0]
            else:
                raise ValueError(f"Invalid picking strategy: {picking_strategy}")

        # Store clusters in bins
        return [
            FramePredicate(
                id=bin_str,
                predicate=bin_str,
                attribute=self.attribute,
                backend=self.backend,
                llm_api_keys=llm_api_keys,
            )
            for bin_str in selected_proposal
        ]

    async def compute_metadata_bins(self, data: list[Datapoint]) -> list[MetadataFilter]:
        """Create MetadataFilters for each unique value of the specified metadata key.

        Args:
            data: List of datapoints to analyze

        Returns:
            List of MetadataFilters, one for each unique value of the metadata key

        Raises:
            ValueError: If metadata_key is not set or if no datapoints have the specified key
        """
        if self.metadata_key is None:
            raise ValueError("Cannot compute metadata filters: metadata_key is not set")

        # Collect all unique values for this metadata key
        unique_values: set[Any] = set()
        for d in data:
            if hasattr(d.metadata, self.metadata_key):
                unique_values.add(getattr(d.metadata, self.metadata_key))

        # Create a MetadataFilter for each unique value
        bins = [
            MetadataFilter(
                id=f"{self.metadata_key}_{str(value).zfill(3)}",
                key=self.metadata_key,
                value=value,
            )
            for value in unique_values
        ]
        bins.sort(key=lambda x: x.id)
        return bins


FrameFilterTypes = (
    MetadataFilter
    | FramePredicate
    | ComplexFrameFilter
    | DatapointIdFilter
    | AttributeFilter
    | TranscriptContainsFilter
)


class Frame:
    def __init__(
        self,
        data: list[Datapoint],
        filter: FrameFilterTypes | None,
        precomputed_judgments: list[list[Judgment]] | None = None,
    ):
        self._data, self._filter = data, filter
        self._judgments: list[list[Judgment | None]] | None = cast(
            list[list[Judgment | None]] | None, precomputed_judgments
        )
        self._matching_locs: list[tuple[str, int]] | None = None

        # Hashtable index for metadata filters
        self._metadata_index: dict[Any, list[str]] | None = None

    async def _init_metadata_index(self):
        if self._filter and isinstance(self._filter, MetadataFilter):
            self._metadata_index = {}
            for d in self._data:
                judgment = (await self._filter.apply([d]))[0][0]
                if judgment.matches:
                    value = getattr(d.metadata, self._filter.key)
                    self._metadata_index.setdefault(value, []).append(d.id)

    @property
    def filter(self) -> FrameFilterTypes | None:
        return self._filter

    def clear_judgments(self):
        self._judgments = None

    async def compute_judgments_and_locs(
        self, has_update: Callable[[], Awaitable[None]] | None = None
    ):
        """
        TARGET: these judgments need to be updated live.
        """
        if self._filter is None:
            # If no filter, create "match all" judgments
            self._judgments = [
                [
                    Judgment(
                        matches=True,
                        reason="No filter - matches everything",
                        data_id=d.id,
                    )
                ]
                for d in self._data
            ]
            return

        self._judgments: list[list[Judgment | None]] | None = []
        self._matching_locs: list[tuple[str, int]] | None = []
        lock = asyncio.Lock()

        async def _judgment_callback(data_index: int, attribute_index: int, judgment: Judgment):
            """Weird typing and null-checking thanks to pyright + no sleep"""

            async with lock:
                # Add to matching locs
                if judgment.matches:
                    if self._matching_locs is None:
                        self._matching_locs = []
                    self._matching_locs.append((judgment.data_id, attribute_index))

                # Dynamically grow the judgments list as needed (must be locked as the list structure is changing)
                while self._judgments is not None and len(self._judgments) <= data_index:
                    self._judgments.append([])
                while (
                    self._judgments is not None
                    and len(self._judgments[data_index]) <= attribute_index
                ):
                    self._judgments[data_index].append(None)

            # Set the judgment
            if self._judgments is not None:
                self._judgments[data_index][attribute_index] = judgment

            if has_update:
                await has_update()

        # Retrieve from metadata index if available
        # Perf gains will be more significant for *sparse* filters
        indexed_matching_data_ids: list[str] | None = None
        if (
            self._filter
            and isinstance(self._filter, MetadataFilter)
            and self._metadata_index is not None
        ):
            indexed_matching_data_ids = self._metadata_index[self._filter.value]

        # Finalize judgments and matching locs
        judgments = await self._filter.apply(
            self._data,
            indexed_matching_data_ids=indexed_matching_data_ids,
            judgment_callback=_judgment_callback,
        )
        self._judgments = cast(list[list[Judgment | None]], judgments)
        self._matching_locs = [
            (judgment.data_id, j)
            for judgments in self._judgments
            for j, judgment in enumerate(judgments)
            if judgment and judgment.matches
        ]

        return self._judgments

    async def get_judgments(self):
        return self._judgments

    async def get_matching_locs(self, compute_if_none: bool = True) -> list[tuple[str, int]]:
        """Get the datapoints that match the filter.

        Args:
            attribute_callback: Optional callback for streaming attribute extraction updates.
            assignment_callb    ack: Optional callback for streaming assignment updates.

        Returns:
            List of tuples (datapoint_id, judgment_index)
        """
        if compute_if_none and self._matching_locs is None:
            await self.compute_judgments_and_locs()
        assert self._matching_locs is not None
        return self._matching_locs


class DimState(BaseModel):
    dim: FrameDimension
    loading_clusters: bool = False
    loading_marginal: bool = False
    loading_marginal_callback: Callable[[], Awaitable[None]] | None = Field(
        default=None, exclude=True
    )


class FrameGrid(BaseModel):
    data: list[Datapoint]
    dims: list[FrameDimension]
    base_filter: FrameFilterTypes | None = None

    def __init__(
        self,
        data: list[Datapoint],
        dims: list[FrameDimension],
        base_filter: FrameFilterTypes | None = None,
    ):
        super().__init__(data=data, dims=dims, base_filter=base_filter)

        # Check that all dimensions have unique ids
        dim_ids = [dim.id for dim in self.dims]
        if len(dim_ids) != len(set(dim_ids)):
            raise ValueError(f"Dimensions must have unique IDs, got: {dim_ids}")

        self._all_data = self.data
        self._all_data_dict = {d.id: d for d in self.data}
        self._dim_states = {dim.id: DimState(dim=dim) for dim in self.dims}

        # Potential base filter for entire FG
        self._base_frame: Frame | None = (
            Frame(self._all_data, self.base_filter) if self.base_filter else None
        )

        # Map of dim_id -> bin_id -> marginal_indices
        self._marginals: dict[str, dict[str, Frame]] | None = None

        # Lock for thread safety
        self._lock = asyncio.Lock()

    def propagate_api_keys(self, llm_api_keys: LLMApiKeys):
        def _reach_all_predicates(filter: FrameFilterTypes):
            if isinstance(filter, FramePredicate):
                filter.llm_api_keys = llm_api_keys
            elif isinstance(filter, ComplexFrameFilter):
                for b in filter.filters:
                    _reach_all_predicates(b)

        for dim in self.dims:
            if dim.bins is None:
                continue
            for bin in dim.bins:
                _reach_all_predicates(bin)

    @property
    def all_data(self):
        return self._all_data

    @property
    def all_data_dict(self):
        return self._all_data_dict

    @property
    def dim_states(self):
        return list(self._dim_states.values())

    @property
    def base_frame(self):
        return self._base_frame

    def get_dim_state(self, dim_id: str):
        return self._dim_states.get(dim_id, None)

    def get_dim(self, dim_id: str):
        state = self._dim_states.get(dim_id, None)
        return None if state is None else state.dim

    #################
    # Serialization #
    #################

    @classmethod
    def from_json(cls, fpath: str):
        start = perf_counter()
        with open(fpath, "r") as f:
            json_str = f.read()
            json_str = json_str.replace("experiment_description", "intervention_description")
            json_str = json_str.replace("experiment_timestamp", "intervention_timestamp")
            fg = cls.model_validate_json(json_str)
        logger.info(f"Deserialized FrameGrid in {perf_counter() - start:.2f}s")
        return fg

    def to_json(self, fpath: str):
        start = perf_counter()
        with open(fpath, "w") as f:
            f.write(self.model_dump_json())
        logger.info(f"Serialized FrameGrid in {perf_counter() - start:.2f}s")

    ######################
    # Base frame getters #
    ######################

    async def get_base_frame_locs(self):
        async with self._lock:
            return await self._unlocked_get_base_frame_locs()

    async def get_base_data(self):
        async with self._lock:
            return await self._unlocked_get_base_data()

    async def _unlocked_get_base_frame_locs(self):
        return (
            (await self._base_frame.get_matching_locs())
            if self._base_frame
            else [(k, None) for k in self._all_data_dict.keys()]
        )

    async def _unlocked_get_base_data(
        self,
    ):
        base_locs = await self._unlocked_get_base_frame_locs()
        return [self._all_data_dict[k] for k, _ in base_locs]

    ###################
    # Marginalization #
    ###################

    async def compute_all_marginals(
        self,
        has_update: Callable[[], Awaitable[None]] | None = None,
    ):
        async with self._lock:
            await self._unlocked_set_marginals(None)
            assert self._marginals is not None
            await self._unlocked_populate_marginals(None, has_update=has_update)
            return self._marginals

    async def unlocked_get_all_marginals(self):
        return self._marginals

    async def marginalize(
        self,
        keep_dim_ids: list[str],
        map_fn: Callable[[Frame], Awaitable[Any]] | None = None,
    ):
        """
        Raises:
            ValueError: If any dimension has no bins defined.
        """

        async with self._lock:
            if self._marginals is None:
                await self._unlocked_set_marginals(keep_dim_ids)
                assert self._marginals is not None
                await self._unlocked_populate_marginals(keep_dim_ids)

            start = perf_counter()

            # Result variables
            flat_result: dict[tuple[tuple[str, str], ...], Any] = {}
            available_bins: dict[str, list[str]] = {}

            # Get the bins for each dimension
            bins_per_dim: list[list[tuple[str, str]]] = []
            for dim_id in keep_dim_ids:
                bins = self._dim_states[dim_id].dim.bins
                if bins is None:
                    raise ValueError(
                        f"Dimension {dim_id} has no bins defined. Call `compute_metadata_bins` or `compute_clusters` first."
                    )

                bin_ids = [bin.id for bin in bins]
                bins_per_dim.append([(dim_id, bin_id) for bin_id in bin_ids])
                available_bins[dim_id] = bin_ids

            # Iterate over the Cartesian product of the bins
            base_data_ids = set([i for i, _ in await self._unlocked_get_base_frame_locs()])
            for bin_combination in product(*bins_per_dim):
                filters: list[FrameFilterTypes] = []
                matching_ids_FN: list[set[str]] = []
                for dim_id, bin_id in bin_combination:
                    cur_marginal = self._marginals[dim_id][bin_id]

                    # Collect the datapoint IDs that match the current filter
                    matching_datapoint_ids = base_data_ids & set(
                        [i for i, _ in await cur_marginal.get_matching_locs()]
                    )
                    matching_ids_FN.append(matching_datapoint_ids)

                    # Add to filter list
                    assert cur_marginal.filter is not None, "Marginal should have a filter"
                    filters.append(cur_marginal.filter)

                judgments_N1 = _combine_filter_judgments_partial(matching_ids_FN, "and")
                matching_data = [
                    self._all_data_dict[judgment.data_id]
                    for judgments in judgments_N1
                    for judgment in judgments
                ]

                frame = Frame(
                    matching_data,
                    ComplexFrameFilter(filters=filters, op="and"),
                    precomputed_judgments=judgments_N1,
                )

                if map_fn is not None:
                    flat_result[bin_combination] = await map_fn(frame)
                else:
                    flat_result[bin_combination] = frame

            elapsed = perf_counter() - start
            time_str = f"{elapsed * 1000:.0f}ms" if elapsed < 1 else f"{elapsed:.2f}s"
            logger.info(
                f"Marginalization took {time_str} to compute {len(flat_result)} frames on {len(base_data_ids)} datapoints"
            )

            return flat_result, available_bins

    async def _unlocked_set_marginals(
        self,
        dim_ids: list[str] | None = None,
    ):
        """Computes the marginal views for the specified dimensions.

        Args:
            dim_ids: The dimensions to compute the marginal views for.
                If None, we compute the marginal views for all dimensions.
        Raises:
            ValueError: If any dimension doesn't have bins defined.
        """
        if self._marginals is None:
            self._marginals = {}

        cur_dims = [self._dim_states[dim_id].dim for dim_id in (dim_ids or self._dim_states.keys())]

        for dim in cur_dims:
            # Skip if we already have marginals for this dimension
            if dim.id in self._marginals:
                continue
            # Dimension must have bins defined
            if dim.bins is None:
                logger.warning(
                    f"Dimension `{dim.id}` has no bins defined. Call `compute_metadata_bins` or `compute_clusters` first. Skipping..."
                )
                continue

            # Set the marginal Frame of cur dimension
            self._marginals[dim.id] = await dim.get_frames(await self._unlocked_get_base_data())

    async def _unlocked_populate_marginals(
        self,
        dim_ids: list[str] | None,
        has_update: Callable[[], Awaitable[None]] | None = None,
    ):
        assert self._marginals, "Call compute_marginal_views first"

        cur_dims = [self._dim_states[dim_id].dim for dim_id in (dim_ids or self._dim_states.keys())]

        for dim in cur_dims:
            if dim.bins is None:
                logger.warning(f"Dimension `{dim.id}` has no bins defined, skipping...")
                continue

            dim_state = self._dim_states[dim.id]
            cb = dim_state.loading_marginal_callback
            dim_state.loading_marginal = True
            if cb is not None:
                await cb()

            # Compute all judgments together
            if len(dim.bins) <= 10:
                tasks = [
                    asyncio.create_task(
                        self._marginals[dim.id][bin.id].compute_judgments_and_locs(has_update)
                    )
                    for bin in dim.bins
                ]
                try:
                    await asyncio.gather(*tasks)
                except asyncio.CancelledError:
                    for task in tasks:
                        if not task.done():
                            task.cancel()

                    logger.info(
                        f"Cancelled judgment computation for dimension `{dim.id}` due to asyncio.CancelledError interrupt"
                    )
                    raise
            else:
                for bin in dim.bins:
                    await self._marginals[dim.id][bin.id].compute_judgments_and_locs(has_update)

            dim_state.loading_marginal = False
            if cb is not None:
                await cb()

    def _unlocked_invalidate_dimension_marginals(self, dim_id: str) -> None:
        """
        Invalidate cached marginals for a specific dimension.

        Args:
            dim_id: ID of the dimension whose marginals should be invalidated
        """
        if self._marginals and dim_id in self._marginals:
            del self._marginals[dim_id]

    #####################
    # Datapoint setters #
    #####################

    async def add_datapoints(
        self,
        datapoints: list[Datapoint],
    ) -> None:
        """
        Add new datapoints to the frame grid.
        This will invalidate all cached marginals since they need to be recomputed.

        Args:
            datapoints: List of new Datapoint objects to add to the grid
            attribute_callback: Optional callback for streaming attribute extraction updates.
            assignment_callback: Optional callback for streaming assignment updates.

        Raises:
            ValueError: If any of the new datapoints have IDs that conflict with existing ones
        """
        async with self._lock:
            # Check for ID conflicts
            conflicting_ids = set(d.id for d in datapoints) & set(self._all_data_dict.keys())
            if conflicting_ids:
                raise ValueError(f"Cannot add datapoints with duplicate IDs: {conflicting_ids}")

            # Add new datapoints
            self._all_data.extend(datapoints)
            self._all_data_dict.update({d.id: d for d in datapoints})

            # Update base frame if it exists
            if self._base_frame is not None:
                self._base_frame = Frame(self._all_data, self._base_frame.filter)

            # Clear all marginals since they need to be recomputed with new data
            self._marginals = None
            # Recompute metadata bins to ensure they are up to date
            await self._unlocked_recompute_metadata_bins()

    async def update_datapoint_content(
        self,
        datapoint_id: str,
        messages: list[ChatMessage] | None = None,
        metadata: TranscriptMetadata | None = None,
    ) -> None:
        """
        Update an existing datapoint with specified values while maintaining its identity.
        This will invalidate all cached marginals since they need to be recomputed.

        Args:
            datapoint_id: ID of the existing datapoint to update
            messages: Optional new messages to set
            metadata: Optional new metadata to set
        Raises:
            ValueError: If the datapoint_id is not found in the frame grid or if no updates are specified
        """
        async with self._lock:
            # Check if the datapoint exists
            if datapoint_id not in self._all_data_dict:
                raise ValueError(f"Datapoint with ID '{datapoint_id}' not found")

            # Check if any updates are specified
            if messages is None and metadata is None:
                raise ValueError("No updates specified")

            # Get the existing datapoint
            target_datapoint = self._all_data_dict[datapoint_id]

            # Update individual fields if specified
            if messages is not None:
                target_datapoint.obj.messages = messages.copy()
            if metadata is not None:
                target_datapoint.obj.metadata = metadata.model_copy()

            # Update base frame if it exists
            if self._base_frame is not None:
                self._base_frame.clear_judgments()

            # Clear all marginals since they need to be recomputed with updated data
            self._marginals = None

            # Recompute metadata bins to ensure they are up to date
            await self._unlocked_recompute_metadata_bins()

    async def update_base_filter(
        self,
        filter: FrameFilterTypes | None,
    ) -> None:
        """
        Update the base filter for the frame grid.
        This will invalidate all cached marginals since they need to be recomputed.

        Args:
            filter: New base filter to apply, or None to clear the filter
            attribute_callback: Optional callback for streaming attribute extraction updates.
            assignment_callback: Optional callback for streaming assignment updates.
        """
        async with self._lock:
            # Update the base frame with new filter
            self.base_filter = filter
            self._base_frame = Frame(self._all_data, filter) if filter else None

            # Remove all FramePredicate dimensions
            for dim_id in list(self._dim_states.keys()):
                if (
                    self._dim_states[dim_id].dim.attribute is not None
                ):  # FIXME(kevin): this is a hack
                    logger.info(f"Removing attribute dimension {dim_id} due to metadata update")
                    self._unlocked_delete_dimension(dim_id)

            # Clear all marginals since they need to be recomputed with new base data
            self._marginals = None
            # Recompute metadata bins to ensure they are up to date
            await self._unlocked_recompute_metadata_bins()

    #####################
    # Dimension setters #
    #####################

    async def compute_and_set_attributes_if_needed(
        self,
        attribute: str,
        attribute_callback: AttributeStreamingCallback | None = None,
        llm_api_keys: LLMApiKeys | None = None,
    ):
        """
        Compute the attributes for the given attribute if they are not already computed.
        """
        async with self._lock:
            data = await self._unlocked_get_base_data()
        extracted = await extract_attributes(
            data,
            attribute,
            attribute_callback=attribute_callback,
            llm_api_keys=llm_api_keys,
        )
        async with self._lock:
            for i, attr in enumerate(extracted):
                data[i].attributes[attribute] = attr or []

    async def recompute_metadata_bins(self):
        """
        Recomputes the metadata bins for all dimensions.

        Args:
            attribute_callback: Optional callback for streaming attribute extraction updates.
            assignment_callback: Optional callback for streaming assignment updates.
        """
        async with self._lock:
            await self._unlocked_recompute_metadata_bins()

    async def add_dimension(
        self,
        dim: FrameDimension,
        loading_marginal_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """
        Add a new dimension to the FrameGrid.

        Args:
            dim: The FrameDimension to add.
            loading_marginal_callback: Optional callback for marginal loading state changes

        Raises:
            ValueError: If the dimension's ID conflicts with an existing one.
        """
        async with self._lock:
            self._unlocked_add_dimension(dim, loading_marginal_callback)

    async def edit_bin(self, dim_id: str, bin_id: str, new_predicate: str) -> None:
        """
        Edit a specific bin's predicate within a dimension.

        Args:
            dim_id: ID of the dimension containing the bin
            bin_id: ID of the bin to edit
            new_predicate: New predicate to assign to the bin

        Raises:
            ValueError: If dimension or bin not found, or if bin is not a FramePredicate
        """
        async with self._lock:
            self._unlocked_edit_bin(dim_id, bin_id, new_predicate)

    async def replace_bins(
        self,
        dim_id: str,
        new_bins: Sequence[FrameFilterTypes],
    ) -> None:
        """
        Replace all bins in a dimension with new ones.

        Args:
            dim_id: ID of the dimension to update
            new_bins: List of new bins to replace existing ones

        Raises:
            ValueError: If dimension not found
        """
        async with self._lock:
            self._unlocked_replace_bins(dim_id, new_bins)

    async def delete_dimension(self, dim_id: str, ok_if_not_found: bool = False) -> None:
        """
        Delete a dimension from the frame grid.

        Args:
            dim_id: ID of the dimension to delete

        Raises:
            ValueError: If dimension not found
        """
        async with self._lock:
            self._unlocked_delete_dimension(dim_id, ok_if_not_found)

    async def delete_bin(self, dim_id: str, bin_id: str) -> None:
        """
        Delete a bin from a dimension in the frame grid.

        Args:
            dim_id: ID of the dimension containing the bin
            bin_id: ID of the bin to delete

        Raises:
            ValueError: If dimension or bin not found
        """
        async with self._lock:
            self._unlocked_delete_bin(dim_id, bin_id)

    async def _unlocked_recompute_metadata_bins(self):
        for dim_id in self._dim_states.keys():
            dim = self._dim_states[dim_id].dim
            if dim.metadata_key is not None:
                bins = await dim.compute_metadata_bins(await self._unlocked_get_base_data())
                self._unlocked_replace_bins(dim_id, bins)

    def _unlocked_add_dimension(
        self,
        dim: FrameDimension,
        loading_marginal_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if dim.id in self._dim_states:
            raise ValueError(f"Cannot add dimension with duplicate ID: '{dim.id}'")
        self._dim_states[dim.id] = DimState(
            dim=dim,
            loading_marginal_callback=loading_marginal_callback,
        )

    def _unlocked_edit_bin(self, dim_id: str, bin_id: str, new_predicate: str) -> None:
        # Get the dimension
        dim = self.get_dim(dim_id)
        if dim is None:
            raise ValueError(f"Dimension '{dim_id}' not found")
        if dim.bins is None:
            raise ValueError(f"Dimension '{dim_id}' has no bins defined")

        # Find and update the bin
        for i, bin in enumerate(dim.bins):
            if bin.id == bin_id:
                if not isinstance(bin, FramePredicate):
                    raise ValueError(f"Bin '{bin_id}' is not a FramePredicate and cannot be edited")

                # Create new bin with same attributes but new id and predicate
                new_bin = FramePredicate(
                    **(bin.model_dump() | {"id": new_predicate, "predicate": new_predicate})
                )
                dim.bins[i] = new_bin

                # Clear cached judgments for this dimension
                self._unlocked_invalidate_dimension_marginals(dim_id)
                return

        raise ValueError(f"Bin '{bin_id}' not found in dimension '{dim_id}'")

    def _unlocked_replace_bins(
        self,
        dim_id: str,
        new_bins: Sequence[FrameFilterTypes],
    ) -> None:
        # Get the dimension
        dim = self.get_dim(dim_id)
        if dim is None:
            raise ValueError(f"Dimension '{dim_id}' not found")

        # Replace bins
        dim.bins = list(new_bins)

        # Clear cached judgments for this dimension
        self._unlocked_invalidate_dimension_marginals(dim_id)

    def _unlocked_delete_dimension(self, dim_id: str, ok_if_not_found: bool = False) -> None:
        if not ok_if_not_found and dim_id not in self._dim_states:
            raise ValueError(f"Dimension '{dim_id}' not found")

        if dim_id in self._dim_states:
            del self._dim_states[dim_id]

            # Clear cached judgments for this dimension
            self._unlocked_invalidate_dimension_marginals(dim_id)
        else:
            logger.warning(f"Attempted to delete dimension {dim_id}, which did not exist")

    def _unlocked_delete_bin(self, dim_id: str, bin_id: str) -> None:
        if dim_id not in self._dim_states:
            raise ValueError(f"Dimension '{dim_id}' not found")

        dim = self._dim_states[dim_id].dim
        if dim.bins is None:
            raise ValueError(f"No bins defined in dimension '{dim_id}'")

        # Find and remove the bin
        bin_index = next((i for i, bin in enumerate(dim.bins) if bin.id == bin_id), -1)
        if bin_index == -1:
            raise ValueError(f"Bin '{bin_id}' not found in dimension '{dim_id}'")

        dim.bins.pop(bin_index)

        # Clear cached marginals for this dimension
        self._unlocked_invalidate_dimension_marginals(dim_id)


def _transpose_judgment_lists(
    lists_FNA: list[list[list[Judgment]]],
) -> list[list[list[Judgment]]]:  # type: ignore
    """
    Turns lists_FNA into lists_NAF by transposing dimensions (0, 2).

    Raises:
        ValueError: If the input lists have different shapes
    """
    if not lists_FNA:
        return []

    # Validate all lists have same shape
    shapes = [[len(lists_A) for lists_A in lists_NA] for lists_NA in lists_FNA]
    if not all(len(row) == len(shapes[0]) for row in shapes):
        raise ValueError("All input lists must have the same number of sublists")
    if not all(all(col == shapes[0][i] for col, i in zip(row, range(len(row)))) for row in shapes):
        raise ValueError("All sublists must have the same length")

    # Original logic, now safe to use
    return [[list(group) for group in zip(*rows)] for rows in zip(*lists_FNA)]


def _combine_filter_judgments_partial(
    matching_ids_FN: list[set[str]],
    op: Literal["and", "or"],
):
    if op == "and":
        matching_ids = set[str].intersection(*matching_ids_FN)
    elif op == "or":
        matching_ids = set[str].union(*matching_ids_FN)
    else:
        raise ValueError(f"Invalid operation: {op}")

    return [
        [Judgment(matches=True, reason="Matched intersection of filters", data_id=i)]
        for i in matching_ids
    ]


# add optional streaming parameter
async def _unlocked_compute_and_set_attributes_if_needed(
    data: list[Datapoint],
    attribute: str,
    attribute_callback: AttributeStreamingCallback | None = None,
    llm_api_keys: LLMApiKeys | None = None,
):
    # Only compute attributes for datapoints that don't already have them.
    need_attr = [i for i, d in enumerate(data) if attribute not in d.attributes]
    if not need_attr:
        return

    extracted = await extract_attributes(
        [data[i] for i in need_attr],
        attribute,
        attribute_callback=attribute_callback,
        llm_api_keys=llm_api_keys,
    )

    # Final update: once all results are in, update each datapoint.
    for i, attr in zip(need_attr, extracted):
        data[i].attributes[attribute] = attr or []


def parse_filter_dict(filter_dict: dict[str, Any]) -> FrameFilterTypes:
    if "type" not in filter_dict:
        raise ValueError("Filter dictionary must contain 'type' field")
    filter_type = filter_dict["type"]

    if filter_type == "metadata":
        return MetadataFilter(**filter_dict)
    elif filter_type == "predicate":
        return FramePredicate(**filter_dict)
    elif filter_type == "complex":
        # Recursively parse nested filters
        nested_filters = [parse_filter_dict(f) for f in filter_dict["filters"]]
        return ComplexFrameFilter(
            id=filter_dict.get("id", f"_complex_{str(uuid4())}"),
            filters=nested_filters,
            op=filter_dict["op"],
        )
    elif filter_type == "datapoint_id":
        return DatapointIdFilter(**filter_dict)
    elif filter_type == "attribute":
        return AttributeFilter(**filter_dict)
    elif filter_type == "transcript_contains":
        return TranscriptContainsFilter(**filter_dict)
    else:
        raise ValueError(f"Unknown filter type: {filter_type}")


# def _hash_datapoints(data: list[Datapoint]) -> str:
#     ts = perf_counter()
#     hash = hashlib.sha256(
#         "|".join(sorted([d.model_dump_json() for d in data])).encode()
#     ).hexdigest()
#     logger.info(f"Hashed {len(data)} datapoints in {perf_counter() - ts} seconds")
#     return hash
