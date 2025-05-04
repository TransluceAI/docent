import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeAlias, TypedDict

from inspect_ai.model import ChatMessage as InspectChatMessage
from inspect_ai.model import ChatMessageAssistant as InspectChatMessageAssistant
from inspect_ai.model import ChatMessageSystem as InspectChatMessageSystem
from inspect_ai.model import ChatMessageTool as InspectChatMessageTool
from inspect_ai.model import ChatMessageUser as InspectChatMessageUser
from inspect_ai.model import Content as InspectContent
from inspect_ai.model import ContentReasoning as InspectContentReasoning
from inspect_ai.tool import ToolCall as InspectToolCall
from inspect_ai.tool import ToolCallError as InspectToolCallError
from inspect_ai.tool import ToolDef as InspectToolDef
from inspect_ai.tool import ToolInfo as InspectToolInfo
from docent._log_util import get_logger
from openai.types.chat.chat_completion_token_logprob import TopLogprob
from pydantic import BaseModel

ChatMessage: TypeAlias = InspectChatMessage
ChatMessageUser: TypeAlias = InspectChatMessageUser
ChatMessageAssistant: TypeAlias = InspectChatMessageAssistant
ChatMessageTool: TypeAlias = InspectChatMessageTool
ChatMessageSystem: TypeAlias = InspectChatMessageSystem
ChatMessageContent: TypeAlias = InspectContent
ChatMessageContentReasoning: TypeAlias = InspectContentReasoning

ToolDef: TypeAlias = InspectToolDef
ToolCall: TypeAlias = InspectToolCall
ToolInfo: TypeAlias = InspectToolInfo
ToolCallError: TypeAlias = InspectToolCallError

logger = get_logger(__name__)


class LLMApiKeys(TypedDict):
    openai_key: str | None
    anthropic_key: str | None


class ModelCallParams(BaseModel):
    provider: str
    model_name: str
    reasoning_effort: Literal["low", "medium", "high"] | None = None


@dataclass
class ToolCallPartial:
    id: str | None
    function: str | None
    arguments_raw: str | None
    type: Literal["function"]


def parse_chat_message(message_data: dict[str, Any]) -> ChatMessage:
    role = message_data.get("role")

    if role == "system":
        return ChatMessageSystem.model_validate(message_data)
    elif role == "user":
        return ChatMessageUser.model_validate(message_data)
    elif role == "assistant":
        return ChatMessageAssistant.model_validate(message_data)
    elif role == "tool":
        return ChatMessageTool.model_validate(message_data)
    else:
        raise ValueError(f"Unknown message role: {role}")


class CompletionTooLongException(Exception):
    pass


class RateLimitException(Exception):
    pass


FinishReasonType = Literal[
    "error",
    "stop",
    "length",
    "tool_calls",
    "content_filter",
    "function_call",
    "streaming",
]


class LLMCompletion(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: FinishReasonType | None = None
    top_logprobs: list[list[TopLogprob]] | None = None
    """List of the top logprobs for each token in the completion text."""

    @property
    def no_text(self) -> bool:
        return self.text is None or len(self.text) == 0


class LLMOutput(BaseModel):
    model: str
    completions: list[LLMCompletion]
    errors: (
        list[Literal["rate_limit", "no_response", "other", "all_providers_exhausted"]] | None
    ) = None

    @property
    def non_empty(self) -> bool:
        return len(self.completions) > 0

    @property
    def first(self) -> LLMCompletion | None:
        return self.completions[0] if self.non_empty else None

    @property
    def first_text(self) -> str | None:
        return self.first.text if self.first else None

    @property
    def did_error(self) -> bool:
        return bool(self.errors)


class LLMCompletionPartial(LLMCompletion):
    tool_calls: list[ToolCallPartial | None] | None = None  # type: ignore


class LLMOutputPartial(LLMOutput):
    completions: list[LLMCompletionPartial]  # type: ignore


def finalize_llm_output_partial(partial: LLMOutputPartial) -> LLMOutput:
    def _parse_tool_call(tc_partial: ToolCallPartial):
        if tc_partial.id is None:
            raise ValueError("Tool call ID not found in partial; check for parsing errors")
        if tc_partial.function is None:
            raise ValueError("Tool call function not found in partial; check for parsing errors")

        # Attempt to load arguments into JSON
        try:
            arguments: dict[str, Any] = json.loads(tc_partial.arguments_raw or "{}")
            parse_error = None
        # If the tool call arguments are not valid JSON, return an empty dict with the error
        except Exception as e:
            arguments: dict[str, Any] = {}
            parse_error = f"Couldn't parse tool call arguments as JSON: {e}. Original input: {tc_partial.arguments_raw}"

        return ToolCall(
            id=tc_partial.id,
            function=tc_partial.function,
            arguments=arguments,
            parse_error=parse_error,
            type=tc_partial.type,
        )

    output = LLMOutput(
        model=partial.model,
        completions=[
            LLMCompletion(
                text=c.text,
                tool_calls=[_parse_tool_call(tc) for tc in (c.tool_calls or []) if tc is not None],
                finish_reason=c.finish_reason,
            )
            for c in partial.completions
        ],
    )

    # If the completion is empty and was truncated (likely due to too much reasoning), raise an exception
    if output.first and output.first.finish_reason == "length" and output.first.no_text:
        raise CompletionTooLongException(
            "Completion empty due to truncation. Consider increasing max_new_tokens."
        )
    for c in output.completions:
        if c.finish_reason == "length":
            logger.warn("Completion truncated due to length; consider increasing max_new_tokens.")

    return output


def get_tools_info(tool: ToolDef) -> ToolInfo:
    return ToolInfo(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters,
    )


class AsyncStreamingCallback(Protocol):
    async def __call__(
        self,
        batch_index: int,
        llm_output: LLMOutput,
    ) -> None: ...


class AsyncSingleStreamingCallback(Protocol):
    async def __call__(
        self,
        llm_output: LLMOutput,
    ) -> None: ...


def get_single_streaming_callback(
    batch_index: int,
    streaming_callback: AsyncStreamingCallback,
) -> AsyncSingleStreamingCallback:
    async def single_streaming_callback(llm_output: LLMOutput):
        await streaming_callback(batch_index, llm_output)

    return single_streaming_callback
