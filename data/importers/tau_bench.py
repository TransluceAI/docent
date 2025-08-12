import json
from pathlib import Path
from typing import Any, List, Tuple

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat import ChatMessage, ToolCall, parse_chat_message
from docent.data_models.transcript import Transcript


async def process_tau_bench_file(file_path: Path) -> Tuple[List[AgentRun], dict[str, Any]]:
    """
    Process a TauBench file and extract agent runs.

    Args:
        file_path: Path to the JSON file containing TauBench data

    Returns:
        tuple: (agent_runs, file_info) where file_info contains metadata about the file
    """
    if not file_path.suffix.lower() == ".json":
        raise ValueError("File must be a .json file")

    with open(file_path, "r") as f:
        data = json.load(f)

    agent_runs: list[AgentRun] = []
    for sample_idx, sample in enumerate(data):
        # Extract the conversation from the trajectory
        traj = sample["traj"]
        info = sample["info"]

        # Convert trajectory messages to ChatMessage objects
        messages: list[ChatMessage] = []
        for msg in traj:
            role = msg.get("role")
            content = msg.get("content", "")
            tool_calls_data = msg.get("tool_calls")
            tool_call_id = msg.get("tool_call_id")

            # Create a message data dictionary
            message_data = {
                "role": role,
                "content": content,
            }

            # For tool messages, include the tool name
            if role == "tool":
                message_data["name"] = msg.get("name")
                message_data["tool_call_id"] = tool_call_id

            # For assistant messages, include tool calls if present
            if role == "assistant" and tool_calls_data:
                # Convert tool calls to the expected format
                parsed_tool_calls: list[ToolCall] = []
                for tc in tool_calls_data:
                    tool_call = ToolCall(
                        id=tc.get("id"),
                        function=tc.get("function", {}).get("name"),
                        arguments=tc.get("function", {}).get("arguments", {}),
                        type="function",
                        parse_error=None,
                    )
                    parsed_tool_calls.append(tool_call)

                message_data["tool_calls"] = parsed_tool_calls

            # Parse the message into the appropriate type
            chat_message = parse_chat_message(message_data)
            messages.append(chat_message)

        # Extract metadata from the sample
        task_id = info["task"]["user_id"]
        sample_id = sample_idx
        scores = {"reward": round(sample["reward"], 3)}

        # Build metadata
        metadata: dict[str, Any] = {
            "benchmark_id": task_id,
            "task_id": str(sample_id),
            "model": "sonnet-35-new",  # Default model name TODO(kevin): this is a hack.
            "scores": scores,
            "additional_metadata": info,
            "scoring_metadata": info["reward_info"],
        }

        # Create the transcript and wrap in AgentRun
        transcript = Transcript(
            messages=messages,
            metadata=metadata,
        )

        agent_run = AgentRun(
            transcripts={"default": transcript},
            metadata=metadata,
        )

        agent_runs.append(agent_run)

    file_info = {
        "filename": file_path.name,
        "total_samples": len(data),
        "total_runs": len(agent_runs),
    }

    return agent_runs, file_info
