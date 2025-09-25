import json
from typing import Any

from pydantic import BaseModel

from docent.data_models.chat.message import (
    AssistantMessage,
    ChatMessage,
    ToolMessage,
    UserMessage,
    parse_chat_message,
)
from docent.data_models.chat.tool import ToolInfo
from docent_core.investigator.db.schemas.experiment import SQLABaseContext
from docent_core.investigator.tools.policies.deterministic import DeterministicContextPolicyConfig


class BaseContext(BaseModel):
    """Base context."""

    id: str
    name: str
    prompt: list[ChatMessage]
    tools: list[ToolInfo] | None = None

    @classmethod
    def from_sql(cls, context: SQLABaseContext) -> "BaseContext":
        tools = None
        if context.tools:
            tools = [ToolInfo.model_validate(tool) for tool in context.tools]

        return cls(
            id=context.id,
            name=context.name,
            prompt=[parse_chat_message(m) for m in context.prompt],
            tools=tools,
        )

    def to_json_array_str(self) -> str:
        """
        Formats the interaction as a JSON object with tools and messages, useful for passing to an LLM.

        Example:
        ```json
        {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "description": "Perform calculations",
                        "parameters": {...}
                    }
                }
            ],
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful assistant."
                },
                {
                    "role": "user",
                    "content": "Hello, how are you?"
                }
            ]
        }
        ```
        """
        # Build messages list with all relevant fields
        messages: list[dict[str, Any]] = []
        for m in self.prompt:
            msg_dict: dict[str, Any] = {"role": m.role, "content": m.content}

            # Add tool calls for assistant messages
            if isinstance(m, AssistantMessage) and m.tool_calls:
                tool_calls_list: list[dict[str, Any]] = []
                for tc in m.tool_calls:
                    tool_call_dict = {
                        "id": tc.id,
                        "type": tc.type or "function",
                        "function": tc.function,
                    }

                    # Function tool calls have 'arguments'
                    tool_call_dict["arguments"] = tc.arguments  # type: ignore

                    tool_calls_list.append(tool_call_dict)

                msg_dict["tool_calls"] = tool_calls_list

            # Add tool_call_id for user and tool messages
            if isinstance(m, UserMessage) and m.tool_call_id:
                msg_dict["tool_call_id"] = m.tool_call_id
            elif isinstance(m, ToolMessage) and m.tool_call_id:
                msg_dict["tool_call_id"] = m.tool_call_id

            # Add function and error for tool messages
            if isinstance(m, ToolMessage):
                if m.function:
                    msg_dict["function"] = m.function
                if m.error:
                    msg_dict["error"] = m.error

            messages.append(msg_dict)

        # Build the complete interaction object
        interaction: dict[str, Any] = {"messages": messages}

        # Add tools if present
        if self.tools:
            interaction["tools"] = [tool.model_dump() for tool in self.tools]

        return json.dumps(interaction, indent=4)

    def to_deterministic_context_policy_config(self) -> DeterministicContextPolicyConfig:
        return DeterministicContextPolicyConfig(
            messages=self.prompt,
            tools=self.tools,
        )
