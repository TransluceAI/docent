import json
from typing import Any

from pydantic import Field

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun, BaseAgentRunMetadata
from docent.data_models.chat import ChatMessage, ToolCall, parse_chat_message
from docent.data_models.transcript import Transcript

logger = get_logger(__name__)


LOG_DIR_PREFIX = "/Users/mengk/Code/luce-artifacts/mengk/inspect_logs"
TAU_BENCH_LOGS: dict[str, str] = {
    "tb_airline": f"{LOG_DIR_PREFIX}/sonnet-35-new-airline.json",
}


class TauBenchMetadata(BaseAgentRunMetadata):
    benchmark_id: str = Field(
        description="The benchmark that the task belongs to", default="tau_bench"
    )
    task_id: str = Field(description="The task within the benchmark that the agent is solving")
    model: str = Field(description="The LLM used by the agent")
    additional_metadata: dict[str, Any] = Field(description="Additional metadata about the task")
    scoring_metadata: dict[str, Any] | None = Field(
        description="Additional metadata about the scoring process"
    )


def load_tau_bench_experiment(experiment_id: str, fpath: str) -> list[AgentRun]:
    """Loads TauBench transcripts from the specified file path.

    Args:
        experiment_id: The ID of the experiment.
        fpath: The path to the JSON file containing the transcript data.

    Returns:
        A list of AgentRun objects representing the conversations.
    """
    logger.info("Loading %s from %s", experiment_id, fpath)

    with open(fpath, "r") as f:
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
        default_score_key = "reward"

        # Build metadata
        metadata = TauBenchMetadata(
            benchmark_id=task_id,
            task_id=str(sample_id),
            model="sonnet-35-new",  # Default model name TODO(kevin): this is a hack.
            scores=scores,
            default_score_key=default_score_key,
            additional_metadata=info,
            scoring_metadata=info["reward_info"],
        )

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

    return agent_runs


def load_tau_bench() -> list[AgentRun]:
    """Loads all TauBench transcripts.

    Returns:
        A list of AgentRun objects representing the conversations.
    """
    result: list[AgentRun] = []
    for experiment_id, fpath in TAU_BENCH_LOGS.items():
        agent_runs = load_tau_bench_experiment(experiment_id, fpath)
        result.extend(agent_runs)
    return result
