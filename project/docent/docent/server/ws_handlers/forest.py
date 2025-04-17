from docent.forest import TranscriptForest
from docent.server.ws_handlers.util import ConnectionManager, WSMessage
from fastapi import WebSocket
from frames.frame import FrameGrid
from log_util import get_logger

logger = get_logger(__name__)


def _make_forest_for_sample(fg: FrameGrid, sample_id: str | int):
    # Create a TranscriptForest from the FrameGrid data
    forest = TranscriptForest()

    # Filter and add transcripts with the matching sample_id
    at_least_one_transcript = False
    for d in fg.data:
        # Cast sample_id: str | int to the same type as d_sample_id for proper comparison
        d_sample_id = d.obj.metadata.sample_id
        if isinstance(d_sample_id, int):
            sample_id = int(sample_id)
        else:
            sample_id = str(sample_id)

        if d_sample_id == sample_id:
            forest.add_transcript(
                d.id,
                {},  # Empty environment config
                d.obj.messages,
                metadata=d.obj.metadata.model_dump()
                | {"forest_label": d.obj.metadata.intervention_description},
                compute_derivations=False,
            )
            at_least_one_transcript = True

    forest.recompute_all_derivations()

    if not at_least_one_transcript:
        raise ValueError(f"No transcripts found with sample_id: {sample_id}")

    return forest


async def handle_get_merged_experiment_tree(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage
) -> None:
    sample_id = msg.payload.get("sample_id")
    if not sample_id:
        raise ValueError("sample_id is required")

    forest = _make_forest_for_sample(fg, sample_id)

    # Build the merged experiment tree
    G, experiment_to_transcripts = forest.build_merged_experiment_tree()
    nodes, edges = G.export()

    # Send the result back to the client
    await cm.send(
        websocket,
        WSMessage(
            action="get_merged_experiment_tree_result",
            payload={
                "sample_id": sample_id,
                "nodes": nodes,
                "edges": edges,
                "experiment_to_transcripts": experiment_to_transcripts,
            },
        ),
    )


async def handle_get_transcript_derivation_tree(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage
) -> None:
    sample_id = msg.payload.get("sample_id")
    if not sample_id:
        raise ValueError("sample_id is required")

    forest = _make_forest_for_sample(fg, sample_id)

    # Build the transcript derivation tree
    G = forest.build_transcript_derivation_tree()
    nodes, edges = G.export()

    # Send the result back to the client
    await cm.send(
        websocket,
        WSMessage(
            action="get_transcript_derivation_tree_result",
            payload={
                "sample_id": sample_id,
                "nodes": nodes,
                "edges": edges,
            },
        ),
    )
