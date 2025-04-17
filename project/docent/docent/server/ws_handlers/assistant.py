import asyncio
import hashlib
import json
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

from docent.assistant.chat import make_single_tasst_system_prompt
from docent.assistant.summarizer import (
    HighLevelAction,
    LowLevelAction,
    ObservationType,
    group_actions_into_high_level_steps,
    interesting_agent_observations,
    summarize_agent_actions,
    summarize_intended_solution,
)
from docent.assistant.tdiff import (
    ComparisonResult,
    DiffResult,
    compare_transcripts,
    diff_transcripts,
)
from docent.server.ws_handlers.util import ConnectionManager, WSMessage
from fastapi import WebSocket
from frames.frame import Datapoint, Frame, FrameGrid, parse_filter_dict
from frames.transcript import Citation, parse_citations_single_transcript
from llm_util.prod_llms import get_llm_completions_async
from llm_util.types import LLMOutput
from log_util import get_logger
from pydantic import BaseModel

logger = get_logger(__name__)


class TaChatMessage(TypedDict):
    role: str
    content: str
    citations: list[Citation]


class TASession(BaseModel):
    """Transcript Assistant session state"""

    id: str
    messages: list[TaChatMessage]
    datapoint_ids: list[str]


TA_SESSIONS: dict[str, TASession] = {}  # session_id -> TASession


async def handle_create_ta_session(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage
):
    """Handle create_ta_session action by creating a new transcript assistant session.

    Expected payload:
    {
        "base_filter": dict | None  # Optional metadata filter to apply
    }
    """
    base_filter_raw = cast(dict[str, Any] | None, msg.payload.get("base_filter"))
    base_filter = parse_filter_dict(base_filter_raw) if base_filter_raw else None

    # Create a frame with the filter to get matching datapoints
    if base_filter:
        frame = Frame(data=fg.all_data, filter=base_filter)
        matching_locs = await frame.get_matching_locs()
        datapoint_ids = [i for i, _ in matching_locs]
    else:
        # If no filter provided, use the base frame of the framegrid
        matching_locs = await fg.get_base_frame_locs()
        datapoint_ids = [i for i, _ in matching_locs]

    datapoints = [fg.all_data_dict[i] for i in datapoint_ids]
    if not datapoints:
        raise ValueError("No matching transcripts found")

    assert len(datapoints) == 1, "Only one transcript is supported for TA sessions"

    # Create system prompt with all matching transcripts
    system_prompt = make_single_tasst_system_prompt(datapoints[0])

    # Generate session ID and store session
    session_id = str(uuid4())
    TA_SESSIONS[session_id] = TASession(
        id=session_id,
        messages=[{"role": "system", "content": system_prompt, "citations": []}],
        datapoint_ids=datapoint_ids,
    )

    await cm.send(
        websocket,
        WSMessage(
            action="ta_session_created",
            payload={
                "session_id": session_id,
                "num_transcripts": len(datapoints),
            },
        ),
    )


async def handle_ta_message(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
):
    """Handle ta_message action by sending a message to the transcript assistant.

    Expected payload:
    {
        "session_id": str,
        "message": str,
    }
    """
    session_id = msg.payload["session_id"]
    message = msg.payload["message"]

    session = TA_SESSIONS[session_id]
    api_keys = cm.get_api_keys(socket_fg_id)

    # Add user message to session
    to_send = session.messages + [{"role": "user", "content": message, "citations": []}]

    # Immediately send back the initial message state
    await cm.send(
        websocket,
        WSMessage(
            action="ta_message_chunk",
            payload={
                "text": "",
                "messages": to_send,
            },
        ),
    )

    async def llm_callback(batch_index: int, llm_output: LLMOutput):
        text = llm_output.first_text
        if text:
            # Create current state of assistant message
            current_assistant_message = {
                "role": "assistant",
                "content": text,
                "citations": parse_citations_single_transcript(text),
            }
            # Send chunk with full message history
            await cm.send(
                websocket,
                WSMessage(
                    action="ta_message_chunk",
                    payload={
                        "text": text,
                        "messages": to_send + [current_assistant_message],
                    },
                ),
            )

    output = (
        await get_llm_completions_async(
            [cast(list[dict[str, Any]], to_send)],
            # model_category="smart",
            model_category="reasoning_smart",
            # reasoning_effort="high",
            max_new_tokens=8192,
            timeout=180.0,
            streaming_callback=llm_callback,
            use_cache=True,
            llm_api_keys=api_keys,
        )
    )[0]

    if output.first_text:
        final_messages = to_send + [
            {
                "role": "assistant",
                "content": output.first_text,
                "citations": parse_citations_single_transcript(output.first_text),
            }
        ]
        await cm.send(
            websocket,
            WSMessage(
                action="ta_message_complete",
                payload={
                    "messages": final_messages,
                },
            ),
        )

        # After generation completes, update the session with the new messages
        session.messages = final_messages


async def handle_summarize_transcript(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
):
    """Handle summarize_transcript action by generating summaries for a transcript.

    Expected payload:
    {
        "datapoint_id": str,  # ID of the transcript to summarize
        "summary_type": str,  # One of: "task", "solution", "actions"
    }
    """
    datapoint_id = msg.payload["datapoint_id"]
    summary_type = msg.payload["summary_type"]

    if not summary_type or summary_type not in ["task", "solution", "actions"]:
        raise ValueError("summary_type must be one of: task, solution, actions")

    # Get the transcript
    if datapoint_id not in fg.all_data_dict:
        raise ValueError(f"Transcript with ID {datapoint_id} not found")

    datapoint = fg.all_data_dict[datapoint_id]
    transcript = datapoint.obj

    api_keys = cm.get_api_keys(socket_fg_id)

    # Generate appropriate summary based on type
    if summary_type == "solution":

        async def solution_callback(summary: str, parts: list[str]):
            await cm.send(
                websocket,
                WSMessage(
                    action="summarize_transcript_update",
                    payload={
                        "summary": summary,
                        "parts": parts,
                        "type": "solution",
                        "datapoint_id": datapoint_id,
                    },
                ),
            )

        await summarize_intended_solution(
            transcript, streaming_callback=solution_callback, api_keys=api_keys
        )
        await cm.send(
            websocket,
            WSMessage(
                action="summarize_transcript_complete",
                payload={
                    "type": "solution",
                    "datapoint_id": datapoint_id,
                },
            ),
        )
    elif summary_type == "actions":
        prev_actions_hash: str | None = None
        low_level_actions: list[LowLevelAction] = []
        high_level_actions: list[HighLevelAction] = []
        prev_observations_hash: str | None = None
        agent_observations: list[ObservationType] = []

        async def actions_callback(actions: list[LowLevelAction]):
            nonlocal prev_actions_hash, low_level_actions

            # Store the actions for later use with high-level steps
            low_level_actions = actions

            # Hash the actions to compare with previous hash
            actions_json = json.dumps(actions, sort_keys=True)
            current_hash = hashlib.sha256(actions_json.encode()).hexdigest()

            # Only send if hash is different from previous hash
            if current_hash != prev_actions_hash:
                await cm.send(
                    websocket,
                    WSMessage(
                        action="summarize_transcript_update",
                        payload={
                            "actions": {
                                "low_level": actions,
                                "high_level": high_level_actions,
                                "observations": agent_observations,
                            },
                            "type": "actions",
                            "datapoint_id": datapoint_id,
                        },
                    ),
                )
                prev_actions_hash = current_hash

        async def high_level_actions_callback(actions: list[HighLevelAction]):
            nonlocal high_level_actions, prev_actions_hash

            high_level_actions = actions

            # Send an update with both low and high level actions
            actions_json = json.dumps(
                {
                    "low_level": low_level_actions,
                    "high_level": actions,
                    "observations": agent_observations,
                },
                sort_keys=True,
            )
            current_hash = hashlib.sha256(actions_json.encode()).hexdigest()

            if current_hash != prev_actions_hash:
                await cm.send(
                    websocket,
                    WSMessage(
                        action="summarize_transcript_update",
                        payload={
                            "actions": {
                                "low_level": low_level_actions,
                                "high_level": actions,
                                "observations": agent_observations,
                            },
                            "type": "actions",
                            "datapoint_id": datapoint_id,
                        },
                    ),
                )
                prev_actions_hash = current_hash

        async def observations_callback(observations: list[ObservationType]):
            nonlocal agent_observations, prev_observations_hash

            agent_observations = observations

            # Send an update with all three types of data
            actions_json = json.dumps(
                {
                    "low_level": low_level_actions,
                    "high_level": high_level_actions,
                    "observations": observations,
                },
                sort_keys=True,
            )
            current_hash = hashlib.sha256(actions_json.encode()).hexdigest()

            if current_hash != prev_observations_hash:
                await cm.send(
                    websocket,
                    WSMessage(
                        action="summarize_transcript_update",
                        payload={
                            "actions": {
                                "low_level": low_level_actions,
                                "high_level": high_level_actions,
                                "observations": observations,
                            },
                            "type": "actions",
                            "datapoint_id": datapoint_id,
                        },
                    ),
                )
                prev_observations_hash = current_hash

        # Run agent observations concurrently with the other tasks
        observations_task = asyncio.create_task(
            interesting_agent_observations(
                transcript, streaming_callback=observations_callback, api_keys=api_keys
            )
        )
        # First get the low-level actions
        low_level_actions = await summarize_agent_actions(
            transcript, streaming_callback=actions_callback, api_keys=api_keys
        )
        # Then group them into high-level steps
        if low_level_actions:
            await group_actions_into_high_level_steps(
                low_level_actions,
                transcript,
                streaming_callback=high_level_actions_callback,
                api_keys=api_keys,
            )

        await summarize_agent_actions(
            transcript, streaming_callback=actions_callback, api_keys=api_keys
        )
        # Wait for observations task to complete
        agent_observations = await observations_task

        await cm.send(
            websocket,
            WSMessage(
                action="summarize_transcript_complete",
                payload={
                    "type": "actions",
                    "datapoint_id": datapoint_id,
                },
            ),
        )
    else:
        raise ValueError(f"Unknown summary type: {summary_type}")


class TranscriptDiffNode(TypedDict):
    id: str
    data: Any

    datapoint_id: str
    action_unit_idx: int
    starting_block_idx: int


class TranscriptDiffEdge(TypedDict):
    id: str
    source: str
    target: str
    type: Literal["chain", "exact_match", "near_match"]
    explanation: str


def _create_graph(
    datapoint_1: Datapoint,
    summary_1: dict[int, LowLevelAction],
    datapoint_2: Datapoint,
    summary_2: dict[int, LowLevelAction],
    all_diff_results: dict[int, list[DiffResult | None]],
):
    nodes: list[TranscriptDiffNode] = []
    edges: list[TranscriptDiffEdge] = []

    # Create nodes
    for datapoint, summary in [(datapoint_1, summary_1), (datapoint_2, summary_2)]:
        for unit_idx, action in summary.items():
            nodes.append(
                {
                    "id": f"{datapoint.id}-{unit_idx}",
                    "data": action,
                    "datapoint_id": datapoint.id,
                    "action_unit_idx": unit_idx,
                    "starting_block_idx": datapoint.obj.units_of_action[unit_idx][0],
                }
            )

    # Add chain edges for both datapoints
    for idx, (datapoint, summary) in enumerate(
        [(datapoint_1, summary_1), (datapoint_2, summary_2)]
    ):
        transcript_num = idx + 1
        for i in range(len(summary) - 1):
            action_1, action_2 = summary[i], summary[i + 1]
            unit_idx_1, unit_idx_2 = action_1["action_unit_idx"], action_2["action_unit_idx"]
            edges.append(
                {
                    "id": f"{datapoint.id}-edge-{unit_idx_1}-{unit_idx_2}",
                    "source": f"{datapoint.id}-{unit_idx_1}",
                    "target": f"{datapoint.id}-{unit_idx_2}",
                    "type": "chain",
                    "explanation": f"Sequential action in transcript {transcript_num}: {i} → {i+1}",
                }
            )

    # Add matching edges for matching action units
    for t1_idx, diff_results in all_diff_results.items():
        for diff_result in diff_results:
            if diff_result and diff_result["matches"]:
                for match_info in diff_result["matches"]:
                    t2_idx = match_info["index"]
                    match_type = (
                        "exact_match" if match_info["match_type"] == "exact" else "near_match"
                    )
                    explanation = match_info.get("explanation", "")

                    # Add edge between matching action units
                    edges.append(
                        {
                            "id": f"match-{datapoint_1.id}-{t1_idx}-{datapoint_2.id}-{t2_idx}",
                            "source": f"{datapoint_1.id}-{t1_idx}",
                            "target": f"{datapoint_2.id}-{t2_idx}",
                            "type": match_type,
                            "explanation": explanation,
                        }
                    )

    return nodes, edges


async def handle_diff_transcripts(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
):
    """Handle diff_transcripts action by comparing two transcripts.

    Expected payload:
    {
        "datapoint_id_1": str,  # ID of the first transcript
        "datapoint_id_2": str,  # ID of the second transcript
    }
    """
    datapoint_1 = fg.all_data_dict[msg.payload["datapoint_id_1"]]
    datapoint_2 = fg.all_data_dict[msg.payload["datapoint_id_2"]]

    async def compare_callback(batch_index: int, results: ComparisonResult):
        await cm.send(
            websocket,
            WSMessage(
                action="compare_transcripts_update",
                payload=cast(dict[str, Any], results),
            ),
        )

    # First get textual comparison
    asyncio.create_task(
        compare_transcripts(datapoint_1.obj, datapoint_2.obj, streaming_callback=compare_callback)
    )

    summary_1: dict[int, LowLevelAction] = {}
    summary_2: dict[int, LowLevelAction] = {}
    diff_result: dict[int, list[DiffResult | None]] = {}

    async def _create_graph_and_send():
        nonlocal summary_1, summary_2, diff_result
        nodes, edges = _create_graph(datapoint_1, summary_1, datapoint_2, summary_2, diff_result)
        await cm.send(
            websocket,
            WSMessage(
                action="transcript_diff_result",
                payload={
                    "nodes": nodes,
                    "edges": edges,
                },
            ),
        )

    prev_s1_hash, prev_s2_hash = None, None

    async def actions_callback(actions: list[LowLevelAction], which_summary: Literal["1", "2"]):
        nonlocal summary_1, summary_2, prev_s1_hash, prev_s2_hash

        # Update summary
        cur_summary = summary_1 if which_summary == "1" else summary_2
        for action in actions:
            cur_summary[action["action_unit_idx"]] = action

        # Hash the summaries to compare with previous hashes
        cur_json = json.dumps(cur_summary, sort_keys=True)
        cur_hash = hashlib.sha256(cur_json.encode()).hexdigest()
        cur_prev_hash = prev_s1_hash if which_summary == "1" else prev_s2_hash

        # Only send if hash differs
        if cur_prev_hash is None or cur_hash != cur_prev_hash:
            await _create_graph_and_send()
            if which_summary == "1":
                prev_s1_hash = cur_hash
            else:
                prev_s2_hash = cur_hash

    async def diff_callback(batch_index: int, results: list[DiffResult | None]):
        nonlocal diff_result
        diff_result[batch_index] = results
        await _create_graph_and_send()

    api_keys = cm.get_api_keys(socket_fg_id)

    # Dispatch tasks to compute all these in parallel
    await asyncio.gather(
        summarize_agent_actions(
            datapoint_1.obj,
            streaming_callback=lambda actions: actions_callback(actions, "1"),
            api_keys=api_keys,
        ),
        summarize_agent_actions(
            datapoint_2.obj,
            streaming_callback=lambda actions: actions_callback(actions, "2"),
            api_keys=api_keys,
        ),
        diff_transcripts(
            datapoint_1.obj, datapoint_2.obj, completion_callback=diff_callback, api_keys=api_keys
        ),
    )


async def rewrite_search_query(query: str) -> str:
    prompt = f"""
A user is trying to search over a large number of agent transcripts where an AI tries to solve a task; here is their query:

{query}

Please rewrite this query to be more specific and with examples so that, given the rewritten query and an agent transcript, another AI can determine whether they match. I recommend queries that are of the form "<specific query>, including but not limited to <example 1>, ..." Note that the rewritten query should NOT feel like a prompt to an AI but rather like a query to a search engine.

If you find the query too vague, you can suggest them be more specific.

Return the rewritten query (or request) and nothing else.
""".strip()

    # Send the prompt to the LLM
    output = (
        await get_llm_completions_async(
            [
                [
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ]
            ],
            model_category="smart",
            max_new_tokens=2048,
            timeout=60.0,
            use_cache=True,
        )
    )[0]

    return output.first_text or ""
