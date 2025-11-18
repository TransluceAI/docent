from logging import getLogger
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Discriminator, Field

from docent.data_models.chat.content import Content
from docent.data_models.chat.tool import ToolCall
from docent.data_models.citation import InlineCitation

logger = getLogger(__name__)


class BaseChatMessage(BaseModel):
    """Base class for all chat message types.

    Attributes:
        id: Optional unique identifier for the message.
        content: The message content, either as a string or list of Content objects.
        role: The role of the message sender (system, user, assistant, tool).
        metadata: Additional structured metadata about the message.
    """

    id: str | None = None
    content: str | list[Content]
    role: Literal["system", "user", "assistant", "tool"]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def text(self) -> str:
        """Get the text content of the message.

        Returns:
            str: The text content of the message. If content is a list,
                 concatenates all text content elements with newlines.
        """
        if isinstance(self.content, str):
            return self.content
        else:
            all_text = [content.text for content in self.content if content.type == "text"]
            return "\n".join(all_text)


class SystemMessage(BaseChatMessage):
    """System message in a chat conversation.

    Attributes:
        role: Always set to "system".
    """

    role: Literal["system"] = "system"  # type: ignore


class UserMessage(BaseChatMessage):
    """User message in a chat conversation.

    Attributes:
        role: Always set to "user".
        tool_call_id: Optional list of tool call IDs this message is responding to.
    """

    role: Literal["user"] = "user"  # type: ignore
    tool_call_id: list[str] | None = None


class AssistantMessage(BaseChatMessage):
    """Assistant message in a chat conversation.

    Attributes:
        role: Always set to "assistant".
        model: Optional identifier for the model that generated this message.
        tool_calls: Optional list of tool calls made by the assistant.
    """

    role: Literal["assistant"] = "assistant"  # type: ignore
    model: str | None = None
    tool_calls: list[ToolCall] | None = None


class DocentAssistantMessage(AssistantMessage):
    """Assistant message in a chat session with additional chat-specific metadata.

    This extends AssistantMessage with fields that are only relevant in Docent chat contexts

    Attributes:
        citations: Optional list of citations referenced in the message content.
        suggested_messages: Optional list of suggested followup messages.
    """

    citations: list[InlineCitation] | None = None
    suggested_messages: list[str] | None = None


class ToolMessage(BaseChatMessage):
    """Tool message in a chat conversation.

    Attributes:
        role: Always set to "tool".
        tool_call_id: Optional ID of the tool call this message is responding to.
        function: Optional name of the function that was called.
        error: Optional error information if the tool call failed.
    """

    role: Literal["tool"] = "tool"  # type: ignore

    tool_call_id: str | None = None
    function: str | None = None
    error: dict[str, Any] | None = None


ChatMessage = Annotated[
    SystemMessage | UserMessage | AssistantMessage | ToolMessage,
    Discriminator("role"),
]
"""Type alias for any chat message type, discriminated by the role field.

This is the base message union used in Transcript and AgentRun contexts.
For chat sessions, use ChatSessionMessage instead.
"""

DocentChatMessage = Annotated[
    SystemMessage | UserMessage | DocentAssistantMessage | ToolMessage,
    Discriminator("role"),
]
"""Type alias for chat session messages with chat-specific assistant metadata."""


def parse_chat_message(message_data: dict[str, Any] | ChatMessage) -> ChatMessage:
    """Parse a message dictionary or object into the appropriate ChatMessage subclass.

    This parses base messages without chat-specific fields. For chat sessions,
    use parse_chat_session_message instead.

    Args:
        message_data: A dictionary or ChatMessage object representing a chat message.

    Returns:
        ChatMessage: An instance of a ChatMessage subclass based on the role.

    Raises:
        ValueError: If the message role is unknown.
    """
    if isinstance(message_data, (SystemMessage, UserMessage, AssistantMessage, ToolMessage)):
        return message_data

    role = message_data.get("role")
    if role == "system":
        return SystemMessage.model_validate(message_data)
    elif role == "user":
        return UserMessage.model_validate(message_data)
    elif role == "assistant":
        return AssistantMessage.model_validate(message_data)
    elif role == "tool":
        return ToolMessage.model_validate(message_data)
    else:
        raise ValueError(f"Unknown message role: {role}")


def parse_docent_chat_message(
    message_data: dict[str, Any] | DocentChatMessage,
) -> DocentChatMessage:
    """Parse a message dictionary or object into the appropriate ChatSessionMessage subclass.

    This handles chat session messages which may include ChatAssistantMessage with
    citations and suggested_messages fields.

    Args:
        message_data: A dictionary or ChatSessionMessage object representing a chat session message.

    Returns:
        ChatSessionMessage: An instance of a ChatSessionMessage subclass based on the role.

    Raises:
        ValueError: If the message role is unknown.
    """
    if isinstance(
        message_data,
        (SystemMessage, UserMessage, DocentAssistantMessage, AssistantMessage, ToolMessage),
    ):
        return message_data

    role = message_data.get("role")
    if role == "system":
        return SystemMessage.model_validate(message_data)
    elif role == "user":
        return UserMessage.model_validate(message_data)
    elif role == "assistant":
        return DocentAssistantMessage.model_validate(message_data)
    elif role == "tool":
        return ToolMessage.model_validate(message_data)
    else:
        raise ValueError(f"Unknown message role: {role}")
