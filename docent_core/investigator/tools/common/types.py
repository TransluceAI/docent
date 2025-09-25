import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from docent.data_models.chat import ChatMessage


def generate_uid() -> str:
    return str(uuid.uuid4())


class Grade(BaseModel):
    grade: float

    # The exact list of messages that was shown to the grader.
    grader_prompt: list[ChatMessage]
    grader_response: str


# Main experiment configuration
class ExperimentStatus(BaseModel):
    """Configuration for a single experiment.

    This is mostly used for the UI visualization (list of experiments in the sidebar)
    """

    status: Literal["pending", "running", "completed", "cancelled", "error"] = "pending"
    progress: float = 0.0
    start_time: datetime

    # If the experiment has been saved to a Docent collection, this will be the collection id.
    docent_collection_id: Optional[str] = None
    error_message: Optional[str] = None


class TokenDelta(BaseModel):
    """Incremental token update for a message.

    Note that the message_id must match the message_id of the MessageStart event that preceded it.
    """

    message_id: str
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    is_thinking: bool = False


class MessageStart(BaseModel):
    """Event indicating the start of a new message."""

    message_id: str = Field(default_factory=generate_uid)
    role: Literal["user", "assistant", "system", "tool"]
    is_thinking: bool = False
    tool_call_id: str | None = None  # For tool messages, the ID of the tool call being responded to


class MessageEnd(BaseModel):
    """Event indicating the end of a message.

    Note that the message_id must match the message_id of the MessageStart event that preceded it.
    """

    message_id: str


class ToolCallStart(BaseModel):
    """Event indicating the start of a tool call."""

    type: Literal["function", "custom"]
    message_id: str
    tool_call_id: str
    function_name: str
    tool_call_index: int = 0


class ToolCallDelta(BaseModel):
    """Incremental update for a tool call's arguments."""

    type: Literal["function", "custom"]
    message_id: str
    tool_call_id: str
    arguments_delta: str
    tool_call_index: int = 0


class ToolCallEnd(BaseModel):
    """Event indicating the end of a tool call."""

    type: Literal["function", "custom"]
    message_id: str
    tool_call_id: str
    tool_call_index: int = 0


class GradeStart(BaseModel):
    """Event indicating grading has started."""


class GradeUpdate(BaseModel):
    """Event with partial grading information."""

    content: str


class GradeEnd(BaseModel):
    """Event with final grading result."""

    annotation: Grade


class RolloutEnd(BaseModel):
    """Event indicating the end of a rollout.

    Note: this **precedes** grading. It just marks the end of the policy/subject model interaction.
    """


class RolloutErrorEvent(BaseModel):
    """Event indicating a rollout failed with an error."""

    error: Exception
    user_error_message: str | None = None

    class Config:
        arbitrary_types_allowed = True


StreamEvent = (
    TokenDelta
    | MessageStart
    | MessageEnd
    | ToolCallStart
    | ToolCallDelta
    | ToolCallEnd
    | GradeStart
    | GradeUpdate
    | GradeEnd
    | RolloutEnd
    | RolloutErrorEvent
)
