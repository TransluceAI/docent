import json

from docent._frames.transcript import Transcript, TranscriptMetadata
from docent._llm_util.types import ChatMessage, ToolCall, parse_chat_message
from docent._log_util import get_logger

logger = get_logger(__name__)


LOG_DIR_PREFIX = "/home/ubuntu/artifacts/mengk/inspect_logs"
TAU_BENCH_LOGS: dict[str, str] = {
    "tb_airline": f"{LOG_DIR_PREFIX}/sonnet-35-new-airline.json",
}


def load_tau_bench_experiment(experiment_id: str, fpath: str) -> list[Transcript]:
    """Loads TauBench transcripts from the specified file path.

    Args:
        experiment_id: The ID of the experiment.
        fpath: The path to the JSON file containing the transcript data.

    Returns:
        A list of Transcript objects representing the conversations.
    """
    logger.info("Loading %s from %s", experiment_id, fpath)

    with open(fpath, "r") as f:
        data = json.load(f)

    transcripts: list[Transcript] = []
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
        metadata = TranscriptMetadata(
            task_id=task_id,
            sample_id=str(sample_id),
            original_sample_id_type="str" if isinstance(sample_id, str) else "int",
            epoch_id=1,  # Default to epoch 1 TODO(kevin): this is a hack.
            experiment_id=experiment_id,
            intervention_description=None,
            intervention_timestamp=None,
            intervention_index=None,
            model="sonnet-35-new",  # Default model name TODO(kevin): this is a hack.
            task_args={},
            is_loading_messages=False,
            scores=scores,
            default_score_key=default_score_key,
            additional_metadata=info,
            scoring_metadata=info["reward_info"],
        )

        # Create the transcript
        transcript = Transcript(
            messages=messages,
            metadata=metadata,
        )

        transcripts.append(transcript)

    return transcripts


def load_tau_bench() -> list[Transcript]:
    result: list[Transcript] = []
    for experiment_id, fpath in TAU_BENCH_LOGS.items():
        result.extend(load_tau_bench_experiment(experiment_id, fpath))
    return result
