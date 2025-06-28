from logging import getLogger
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Discriminator

from docent.data_models.chat.content import Content
from docent.data_models.chat.tool import ToolCall

logger = getLogger(__name__)


class BaseChatMessage(BaseModel):
    """Base class for all chat message types.

    Attributes:
        id: Optional unique identifier for the message.
        content: The message content, either as a string or list of Content objects.
        role: The role of the message sender (system, user, assistant, tool).
    """

    id: str | None = None
    content: str | list[Content]
    role: Literal["system", "user", "assistant", "tool"]

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
"""Type alias for any chat message type, discriminated by the role field."""


def parse_chat_message(message_data: dict[str, Any] | ChatMessage) -> ChatMessage:
    """Parse a message dictionary or object into the appropriate ChatMessage subclass.

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
