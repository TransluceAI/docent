import json
from pathlib import Path

from env_util import ENV
from frames.transcript import Transcript, TranscriptMetadata
from llm_util.types import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ToolCall,
)
from log_util import get_logger
from tqdm.auto import tqdm

logger = get_logger(__name__)

if ENV.EVAL_LOGS_DIR is None:
    raise ValueError("EVAL_LOGS_DIR is not set")
LOG_DIR_PREFIX = ENV.EVAL_LOGS_DIR

OH_SWE_BENCH_LOGS: dict[str, str] = {
    "oh-sweb": f"{LOG_DIR_PREFIX}/oh-sweb",
}


def load_openhands_swebench_experiment(experiment_id: str, fpath: str) -> list[Transcript]:
    """Loads SWE-Bench transcripts from OpenHands format.

    Args:
        experiment_id: The ID of the experiment.
        fpath: The path to the directory containing the transcript files.

    Returns:
        A list of Transcript objects.
    """
    logger.info("Loading %s from %s", experiment_id, fpath)

    transcripts: list[Transcript] = []
    for file in tqdm(
        list(Path(fpath).glob("*.json")), desc="Loading OpenHands SWEBench transcripts"
    ):
        with open(file, "r") as f:
            data = json.load(f)

        messages: list[ChatMessage] = []

        for msg in data["history"]:
            source = msg["source"]
            action, observation = msg.get("action"), msg.get("observation")
            tc_metadata = msg.get("tool_call_metadata")

            if action and observation:
                raise ValueError("Action and observation cannot both be present")

            if source == "user":
                cur_msg = ChatMessageUser(content=msg["message"])
            elif source == "agent":
                if not tc_metadata:
                    logger.warning(
                        f"Tool call metadata is required for agent messages. Message:\n{json.dumps(msg, indent=2)}"
                    )
                    continue
                if action:  # Assistant with tool call
                    response = tc_metadata["model_response"]["choices"][0]["message"]
                    tool_calls: list[ToolCall] = []
                    for tc in response["tool_calls"]:
                        try:
                            tc_args = json.loads(tc["function"]["arguments"])
                            parse_error = None
                        except Exception as e:
                            tc_args = {"arguments": tc["function"]["arguments"]}
                            parse_error = str(e)

                        tool_calls.append(
                            ToolCall(
                                id=tc["id"],
                                function=tc["function"]["name"],
                                arguments=tc_args,
                                type="function",
                                parse_error=parse_error,
                            )
                        )
                    cur_msg = ChatMessageAssistant(
                        content=response["content"] or "", tool_calls=tool_calls
                    )
                elif observation:  # Tool response
                    cur_msg = ChatMessageTool(
                        tool_call_id=tc_metadata["tool_call_id"],
                        function=tc_metadata["function_name"],
                        content=msg["content"],
                    )
                else:
                    raise ValueError("Neither observation nor action present")

            else:
                raise ValueError(f"Unknown source: {source}")

            messages.append(cur_msg)

        # Build metadata
        metadata = TranscriptMetadata(
            task_id="swe_bench_verified",
            sample_id=data["instance_id"],
            epoch_id=1,  # Default to epoch 1
            experiment_id=experiment_id,
            intervention_description=None,
            intervention_timestamp=None,
            intervention_index=None,
            model=data["metadata"]["llm_config"]["model"],
            task_args={},
            is_loading_messages=False,
            scores={"resolved": data["report"]["resolved"]},
            default_score_key="resolved",
            additional_metadata={},
            scoring_metadata=data["instance"],
        )

        # Create the transcript
        transcript = Transcript(
            messages=messages,
            metadata=metadata,
        )

        transcripts.append(transcript)

    return transcripts


def load_oh_swe_bench() -> list[Transcript]:
    result: list[Transcript] = []
    for experiment_id, fpath in OH_SWE_BENCH_LOGS.items():
        result.extend(load_openhands_swebench_experiment(experiment_id, fpath))
    return result
