import json
from pathlib import Path
from typing import Any

from pydantic import Field
from tqdm.auto import tqdm

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat import (
    AssistantMessage,
    ChatMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from docent.data_models.metadata import BaseAgentRunMetadata
from docent.data_models.transcript import Transcript

logger = get_logger(__name__)

LOG_DIR_PREFIX = "/Users/mengk/Code/luce-artifacts/mengk/inspect_logs"
OH_SWE_BENCH_LOGS: dict[str, str] = {
    "oh-sweb": f"{LOG_DIR_PREFIX}/oh-sweb",
}


class OpenHandsSWEBenchMetadata(BaseAgentRunMetadata):
    benchmark_id: str = Field(
        description="The benchmark that the task belongs to", default="swe_bench_verified"
    )
    task_id: str = Field(description="The task within the benchmark that the agent is solving")
    model: str = Field(description="The LLM used by the agent")
    scoring_metadata: dict[str, Any] = Field(
        description="Additional metadata about the scoring process"
    )


def load_openhands_swebench_experiment(experiment_id: str, fpath: str) -> list[AgentRun]:
    """Loads SWE-Bench transcripts from OpenHands format.

    Args:
        experiment_id: The ID of the experiment.
        fpath: The path to the directory containing the transcript files.

    Returns:
        A list of AgentRun objects.
    """
    logger.info("Loading %s from %s", experiment_id, fpath)

    agent_runs: list[AgentRun] = []
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
                cur_msg = UserMessage(content=msg["message"])
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
                    cur_msg = AssistantMessage(
                        content=response["content"] or "", tool_calls=tool_calls
                    )
                elif observation:  # Tool response
                    cur_msg = ToolMessage(
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
        metadata = OpenHandsSWEBenchMetadata(
            benchmark_id="swe_bench_verified",
            task_id=data["instance_id"],
            model=data["metadata"]["llm_config"]["model"],
            scores={"resolved": data["report"]["resolved"]},
            default_score_key="resolved",
            scoring_metadata=data["instance"],
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


def load_oh_swe_bench() -> list[AgentRun]:
    """Loads all OpenHands SWE-Bench transcripts.

    Returns:
        A list of AgentRun objects.
    """
    result: list[AgentRun] = []
    for experiment_id, fpath in OH_SWE_BENCH_LOGS.items():
        result.extend(load_openhands_swebench_experiment(experiment_id, fpath))
    return result
