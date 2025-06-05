from typing import Optional

from pydantic import BaseModel


class MessageState:
    """Represents the state of a message in a transcript, including its action, goal, and context."""

    def __init__(self, message_idx: int, action: str, goal: str, past_actions: str):
        self.message_idx = message_idx
        self.action = action
        self.goal = goal
        self.past_actions = past_actions

    def __str__(self):
        return f"[B{self.message_idx}]\nAction: {self.action}\nGoal: {self.goal}\nRelevant past actions: {self.past_actions}"


class Claim(BaseModel):
    """A single claim about the difference between two agent runs."""

    claim_summary: str
    shared_context: Optional[str] = None
    agent_1_action: str
    agent_2_action: str
    evidence: str


class TranscriptDiff(BaseModel):
    """Represents the differences between two agent run transcripts."""

    agent_run_1_id: str
    agent_run_2_id: str
    claims: list[Claim]
