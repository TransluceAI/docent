import json
from typing import AsyncIterator

from pydantic import BaseModel

from docent.data_models.chat import (
    AssistantMessage,
    ChatMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from docent.data_models.chat.content import ContentText
from docent.data_models.chat.tool import ToolInfo
from docent_core.investigator.tools.common.types import (
    MessageEnd,
    MessageStart,
    RolloutEnd,
    TokenDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    generate_uid,
)
from docent_core.investigator.tools.policies.base import BaseContextPolicy


class DeterministicContextPolicy(BaseContextPolicy):
    """
    A deterministic context policy that always proposes the same list of messages.

    This policy sends all its messages on the first call, then signals RolloutEnd
    on subsequent calls.
    """

    def __init__(
        self, deterministic_messages: list[ChatMessage], tools: list[ToolInfo] | None = None
    ):
        self.deterministic_messages = deterministic_messages
        self.tools = tools
        self.messages_sent = False

    async def generate_message_stream(
        self, subject_model_turn: list[ChatMessage]
    ) -> AsyncIterator[
        MessageStart
        | TokenDelta
        | MessageEnd
        | RolloutEnd
        | ToolCallStart
        | ToolCallDelta
        | ToolCallEnd
    ]:
        """
        Yields a stream of messages from the deterministic context.
        On the first call, sends all messages. On subsequent calls, yields RolloutEnd.
        """

        # If we've already sent our messages, end the rollout
        if self.messages_sent:
            yield RolloutEnd()
            return

        # If we have no messages to send, end the rollout immediately
        if not self.deterministic_messages:
            yield RolloutEnd()
            return

        # Send all our messages at once
        for message in self.deterministic_messages:

            assert isinstance(
                message, (UserMessage, AssistantMessage, SystemMessage, ToolMessage)
            ), "Only user, assistant, system, and tool messages are supported"

            message_id = generate_uid()

            # Include tool_call_id for tool and user messages (both can have tool_call_id)
            tool_call_id = None
            if isinstance(message, (ToolMessage, UserMessage)) and message.tool_call_id:
                tool_call_id = message.tool_call_id

            assert tool_call_id is None or isinstance(
                tool_call_id, str
            ), "tool_call_id must be a string"

            yield MessageStart(
                message_id=message_id,
                role=message.role,
                is_thinking=False,
                tool_call_id=tool_call_id,
            )
            if isinstance(message.content, str):
                yield TokenDelta(
                    message_id=message_id,
                    role=message.role,
                    content=message.content,
                )
            else:
                # list of content objects
                for content in message.content:
                    if isinstance(content, ContentText):
                        yield TokenDelta(
                            message_id=message_id,
                            role=message.role,
                            content=content.text,
                        )
                    else:  # ContentReasoning
                        yield TokenDelta(
                            message_id=message_id,
                            role=message.role,
                            content=content.reasoning,
                        )

            # Handle tool calls for assistant messages
            if isinstance(message, AssistantMessage) and message.tool_calls:
                for idx, tool_call in enumerate(message.tool_calls):
                    # Emit ToolCallStart
                    yield ToolCallStart(
                        type=tool_call.type or "function",
                        message_id=message_id,
                        tool_call_id=tool_call.id,
                        function_name=tool_call.function,
                        tool_call_index=idx,
                    )

                    # For function calls, send arguments as JSON string
                    if tool_call.arguments:
                        args_str = json.dumps(tool_call.arguments)
                        yield ToolCallDelta(
                            type="function",
                            message_id=message_id,
                            tool_call_id=tool_call.id,
                            arguments_delta=args_str,
                            tool_call_index=idx,
                        )

                    # Emit ToolCallEnd
                    yield ToolCallEnd(
                        type=tool_call.type or "function",
                        message_id=message_id,
                        tool_call_id=tool_call.id,
                        tool_call_index=idx,
                    )

            yield MessageEnd(message_id=message_id)

        # Mark that we've sent our messages
        self.messages_sent = True


class DeterministicContextPolicyConfig(BaseModel):
    """
    A deterministic context policy that always proposes the same list of messages.
    """

    messages: list[ChatMessage]
    tools: list[ToolInfo] | None = None

    def build(self) -> DeterministicContextPolicy:
        return DeterministicContextPolicy(self.messages, self.tools)
