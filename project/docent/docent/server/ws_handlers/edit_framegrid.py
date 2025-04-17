import asyncio
from typing import Any, Callable, TypedDict, cast
from uuid import uuid4

from docent.server.ws_handlers.send_framegrid import (
    compute_and_send_all_marginals,
    handle_get_state,
    send_all_marginals,
    send_dimensions,
)
from docent.server.ws_handlers.util import ConnectionManager, WSMessage
from fastapi import WebSocket
from frames.clustering.cluster_assigner import ASSIGNERS, DEFAULT_ASSIGNER
from frames.clustering.multi_round_clustering import cluster_from_initial_proposal
from frames.frame import (
    ClusterFeedback,
    FrameDimension,
    FrameGrid,
    FramePredicate,
    parse_filter_dict,
)
from frames.transcript import Citation, parse_citations_single_transcript
from log_util import get_logger
from pydantic import BaseModel

logger = get_logger(__name__)


class ClusterState(BaseModel):
    """State for an in-progress clustering operation"""

    dim_id: str
    callback: Callable[[int | str | None], None]


class AttributeWithCitation(TypedDict):
    attribute: str
    citations: list[Citation]


class StreamedAttribute(TypedDict):
    datapoint_id: str | None
    attribute_id: str | None
    attributes: list[AttributeWithCitation] | None
    num_datapoints_done: int
    num_datapoints_total: int


# Add to top of file with other globals
CLUSTER_SESSIONS: dict[str, ClusterState] = {}  # cluster_id -> ClusterState


async def handle_compute_attributes(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
):
    """[Setter] Get the attributes for a dimension."""
    attribute = msg.payload["attribute"]
    num_datapoints_done, num_datapoints_total = 0, len(await fg.get_base_data())
    lock = asyncio.Lock()

    # Stream initial state
    await cm.send(
        websocket,
        WSMessage(
            action="compute_attributes_update",
            payload=cast(
                dict[str, Any],
                StreamedAttribute(
                    datapoint_id=None,
                    attribute_id=None,
                    attributes=None,
                    num_datapoints_done=num_datapoints_done,
                    num_datapoints_total=num_datapoints_total,
                ),
            ),
        ),
    )

    async def ws_attribute_streaming_callback(
        datapoint_id: str, attribute_id: str, attributes: list[str] | None
    ) -> None:
        nonlocal num_datapoints_done

        if attributes is None:
            return

        async with lock:
            num_datapoints_done += 1
            cur_num_datapoints_done = num_datapoints_done
            cur_num_datapoints_total = num_datapoints_total

        payload: StreamedAttribute = {
            "datapoint_id": datapoint_id,
            "attribute_id": attribute_id,
            "attributes": (
                [
                    {
                        "attribute": attr,
                        "citations": parse_citations_single_transcript(attr),
                    }
                    for attr in attributes
                ]
            ),
            "num_datapoints_done": cur_num_datapoints_done,
            "num_datapoints_total": cur_num_datapoints_total,
        }

        await cm.send(
            websocket,
            WSMessage(
                action="compute_attributes_update",
                payload=cast(dict[str, Any], payload),
            ),
        )

    await fg.compute_and_set_attributes_if_needed(
        attribute,
        attribute_callback=ws_attribute_streaming_callback,
        llm_api_keys=cm.get_api_keys(socket_fg_id),
    )
    num_matching = sum(
        [
            len(d.attributes[attribute])
            for d in await fg.get_base_data()
            if attribute in d.attributes
        ]
    )
    await cm.send(
        websocket,
        WSMessage(
            action="compute_attributes_complete",
            payload={"dim_id": attribute, "num_matching": num_matching},
        ),
    )

    # Refresh client state
    await handle_get_state(cm, websocket, fg)


async def handle_recluster_dimension(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
):
    """[Setter] Recluster a dimension."""
    dim_id = msg.payload["dim_id"]
    dim = fg.get_dim(dim_id)
    if dim is None:
        raise ValueError(f"Dimension {dim_id} not found")

    # Collect attributes
    attribs: list[str] = []
    attribute = dim.attribute
    if attribute is None:
        raise ValueError("Dimension has no attribute")
    for d in await fg.get_base_data():
        attribs.extend(d.attributes[attribute])

    # Collect existing clusters
    bins = dim.bins
    if bins is None:
        raise ValueError("Dimension has no bins")
    existing_predicates = [c.predicate for c in bins if isinstance(c, FramePredicate)]

    # Improve MECE-ness
    results = await cluster_from_initial_proposal(
        attribs,
        attribute,
        existing_predicates,
        ASSIGNERS[DEFAULT_ASSIGNER],
        llm_api_keys=cm.get_api_keys(socket_fg_id),
        num_rounds=1,
    )

    # Replace bins
    await fg.replace_bins(
        dim_id,
        [
            FramePredicate(
                id=p,
                predicate=p,
                attribute=attribute,
                backend=DEFAULT_ASSIGNER,
                llm_api_keys=cm.get_api_keys(socket_fg_id),
            )
            for p in results
        ],
    )

    # Send updated state
    await handle_get_state(cm, websocket, fg)


async def handle_cluster_dimension(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
):
    """[Setter] Create clusters for a dimension."""
    dim_id = msg.payload["dim_id"]
    dim = fg.get_dim(dim_id)
    if dim is None:
        raise ValueError(f"Dimension {dim_id} not found")

    feedback: str | None = msg.payload.get("feedback")
    if feedback:
        assert dim.bins is not None
        bin_predicates = [c.predicate for c in dim.bins if isinstance(c, FramePredicate)]
        new_feedback = ClusterFeedback(
            clusters=bin_predicates,
            feedback=feedback,
        )
    else:
        new_feedback = None

    # define a callback that updates the frontend
    num_datapoints_done, num_datapoints_total = 0, len(await fg.get_base_data())

    async def ws_attribute_streaming_callback(
        datapoint_id: str, attribute_id: str, attributes: list[str] | None
    ) -> None:
        nonlocal num_datapoints_done

        if attributes is None:
            return

        payload: StreamedAttribute = {
            "datapoint_id": datapoint_id,
            "attribute_id": attribute_id,
            "attributes": (
                [
                    {
                        "attribute": attr,
                        "citations": parse_citations_single_transcript(attr),
                    }
                    for attr in attributes
                ]
            ),
            "num_datapoints_done": num_datapoints_done,
            "num_datapoints_total": num_datapoints_total,
        }

        await cm.send(
            websocket,
            WSMessage(
                action="compute_attributes_update",
                payload=cast(dict[str, Any], payload),
            ),
        )

    # Send new dim state indicating that clusters are being loaded
    dim_state = fg.get_dim_state(dim_id)
    assert dim_state is not None, "dim was already defined, this cannot happen"
    dim_state.loading_clusters = True
    await send_dimensions(cm, websocket, fg)

    # Create clusters with websocket interaction asynchronously
    clusters = await dim.compute_clusters(
        await fg.get_base_data(),
        picking_strategy="first",
        attribute_callback=ws_attribute_streaming_callback,
        n_clusters=1,
        new_feedback=new_feedback,
        llm_api_keys=cm.get_api_keys(socket_fg_id),
    )

    # Replace bins and send dimensions immediately
    await fg.replace_bins(dim_id, clusters)
    dim_state.loading_clusters = False
    await send_dimensions(cm, websocket, fg)

    # To stream judgments, poll the marginals until handle_get_state is done
    task = asyncio.create_task(handle_get_state(cm, websocket, fg))
    try:
        while not task.done():
            await send_all_marginals(cm, websocket, fg)
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        task.cancel()
        raise

    await task  # Make sure task is done


async def handle_cluster_dimension_complex(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
):
    """[Setter] Create clusters for a dimension."""
    dim_id = msg.payload.get("dim_id")
    if dim_id is None:
        raise ValueError("dim_id is required")

    dim = fg.get_dim(dim_id)
    if dim is None:
        raise ValueError(f"Dimension {dim_id} not found")

    cluster_session_id = str(uuid4())

    # define a callback that updates the frontend
    num_datapoints_done, num_datapoints_total = 0, len(await fg.get_base_data())

    async def ws_attribute_streaming_callback(
        datapoint_id: str, attribute_id: str, attributes: list[str] | None
    ) -> None:
        nonlocal num_datapoints_done

        num_datapoints_done += 1
        payload: StreamedAttribute = {
            "datapoint_id": datapoint_id,
            "attribute_id": attribute_id,
            "attributes": (
                [
                    {
                        "attribute": attr,
                        "citations": parse_citations_single_transcript(attr),
                    }
                    for attr in attributes
                ]
                if attributes is not None
                else None
            ),
            "num_datapoints_done": num_datapoints_done,
            "num_datapoints_total": num_datapoints_total,
        }

        await cm.send(
            websocket,
            WSMessage(
                action="compute_attributes_update",
                payload=cast(dict[str, Any], payload),
            ),
        )

    async def ws_picking_callback(proposals: list[list[str]]) -> int | str | None:
        """Callback that sends proposals to client and waits for response"""

        await cm.send(
            websocket,
            WSMessage(
                action="cluster_proposals",
                payload={"cluster_session_id": cluster_session_id, "proposals": proposals},
            ),
        )

        # Create Future to store response
        future: asyncio.Future[int | str | None] = asyncio.Future()

        # Generate cluster ID and store state
        CLUSTER_SESSIONS[cluster_session_id] = ClusterState(
            dim_id=dim_id, callback=future.set_result
        )

        try:
            # Wait for response via Future
            return await future
        finally:
            # Clean up state
            if cluster_session_id in CLUSTER_SESSIONS:
                del CLUSTER_SESSIONS[cluster_session_id]

    # Send new dim state indicating that clusters are being loaded
    dim_state = fg.get_dim_state(dim_id)
    assert dim_state is not None, "dim was already defined, this cannot happen"
    dim_state.loading_clusters = True
    await send_dimensions(cm, websocket, fg)

    # Create clusters with websocket interaction asynchronously
    cluster_task = asyncio.create_task(
        dim.compute_clusters(
            await fg.get_base_data(),
            picking_strategy="callback",
            picking_callback=ws_picking_callback,
            attribute_callback=ws_attribute_streaming_callback,
            llm_api_keys=cm.get_api_keys(socket_fg_id),
        )
    )

    # Wait for completion in background and handle result/errors
    async def handle_cluster_result():
        clusters = await cluster_task
        dim_state.loading_clusters = False

        await fg.replace_bins(dim_id, clusters)
        logger.info("Initial clusters proposed, now improving MECE...")

        # Second step: improve MECE
        base_data = await fg.get_base_data()
        attribs: list[str] = []
        attribute = dim_state.dim.attribute
        assert attribute is not None
        for d in base_data:
            attribs.extend(d.attributes[attribute])
        results = await cluster_from_initial_proposal(
            attribs,
            attribute,
            [c.predicate for c in clusters],
            ASSIGNERS[DEFAULT_ASSIGNER],
            llm_api_keys=cm.get_api_keys(socket_fg_id),
        )

        # Replace bins
        await fg.replace_bins(
            dim_id,
            [
                FramePredicate(
                    id=pred,
                    predicate=pred,
                    attribute=attribute,
                    backend=DEFAULT_ASSIGNER,
                    llm_api_keys=cm.get_api_keys(socket_fg_id),
                )
                for pred in results
                if pred != "_residual"
            ],
        )

        # Send everything because dimensions, marginals, and attributes may have changed
        await handle_get_state(cm, websocket, fg)

    # Start the handler but don't wait for it
    asyncio.create_task(handle_cluster_result())


async def handle_cluster_response(cm: ConnectionManager, websocket: WebSocket, msg: WSMessage):
    """Handle cluster_response action."""
    cluster_id = msg.payload.get("cluster_id")
    if not cluster_id or cluster_id not in CLUSTER_SESSIONS:
        raise ValueError("Invalid or missing cluster_id")

    state = CLUSTER_SESSIONS[cluster_id]
    choice = msg.payload.get("choice")
    feedback = msg.payload.get("feedback")

    if feedback is not None:
        state.callback(feedback)
    elif choice is not None:
        state.callback(int(choice))
    else:
        state.callback(None)


async def handle_edit_bin(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage
):
    """[Setter] Update a FramePredicate bin's predicate in a dimension.

    Raises:
        ValueError: If payload is incomplete, or (dim_id, bin_id) is not a FramePredicate.
    """
    dim_id = msg.payload["dim_id"]
    bin_id = msg.payload["bin_id"]
    new_predicate = msg.payload["new_predicate"]

    await fg.edit_bin(dim_id, bin_id, new_predicate)

    await send_dimensions(cm, websocket, fg)
    await compute_and_send_all_marginals(cm, websocket, fg)


async def handle_delete_dimension(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage
):
    """[Setter] Remove a dimension from the frame grid.

    Raises:
        ValueError: If payload is incomplete, or dimension does not exist.
    """
    dim_id = msg.payload["dim_id"]
    await fg.delete_dimension(dim_id, ok_if_not_found=True)

    await send_dimensions(cm, websocket, fg)
    await compute_and_send_all_marginals(cm, websocket, fg)


async def handle_delete_bin(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage
):
    """[Setter] Remove a bin from a dimension in the frame grid.

    Raises:
        ValueError: If payload is incomplete, or (dim_id, bin_id) does not exist.
    """
    dim_id = msg.payload["dim_id"]
    bin_id = msg.payload["bin_id"]
    await fg.delete_bin(dim_id, bin_id)

    await send_dimensions(cm, websocket, fg)
    await compute_and_send_all_marginals(cm, websocket, fg)


async def handle_update_base_filter(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage
):
    """[Setter] Update the base filter of the frame grid.

    Raises:
        ValueError: If payload is incomplete.
    """
    filter_raw = msg.payload.get("filter")
    filter = parse_filter_dict(filter_raw) if filter_raw else None

    # Update the base filter and invalidate caches
    await fg.update_base_filter(filter)

    # Send updated state
    await handle_get_state(cm, websocket, fg)


async def handle_add_dimension(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
):
    """[Setter] Add a dimension to the frame grid.

    Raises:
        ValueError: If payload is incomplete, or if dim_id = attribute conflicts with an existing dimension.
    """
    attribute = msg.payload["attribute"]
    bins: list[str] | None = msg.payload.get("bins")

    if attribute is None:
        raise ValueError("attribute is required")

    dim = FrameDimension(
        id=attribute,
        bins=(
            [
                FramePredicate(
                    id=pred,
                    predicate=pred,
                    attribute=attribute,
                    llm_api_keys=cm.get_api_keys(socket_fg_id),
                )
                for pred in bins
            ]
            if bins is not None
            else None
        ),
        attribute=attribute,
    )
    await fg.add_dimension(
        dim,
        loading_marginal_callback=lambda: send_dimensions(cm, websocket, fg),
    )

    await send_dimensions(cm, websocket, fg)
    if dim.bins is not None:
        await compute_and_send_all_marginals(cm, websocket, fg)
