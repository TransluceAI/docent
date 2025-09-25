import json
from typing import Any, AsyncIterator, Literal, TypedDict

from openai import omit
from openai.types.chat import (
    ChatCompletionMessageParam,
)

from docent.data_models.chat import AssistantMessage, ChatMessage, ToolCall
from docent.data_models.chat.tool import (
    ToolInfo,
)
from docent_core._llm_util.providers.openai import parse_chat_messages, parse_tools
from docent_core.investigator.tools.backends.openai_compatible_backend import (
    ModelWithClient,
)
from docent_core.investigator.tools.common.types import (
    MessageEnd,
    MessageStart,
    TokenDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    generate_uid,
)
from docent_core.investigator.tools.subject_models.base import SubjectModelBase


class ToolCallData(TypedDict):
    id: str
    name: str
    arguments: str  # Note that this can be `arguments` or `input` depending on the tool type
    started: bool
    type: Literal["function", "custom"]


class OpenAICompatibleSubjectModel(SubjectModelBase):
    """Subject model that uses an OpenAI-compatible backend."""

    def __init__(self, model_with_client: ModelWithClient, tools: list[ToolInfo] | None = None):
        self.model_with_client = model_with_client
        self.tools = tools
        self.conversation_history: list[ChatMessage] = []

    async def generate_response_stream(
        self, policy_turn: list[ChatMessage]
    ) -> AsyncIterator[
        TokenDelta | MessageStart | MessageEnd | ToolCallStart | ToolCallDelta | ToolCallEnd
    ]:
        """Generate a streaming response from the OpenAI-compatible model.

        This maintains conversation history and yields a single assistant message
        in response to the policy turn.
        """
        # Add the policy turn to our conversation history
        self.conversation_history.extend(policy_turn)

        # Convert messages to OpenAI format
        openai_messages: list[ChatCompletionMessageParam] = parse_chat_messages(
            self.conversation_history
        )

        # Generate response from the model
        message_id = generate_uid()

        # Yield MessageStart for assistant response
        yield MessageStart(
            message_id=message_id,
            role="assistant",
            is_thinking=False,
        )

        # Stream the response
        tools_param = parse_tools(self.tools) if self.tools else omit

        stream = await self.model_with_client.client.chat.completions.create(
            model=self.model_with_client.model,
            messages=openai_messages,
            stream=True,
            tools=tools_param,
        )

        # Collect the full response for history
        full_response = ""
        tool_calls_data: dict[int, ToolCallData] = {}  # Index -> tool call data

        async for chunk in stream:
            # Extract content from the chunk
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta

                # Handle regular content
                if delta.content:
                    # Yield token delta
                    yield TokenDelta(
                        message_id=message_id,
                        role="assistant",
                        content=delta.content,
                        is_thinking=False,
                    )
                    full_response += delta.content

                # Handle tool calls
                if delta.tool_calls:
                    for tool_call_chunk in delta.tool_calls:
                        index = tool_call_chunk.index

                        # Initialize or update tool call data
                        if index not in tool_calls_data:
                            tool_calls_data[index] = ToolCallData(
                                id="",
                                name="",
                                arguments="",
                                started=False,
                                type="function",  # Default to function for OpenAI
                            )

                        # New tool call starting
                        if tool_call_chunk.id:
                            tool_calls_data[index]["id"] = tool_call_chunk.id

                        # Function name
                        if tool_call_chunk.function and tool_call_chunk.function.name:
                            tool_calls_data[index]["name"] = tool_call_chunk.function.name
                            # Emit ToolCallStart when we have both ID and name
                            if (
                                tool_calls_data[index]["id"]
                                and not tool_calls_data[index]["started"]
                            ):
                                yield ToolCallStart(
                                    type=tool_calls_data[index]["type"],  # type: ignore[arg-type]
                                    message_id=message_id,
                                    tool_call_id=tool_calls_data[index]["id"],
                                    function_name=tool_calls_data[index]["name"],
                                    tool_call_index=index,
                                )
                                tool_calls_data[index]["started"] = True

                        # Accumulate arguments
                        if tool_call_chunk.function and tool_call_chunk.function.arguments:
                            args_delta = tool_call_chunk.function.arguments
                            tool_calls_data[index]["arguments"] += args_delta
                            # Emit ToolCallDelta for argument updates
                            if tool_calls_data[index]["started"]:
                                yield ToolCallDelta(
                                    type=tool_calls_data[index]["type"],  # type: ignore[arg-type]
                                    message_id=message_id,
                                    tool_call_id=tool_calls_data[index]["id"],
                                    arguments_delta=args_delta,
                                    tool_call_index=index,
                                )

        # Emit ToolCallEnd events for all completed tool calls
        for index, tool_data in tool_calls_data.items():
            if tool_data["started"]:
                yield ToolCallEnd(
                    type=tool_data["type"],  # type: ignore[arg-type]
                    message_id=message_id,
                    tool_call_id=tool_data["id"],
                    tool_call_index=index,
                )

        # Construct tool calls list for the AssistantMessage
        tool_calls: list[ToolCall] | None = None
        if tool_calls_data:
            tool_calls = []
            for tool_data in tool_calls_data.values():
                if tool_data["id"] and tool_data["name"]:
                    # For function calls, try to parse arguments as JSON
                    parsed_args: dict[str, Any]
                    try:
                        parsed_args = (
                            json.loads(tool_data["arguments"]) if tool_data["arguments"] else {}
                        )
                    except json.JSONDecodeError:
                        # If parsing fails, store as dict with raw key
                        parsed_args = {"raw": tool_data["arguments"]}

                    tool_calls.append(
                        ToolCall(
                            id=tool_data["id"],
                            function=tool_data["name"],
                            arguments=parsed_args,
                            type="function",
                        )
                    )

        # Add the assistant response to conversation history
        assistant_msg = AssistantMessage(
            content=full_response if full_response else "",  # Empty string if no content
            role="assistant",
            tool_calls=tool_calls,
        )
        self.conversation_history.append(assistant_msg)

        # Yield MessageEnd
        yield MessageEnd(message_id=message_id)
