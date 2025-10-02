"""
This module contains the logic for applying counterfactual ideas to a base context.

As an example, if the counterfactual idea is "Change the context to be French.",
then this will produce a counterfactual context that is the base context, but in French.

"""

import textwrap
from collections.abc import AsyncIterator
from string import Template
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from docent.data_models.chat.message import ChatMessage, parse_chat_message
from docent.data_models.chat.tool import ToolInfo
from docent_core.investigator.tools.common.types import (
    MessageEnd,
    MessageStart,
    TokenDelta,
    generate_uid,
)
from docent_core.investigator.tools.contexts.base_context import BaseContext
from docent_core.investigator.tools.counterfactual_analysis.types import CounterfactualIdea
from docent_core.investigator.tools.policies.deterministic import DeterministicContextPolicyConfig
from docent_core.investigator.utils.async_util.concurrency_limiters import LimiterRegistry


class CounterfactualInteraction(BaseModel):
    """Pydantic model for the counterfactual interaction format."""

    tools: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]]


APPLY_COUNTERFACTUAL_IDEA_SYSTEM_PROMPT_TPL = """You are an assistant that helps perform experiments on language models.

Your specific task is to apply modifications to a base interaction. You will receive:
1. A base interaction (which may include tools and messages with tool calls/responses)
2. A specific counterfactual idea describing what aspect should be changed

Your job is to:
- Take the base interaction exactly as provided
- Apply ONLY the minimal changes described in the counterfactual idea
- Preserve as much of the original interaction as possible while making the specified change
- Output the modified interaction that can be directly used to test the subject language model

Guidelines:
- Make the smallest possible change that achieves the counterfactual goal
- Do not add explanatory text or meta-commentary to the modified interaction
- Maintain the original formatting and structure where possible
- If the counterfactual requires changing specific words, sentences, or tone, do so precisely as described
- The counterfactual may apply to tools, tool calls, tool responses, or regular message content
- The output should be a valid interaction that can be immediately used as input to another language model

Output the modified interaction in JSON with the same structure as the base interaction, with no
other text.

{
    "tools": [
        // Optional: Tool definitions if present in the base interaction
    ],
    "messages": [
        {
            "role": "system",
            "content": "..."
        },
        {
            "role": "assistant",
            "content": "...",
            "tool_calls": [  // Optional: if assistant makes tool calls
                {
                    "id": "...",
                    "type": "function",
                    "function": "...",
                    "arguments": {...}
                }
            ]
        },
        {
            "role": "tool",
            "content": "...",
            "tool_call_id": "...",  // Optional: for tool responses
            "function": "...",       // Optional: function name
            "error": {...}           // Optional: if tool had an error
        },
        // ... more messages
    ]
}

Note: Include the "tools" field only if it exists in the base interaction. Always include the "messages" field.
"""

APPLY_COUNTERFACTUAL_IDEA_USER_PROMPT_TPL = Template(
    textwrap.dedent(
        """
        Here is the base interaction:

        $base_context

        Here is the idea for the counterfactual experiment:

        $idea

    """
    ).strip()
)


async def llm_apply_counterfactual_to_base_context(
    client: genai.Client,
    base_context: BaseContext,
    counterfactual_idea: CounterfactualIdea,
    limiter: LimiterRegistry,
    model: str = "gemini-2.5-flash-lite",
) -> AsyncIterator[MessageStart | TokenDelta | MessageEnd | DeterministicContextPolicyConfig]:
    """
    Apply a counterfactual idea to a base context. Once done, yields a
    DeterministicContextPolicyConfig with the counterfactual applied.
    """
    system_prompt = APPLY_COUNTERFACTUAL_IDEA_SYSTEM_PROMPT_TPL

    user_prompt = APPLY_COUNTERFACTUAL_IDEA_USER_PROMPT_TPL.substitute(
        base_context=base_context.to_json_array_str(),
        idea=counterfactual_idea.description,
    )

    # Retry logic: up to 3 attempts
    max_retries = 3

    for attempt in range(max_retries):

        message_uid = generate_uid()

        yield MessageStart(
            message_id=message_uid,
            role="assistant",
            is_thinking=False,
        )

        try:
            # Accumulate the full response
            full_content = ""

            async with limiter():
                # Make the streaming API call
                # Google API expects Content objects with proper structure
                stream = await client.aio.models.generate_content_stream(  # type: ignore
                    model=model,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=user_prompt)],
                        )
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        system_instruction=system_prompt,
                    ),
                )
                # Stream the response
                async for chunk in stream:
                    content = chunk.text or ""
                    full_content += content

                    # Emit TokenDelta
                    yield TokenDelta(
                        message_id=message_uid,
                        role="assistant",
                        content=content,
                    )

                # Emit MessageEnd
                yield MessageEnd(
                    message_id=message_uid,
                )

                # Now parse the full response
                if not full_content:
                    raise ValueError("Empty response from the API")

                # Extract and parse JSON using Pydantic

                # Find the first '{' and last '}' to extract JSON content
                first_brace = full_content.find("{")
                last_brace = full_content.rfind("}")

                if first_brace == -1 or last_brace == -1 or first_brace >= last_brace:
                    raise ValueError("No valid JSON object found in response")

                parsed_content = full_content[first_brace : last_brace + 1]
                interaction = CounterfactualInteraction.model_validate_json(parsed_content)

                # Convert the parsed messages to ChatMessage objects
                chat_messages: list[ChatMessage] = []
                for msg_data in interaction.messages:
                    if "role" not in msg_data or "content" not in msg_data:
                        raise ValueError("Message missing required fields: role and/or content")
                    chat_messages.append(parse_chat_message(msg_data))

                # Convert tools data if present
                tools: list[ToolInfo] | None = None
                if interaction.tools:
                    tools = []
                    for tool_data in interaction.tools:
                        tools.append(ToolInfo.model_validate(tool_data))

                yield DeterministicContextPolicyConfig(
                    messages=chat_messages,
                    tools=tools if tools else None,
                )

                # Success - break out of retry loop
                break

        except Exception:
            if attempt < max_retries - 1:
                # Not the last attempt, continue to retry
                continue
            else:
                # Last attempt failed, re-raise the error
                raise
