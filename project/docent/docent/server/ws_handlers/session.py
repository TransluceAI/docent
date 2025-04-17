from uuid import uuid4

from docent.loader import EVALS
from docent.server.ws_handlers.util import ConnectionManager, WSMessage
from fastapi import WebSocket
from frames.frame import FrameDimension, FrameGrid
from frames.types import Datapoint


async def handle_create_session(
    fg_sessions: dict[str, FrameGrid], cm: ConnectionManager, websocket: WebSocket, msg: WSMessage
) -> str | None:
    """Creates a new FrameGrid session with datapoints from the given experiment IDs.

    Args:
        cm: The connection manager instance
        websocket: The WebSocket connection
        msg: The WebSocket message containing the create session request

    Returns:
        str | None: The ID of the created session if successful, None otherwise

    Raises:
        ValueError: If experiment_ids is missing or contains invalid IDs
    """

    eval_ids = msg.payload["eval_ids"]

    if missing_ids := [eval_id for eval_id in eval_ids if eval_id not in EVALS]:
        raise ValueError(f"eval_ids {missing_ids} not found")

    # Gather all datapoints from all experiments
    datapoints: list[Datapoint] = []
    for eval_id in eval_ids:
        datapoints.extend([Datapoint.from_transcript(t) for t in EVALS[eval_id]])

    fg_id, fg = str(uuid4()), FrameGrid(data=datapoints, dims=[])

    # Add sample_id dimension and compute bins
    dim_sample = FrameDimension(id="sample_id", bins=None, metadata_key="sample_id")
    bins = await dim_sample.compute_metadata_bins(datapoints)
    await fg.add_dimension(dim_sample)
    await fg.replace_bins("sample_id", bins)

    # Add experiment_id dimension and compute bins
    dim_experiment = FrameDimension(id="experiment_id", bins=None, metadata_key="experiment_id")
    bins = await dim_experiment.compute_metadata_bins(datapoints)
    await fg.add_dimension(dim_experiment)
    await fg.replace_bins("experiment_id", bins)

    fg_sessions[fg_id] = fg
    cm.register(fg_id, websocket)
    await cm.send(websocket, WSMessage(action="session_joined", payload={"id": fg_id}))

    return fg_id


async def handle_join_session(
    fg_sessions: dict[str, FrameGrid], cm: ConnectionManager, websocket: WebSocket, msg: WSMessage
) -> str | None:
    """Handle a request to join an existing FrameGrid session.

    Args:
        cm: The connection manager instance
        websocket: The WebSocket connection
        msg: The WebSocket message containing the join session request

    Returns:
        str | None: The ID of the joined session if successful, None otherwise

    Raises:
        ValueError: If session_id is missing or invalid
    """
    session_id = msg.payload.get("session_id")
    if not session_id:
        raise ValueError("session_id is required")

    if session_id not in fg_sessions:
        raise ValueError(f"Session {session_id} not found")

    cm.register(session_id, websocket)
    await cm.send(websocket, WSMessage(action="session_joined", payload={"id": session_id}))

    return session_id


async def handle_set_api_keys(
    cm: ConnectionManager, websocket: WebSocket, session_id: str, msg: WSMessage
):
    """Handle setting API keys for a session."""
    payload = msg.payload
    anthropic_key: str | None = payload.get("anthropic_key")
    openai_key: str | None = payload.get("openai_key")

    if not anthropic_key and not openai_key:
        await cm.send(
            websocket,
            WSMessage(action="error", payload={"message": "At least one API key must be provided"}),
        )
        return

    await cm.set_api_keys(session_id, anthropic_key, openai_key)
    await cm.send(
        websocket,
        WSMessage(action="api_keys_updated", payload={"message": "API keys updated successfully"}),
    )


async def handle_get_api_keys(cm: ConnectionManager, websocket: WebSocket, session_id: str):
    """Handle getting API keys for a session."""
    api_keys = cm.get_api_keys(session_id)
    await cm.send(websocket, WSMessage(action="api_keys", payload=dict(api_keys)))
