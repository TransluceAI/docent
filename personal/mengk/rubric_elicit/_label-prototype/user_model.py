"""
Data structures for User Data (U) and User Model (z) in feedback elicitation.

User Data (U) represents historical observations that inform the user model:
- QA pairs from interactive elicitation sessions
- Human labels on agent runs

User Model (z) represents a markdown representation of user intent,
derived from aggregating user data.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QAPair(BaseModel):
    """A single QA pair: (agent_run_id, question, answer)"""

    agent_run_id: str
    question: str
    answer: str
    timestamp: datetime = Field(default_factory=datetime.now)
    question_context: str | None = None
    is_custom_response: bool = False


class LabeledRun(BaseModel):
    """A human label: (agent_run_id, label_value)"""

    agent_run_id: str
    label_value: dict[str, Any]  # Matches Label.label_value pattern
    timestamp: datetime = Field(default_factory=datetime.now)


class UserData(BaseModel):
    """User Data (U) - Historical observations that inform the user model"""

    initial_rubric: str
    qa_pairs: list[QAPair] = Field(default_factory=lambda: list[QAPair]())
    labels: list[LabeledRun] = Field(default_factory=lambda: list[LabeledRun]())
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)

    def add_qa_pair(
        self,
        agent_run_id: str,
        question: str,
        answer: str,
        question_context: str | None = None,
        is_custom_response: bool = False,
    ) -> None:
        """Add a QA pair to the user data."""
        qa_pair = QAPair(
            agent_run_id=agent_run_id,
            question=question,
            answer=answer,
            question_context=question_context,
            is_custom_response=is_custom_response,
        )
        self.qa_pairs.append(qa_pair)
        self.last_updated = datetime.now()

    def add_label(self, agent_run_id: str, label_value: dict[str, Any]) -> None:
        """Add a label to the user data."""
        labeled_run = LabeledRun(
            agent_run_id=agent_run_id,
            label_value=label_value,
        )
        self.labels.append(labeled_run)
        self.last_updated = datetime.now()


class UserModel(BaseModel):
    """User Model (z) - Markdown representation of user intent"""

    model_text: str
    version: int = 1
    user_data: UserData
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)

    def update_model(self, new_model_text: str) -> None:
        """Update the model text and increment version."""
        self.model_text = new_model_text
        self.version += 1
        self.last_updated = datetime.now()
