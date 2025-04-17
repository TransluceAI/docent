import re
from time import perf_counter
from typing import Any, Awaitable, Callable, cast

from fastapi import WebSocket
from frames.frame import Frame, FrameGrid

from docent.server.ws_handlers.util import ConnectionManager, WSMessage


async def _count_map_fn(frame: Frame, _: Any):
    return len(await frame.get_matching_locs())


async def _locs_map_fn(frame: Frame, _: Any):
    return await frame.get_matching_locs()


async def _judgments_map_fn(frame: Frame, _: Any):
    return await frame.compute_judgments_and_locs()


async def _intervention_descriptions_map_fn(frame: Frame, fg: FrameGrid):
    matching_locs = await frame.get_matching_locs()
    if not matching_locs:
        return None

    results: set[str] = set()
    for k, _ in matching_locs:
        d = fg.all_data_dict[k]
        if d.metadata.intervention_description:
            results.add(d.metadata.intervention_description)

    return list(results)


async def _stats_map_fn(frame: Frame, fg: FrameGrid):
    """Calculate mean score with 95% confidence interval for each score key.

    Returns:
        Dict containing statistics for each score key.
        Each key has mean score, confidence interval half-width, and sample size.
        Returns None if there are no matching indices.
    """
    matching_locs = await frame.get_matching_locs()
    if not matching_locs:
        return {"mean": None, "ci": None, "n": 0}

    # First pass: collect all available score keys and their values
    all_outcomes: dict[str, list[float | None]] = {}
    for k, _ in matching_locs:
        d = fg.all_data_dict[k]
        for score_key, score_value in d.metadata.scores.items():
            cur_list = all_outcomes.setdefault(score_key, [])
            cur_list.append(float(score_value) if not d.metadata.is_loading_messages else None)

    # Calculate statistics for each score key
    results: dict[str, dict[str, float | None]] = {}
    for score_key, outcomes in all_outcomes.items():
        if outcomes and any(outcome is None for outcome in outcomes):
            results[score_key] = {"mean": None, "ci": None, "n": len(outcomes)}
            continue

        # Calculate mean
        outcomes = cast(list[float], outcomes)
        n = len(outcomes)
        mean = sum(outcomes) / n

        # Calculate 95% CI using normal approximation
        # z-score for 95% CI is 1.96
        if n > 1:  # Need at least 2 samples for std
            std = (sum((x - mean) ** 2 for x in outcomes) / (n - 1)) ** 0.5
            ci = 1.96 * std / (n**0.5)
        else:
            # With 1 sample, we can't calculate CI
            ci = 0

        results[score_key] = {"mean": mean, "ci": ci, "n": n}

    # The frontend expects some aggregate data, otherwise it won't show the sample/experiment.
    if not results:
        results["default"] = {"mean": None, "ci": None, "n": len(matching_locs)}

    return results


def _format_bin_combination(bin_combination: tuple[tuple[str, str], ...]) -> str:
    return "|".join(",".join(pair) for pair in bin_combination)


async def _regex_snippets_map_fn(frame: Frame, regex_query: str) -> dict[str, list[dict[str, Any]]]:
    """Generate snippets for regex matches within frame data."""
    if not regex_query:
        return {}

    pattern = re.compile(regex_query, re.IGNORECASE)
    snippets_dict: dict[str, list[dict[str, Any]]] = {}

    for datapoint in frame.data:
        # Find all matches - no limit
        matches = list(pattern.finditer(datapoint.text))
        if matches:
            snippets_dict[datapoint.id] = []
            for match in matches:
                start, end = match.span()

                # Increase context window size significantly - show much more context
                context_len = 500
                context_before_start = max(0, start - context_len)
                context_after_end = min(len(datapoint.text), end + context_len)

                # Calculate match indices relative to the snippet start
                relative_match_start = start - context_before_start
                relative_match_end = end - context_before_start

                snippet_text = datapoint.text[context_before_start:context_after_end]

                # Add ellipsis if context is truncated
                prefix = "... " if context_before_start > 0 else ""
                suffix = " ..." if context_after_end < len(datapoint.text) else ""

                # Adjust relative indices if prefix is added
                if prefix:
                    relative_match_start += len(prefix)
                    relative_match_end += len(prefix)

                final_snippet = prefix + snippet_text + suffix

                snippet_obj = {
                    "snippet": final_snippet,
                    "match_start": relative_match_start,
                    "match_end": relative_match_end,
                }
                snippets_dict[datapoint.id].append(snippet_obj)

    return snippets_dict


async def handle_marginalize(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage
):
    """[Getter] Compute marginals for specified dimensions if unavailable, then send to the client.

    Raises:
        ValueError: If payload is incomplete, map_type is invalid, or if any dimension has no bins defined.
    """
    request_type = msg.payload["request_type"]
    keep_dim_ids = msg.payload["keep_dim_ids"]
    map_type = msg.payload["map_type"]

    # Unpack the map function
    map_fn_impl = None
    if map_type == "count":
        map_fn_impl = _count_map_fn
    elif map_type == "stats":
        map_fn_impl = _stats_map_fn
    elif map_type == "judgments":
        map_fn_impl = _judgments_map_fn
    elif map_type == "locs":
        map_fn_impl = _locs_map_fn
    elif map_type == "intervention_descriptions":
        map_fn_impl = _intervention_descriptions_map_fn
    elif map_type == "regex_snippets":
        # Get the regex query from the payload
        regex_query = msg.payload.get("regex_query", "")

        # Create a closure to capture the regex query
        async def _map_fn_with_regex(frame: Frame, _: Any) -> dict[str, list[dict[str, Any]]]:
            return await _regex_snippets_map_fn(frame, regex_query)

        map_fn_impl = _map_fn_with_regex
    else:
        raise ValueError("Invalid map_type")

    # Verify all dimensions exist
    for dim_id in keep_dim_ids:
        if not any(d.dim.id == dim_id for d in fg.dim_states):
            raise ValueError(f"Dimension {dim_id} not found")

    # Get marginals for these dimensions
    def _map_fn(frame: Frame):
        return map_fn_impl(frame, fg)

    marginals, available_bins = await fg.marginalize(keep_dim_ids, map_fn=_map_fn)

    # Special handling for regex_snippets to preserve the full object structure
    if map_type == "regex_snippets":
        # For regex snippets, we want to flatten the results by datapoint ID
        flat_snippets = {}
        for bin_combination, snippets_dict in marginals.items():
            # Add each datapoint's snippets to our flattened dictionary
            for datapoint_id, snippets in snippets_dict.items():
                # Simply overwrite any existing snippets for simplicity
                # (removes potential duplicate snippets from different bins)
                flat_snippets[datapoint_id] = snippets

        await cm.send(
            websocket,
            WSMessage(
                action="specific_marginals",
                payload={
                    "request_type": request_type,
                    "bins": available_bins,
                    "marginals": flat_snippets,  # Send the flattened snippets by datapoint ID
                },
            ),
        )
    else:
        # Regular handling for other map types
        await cm.send(
            websocket,
            WSMessage(
                action="specific_marginals",
                payload={
                    "request_type": request_type,
                    "bins": available_bins,
                    "marginals": {
                        _format_bin_combination(bin_combination): count
                        for bin_combination, count in marginals.items()
                    },
                },
            ),
        )


async def send_dimensions(cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid):
    """[Getter] Send dimension and bins to the client."""
    await cm.send(
        websocket,
        WSMessage(action="dimensions", payload={"dimensions": fg.dim_states}),
    )


async def send_all_marginals(
    cm: ConnectionManager,
    websocket: WebSocket,
    fg: FrameGrid,
):
    """[Getter] Compute marginals if unavailable, then send to the client.

    Raises:
        ValueError: If any dimension has no bins defined.
    """

    full_marginals = await fg.unlocked_get_all_marginals()
    if full_marginals:
        marginals = {
            dim_id: {
                bin_id: judgments
                for bin_id, frame in frames.items()
                if (judgments := await frame.get_judgments()) is not None
            }
            for dim_id, frames in full_marginals.items()
        }
        await cm.send(
            websocket,
            WSMessage(action="marginals", payload={"marginals": marginals}),
        )


async def compute_and_send_all_marginals(
    cm: ConnectionManager,
    websocket: WebSocket,
    fg: FrameGrid,
    has_update: Callable[[], Awaitable[None]] | None = None,
):
    """[Getter] Compute marginals if unavailable, then send to the client.

    Raises:
        ValueError: If any dimension has no bins defined.
    """

    full_marginals = await fg.compute_all_marginals(has_update)
    marginals = {
        dim_id: {bin_id: await frame.get_judgments() for bin_id, frame in frames.items()}
        for dim_id, frames in full_marginals.items()
    }
    await cm.send(
        websocket,
        WSMessage(action="marginals", payload={"marginals": marginals}),
    )


async def send_base_filter(cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid):
    """[Getter] Send the current base filter to the client."""
    base_filter = fg.base_filter

    await cm.send(
        websocket,
        WSMessage(
            action="base_filter",
            payload={"filter": base_filter},
        ),
    )


async def send_datapoints_updated(
    cm: ConnectionManager, websocket: WebSocket, datapoint_ids: list[str] | None
):
    """[Getter] Indicate that datapoints have been updated.
    Let `datapoint_ids` be None to trigger an update for all datapoints."""
    await cm.send(
        websocket,
        WSMessage(
            action="datapoints_updated",
            payload={"datapoint_ids": datapoint_ids},
        ),
    )


async def send_datapoint(
    cm: ConnectionManager,
    websocket: WebSocket,
    fg: FrameGrid,
    message: WSMessage,
    is_diff: bool = False,
):
    """[Getter] Send single datapoint to the client.

    Raises:
        ValueError: If payload is incomplete, or if datapoint_id is not found.
    """
    datapoint_id = message.payload["datapoint_id"]
    data = fg.all_data_dict[datapoint_id]

    await cm.send(
        websocket,
        WSMessage(
            action="datapoint" if not is_diff else "diff_datapoint",
            payload={"datapoint": data},
        ),
    )


async def send_datapoint_metadata(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, message: WSMessage
):
    """[Getter] Send metadata for a number of datapoints to the client.

    Raises:
        ValueError: If payload is incomplete, or if any datapoint_id is not found.
    """
    datapoint_ids = message.payload["datapoint_ids"]
    metadata = {
        datapoint_id: fg.all_data_dict[datapoint_id].obj.metadata for datapoint_id in datapoint_ids
    }

    await cm.send(
        websocket,
        WSMessage(
            action="datapoint_metadata",
            payload={"metadata": metadata},
        ),
    )


async def handle_get_state(
    cm: ConnectionManager,
    websocket: WebSocket,
    fg: FrameGrid,
    has_update: Callable[[], Awaitable[None]] | None = None,
):
    """[Getter] Send all state components to the client."""

    await send_base_filter(cm, websocket, fg)
    await send_dimensions(cm, websocket, fg)
    ts = perf_counter()
    await compute_and_send_all_marginals(cm, websocket, fg, has_update)
    print(f"Computed and sent all marginals in {perf_counter() - ts:.2f}s")

    # Send data grouped by experiments
    await handle_marginalize(
        cm,
        websocket,
        fg,
        WSMessage(
            action="marginalize",
            payload={
                "keep_dim_ids": ["sample_id", "experiment_id"],
                "map_type": "stats",
                "request_type": "exp_stats",
            },
        ),
    )
    await handle_marginalize(
        cm,
        websocket,
        fg,
        WSMessage(
            action="marginalize",
            payload={
                "keep_dim_ids": ["sample_id", "experiment_id"],
                "map_type": "locs",
                "request_type": "exp_locs",
            },
        ),
    )

    # Stat marginals for samples and experiments
    await handle_marginalize(
        cm,
        websocket,
        fg,
        WSMessage(
            action="marginalize",
            payload={
                "keep_dim_ids": ["sample_id"],
                "map_type": "stats",
                "request_type": "per_sample_stats",
            },
        ),
    )
    await handle_marginalize(
        cm,
        websocket,
        fg,
        WSMessage(
            action="marginalize",
            payload={
                "keep_dim_ids": ["experiment_id"],
                "map_type": "stats",
                "request_type": "per_experiment_stats",
            },
        ),
    )

    # Send intervention descriptions
    await handle_marginalize(
        cm,
        websocket,
        fg,
        WSMessage(
            action="marginalize",
            payload={
                "keep_dim_ids": ["experiment_id"],
                "map_type": "intervention_descriptions",
                "request_type": "intervention_descriptions",
            },
        ),
    )

    await send_datapoints_updated(cm, websocket, None)
