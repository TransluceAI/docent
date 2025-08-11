import json
import tarfile
from pathlib import Path
from typing import Any, List, Tuple

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
from docent.data_models.transcript import Transcript

logger = get_logger(__name__)


def _parse_openhands_swebench_data(data: dict[str, Any]) -> AgentRun:
    """Parse OpenHands SWE-Bench JSON data into an AgentRun object.

    Args:
        data: The parsed JSON data from an OpenHands SWE-Bench file.

    Returns:
        A single AgentRun object.
    """
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
                cur_msg = AssistantMessage(content=response["content"] or "", tool_calls=tool_calls)
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
    metadata: dict[str, Any] = {
        "benchmark_id": "swe_bench_verified",
        "task_id": data["instance_id"],
        "model": data["metadata"]["llm_config"]["model"],
        "scores": {"resolved": data["report"]["resolved"]},
        "scoring_metadata": data["instance"],
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

    return agent_run


async def process_oh_swe_bench_file(file_path: Path) -> Tuple[List[AgentRun], dict[str, Any]]:
    """
    Process an OpenHands SWE-Bench file and extract agent runs.

    Args:
        file_path: Path to the file or .tgz archive containing OpenHands SWE-Bench data

    Returns:
        tuple: (agent_runs, file_info) where file_info contains metadata about the file
    """
    if file_path.suffix.lower() in [".tgz", ".tar.gz"]:
        agent_runs: list[AgentRun] = []
        json_files = []

        with tarfile.open(file_path, "r:gz") as tar:
            json_members = [
                member
                for member in tar.getmembers()
                if not member.name.startswith(".")
                and member.name.endswith(".json")
                and member.isfile()
            ]
            json_files = [member.name for member in json_members]

            # Process each JSON file from the tarball
            for member in tqdm(json_members):
                extracted_file = tar.extractfile(member)
                if extracted_file is not None:
                    data = json.load(extracted_file)
                    agent_run = _parse_openhands_swebench_data(data)
                    agent_runs.append(agent_run)

        file_info = {
            "filename": file_path.name,
            "type": "tgz_archive",
            "file_count": len(json_files),
            "total_runs": len(agent_runs),
        }
    else:
        # Process single file directly
        if not file_path.suffix.lower() == ".json":
            raise ValueError("File must be a .json, .tgz, or .tar.gz file")

        with open(file_path, "r") as f:
            data = json.load(f)

        agent_runs = [_parse_openhands_swebench_data(data)]

        file_info = {
            "filename": file_path.name,
            "type": "single_file",
            "total_runs": len(agent_runs),
        }

    return agent_runs, file_info
