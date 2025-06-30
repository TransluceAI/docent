import json

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat import ChatMessage, parse_chat_message
from docent.data_models.metadata import InspectAgentRunMetadata
from docent.data_models.transcript import Transcript

logger = get_logger(__name__)

O3_LOGS = {
    "/home/ubuntu/artifacts/neil/chat/2025/04/05/ad14cf0e.json": "Time_elapsed",
    "/home/ubuntu/artifacts/neil/chat/2025/04/05/d731afd7.json": "Random_seed_1",
    "/home/ubuntu/artifacts/neil/chat/2025/04/05/83496f36.json": "MacBook_Pro",
    "/home/ubuntu/artifacts/neil/chat/2025/04/07/b21efca0.json": "Yap_score_2",
    "/home/ubuntu/artifacts/neil/chat/2025/04/13/0b898987.json": "What_time_is_it_1",
    "/home/ubuntu/artifacts/neil/chat/2025/04/05/6abbb2c5.json": "Generating_a_random_prime",
    "/home/ubuntu/artifacts/neil/chat/2025/04/08/447ccd14.json": "Writing_a_new_poem",
}

MINI_4O_LOGS = {
    "/home/ubuntu/artifacts/neil/chat/2025/04/05/ad14cf0e_2.json": "Time_elapsed",
    "/home/ubuntu/artifacts/neil/chat/2025/04/05/d731afd7_2.json": "Random_seed_1",
    "/home/ubuntu/artifacts/neil/chat/2025/04/05/83496f36_2.json": "MacBook_Pro",
    "/home/ubuntu/artifacts/neil/chat/2025/04/07/b21efca0_2.json": "Yap_score_2",
    "/home/ubuntu/artifacts/neil/chat/2025/04/13/0b898987_2.json": "What_time_is_it_1",
    "/home/ubuntu/artifacts/neil/chat/2025/04/05/6abbb2c5_2.json": "Generating_a_random_prime",
    "/home/ubuntu/artifacts/neil/chat/2025/04/08/447ccd14_2.json": "Writing_a_new_poem",
}


def load_o3() -> list[AgentRun]:
    print("Loading o3")
    transcripts: list[AgentRun] = []
    for path, name in O3_LOGS.items():
        with open(path, "r") as f:
            sample = json.load(f)

        messages: list[ChatMessage] = []

        for message_data in sample["messages"]:
            chat_message = parse_chat_message(message_data)
            messages.append(chat_message)

        metadata = InspectAgentRunMetadata(
            epoch_id=0,
            model="o3-2025-04-03",
            task_id="",
            sample_id=name,
            scores={"": False},
            scoring_metadata={},
            additional_metadata={},
        )
        transcript = AgentRun(
            transcripts={"default": Transcript(messages=messages)},
            metadata=metadata,
        )
        transcripts.append(transcript)

    for path, name in MINI_4O_LOGS.items():
        try:
            with open(path, "r") as f:
                sample = json.load(f)
        except:
            raise Exception(f"Error loading {path}")

        messages: list[ChatMessage] = []

        for message_data in sample["messages"]:
            chat_message = parse_chat_message(message_data)
            messages.append(chat_message)

        metadata = InspectAgentRunMetadata(
            epoch_id=0,
            model="gpt-4o-mini-2024-07-18",
            task_id="",
            sample_id=name,
            scores={"": False},
            scoring_metadata={},
            additional_metadata={},
        )
        transcript = AgentRun(
            transcripts={"default": Transcript(messages=messages)},
            metadata=metadata,
        )
        transcripts.append(transcript)

    return transcripts
