import json
from pathlib import Path
from typing import Any

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat import ChatMessage, parse_chat_message
from docent.data_models.metadata import InspectAgentRunMetadata
from docent.data_models.transcript import Transcript

logger = get_logger(__name__)

O3_LOGS = {
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/05/ad14cf0e.json": "Time_elapsed",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/05/9073f351.json": "Random_seed_2",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/05/d731afd7.json": "Random_seed_1",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/05/83496f36.json": "MacBook_Pro",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/12/1733796f.json": "Yap_score_2",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/05/deb53916.json": "Yap_score_1",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/07/e25da076.json": "What_time_is_it_2",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/13/0b898987.json": "What_time_is_it_1",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/07/551c4fe8.json": "Python_REPL",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/05/418f55c3.json": "Certificate_for_primality_test",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/05/6abbb2c5.json": "Generating_a_random_prime",
    "/home/ubuntu/inspect_logs/neil/chat/2025/04/08/447ccd14.json": "Writing_a_new_poem",
}


def load_o3() -> list[AgentRun]:
    print("Loading o3")
    ars: list[AgentRun] = []
    for path, name in O3_LOGS.items():
        with open(path, "r") as f:
            sample = json.load(f)

        messages: list[ChatMessage] = []

        for message_data in sample["messages"]:
            chat_message = parse_chat_message(message_data)
            messages.append(chat_message)

        metadata = InspectAgentRunMetadata(
            # experiment_id="human_generated_attacks",
            epoch_id=0,
            model="o3-2025-04-03",
            task_id="",
            sample_id=name,
            scores={"score": 1.0},
            scoring_metadata={},
            additional_metadata={},
        )
        transcript = Transcript(
            messages=messages,
            # metadata=metadata,
        )
        ar = AgentRun(
            transcripts={"default": transcript},
            metadata=metadata,
        )
        ars.append(ar)

    return ars


def load_o3_investigator_run(
    sample_dir_path: Path,
    model_name: str,
    experiment_name: str | None = None,
    min_severity: int | None = None,
) -> list[AgentRun]:
    """
    Loads a single investigator run on o3 from a directory of samples.
    Assumes that the samples contain a "violation_score" key, which ranges from 1 to 5.

    Args:
        sample_dir_path: The path to the directory of samples.
        experiment_name: The name of the experiment.
    """

    if experiment_name is None:
        experiment_name = sample_dir_path.name

    ars: list[AgentRun] = []

    all_data: list[dict[Any, Any]] = []
    for file in sorted(sample_dir_path.glob("*.json")):
        with open(file, "r") as f:
            all_data.append(json.load(f))

    for i, sample in enumerate(all_data):
        if min_severity is not None and sample["metadata"]["violation_score"] < min_severity:
            continue

        messages: list[ChatMessage] = []

        for message_data in sample["messages"]:
            chat_message = parse_chat_message(message_data)
            messages.append(chat_message)

        metadata = InspectAgentRunMetadata(
            # experiment_id=experiment_name,
            epoch_id=i,
            model=model_name,
            task_id="0",
            sample_id=str(i),
            scores={"score": max(0, (sample["metadata"]["violation_score"] - 1) / 4)},
            scoring_metadata={},
            additional_metadata=sample["metadata"],
        )
        transcript = Transcript(
            messages=messages,
        )
        ars.append(AgentRun(transcripts={"default": transcript}, metadata=metadata))

    return ars


def load_all_o3() -> list[AgentRun]:
    data1 = load_o3_investigator_run(
        Path("/home/ubuntu/inspect_logs/neil/o3_investigations/run_008/samples_g3"),
        "o3-2025-04-03",
        "code_tool_honesty_zero-shot",
        min_severity=3,
    )
    data2 = load_o3_investigator_run(
        Path("/home/ubuntu/inspect_logs/neil/o3_investigations/run_013/samples_g1"),
        "o3-2025-04-03",
        "code_tool_honesty_few-shot",
        min_severity=3,
    )
    data3 = load_o3()
    return data1 + data2 + data3
