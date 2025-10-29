import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from openai.types.chat.chat_completion_token_logprob import TopLogprob
from pydantic import BaseModel

from docent._llm_util.data_models.exceptions import (
    LLM_ERROR_TYPES,
    CompletionTooLongException,
    ContextWindowException,
    LLMException,
)
from docent._log_util import get_logger
from docent.data_models.chat import ToolCall

logger = get_logger(__name__)

FinishReasonType = Literal[
    "error",
    "stop",
    "length",
    "tool_calls",
    "content_filter",
    "function_call",
    "streaming",
    "refusal",
]
"""Possible reasons for an LLM completion to finish."""


TokenType = Literal["input", "output", "cache_read", "cache_write"]


class UsageMetrics:
    _usage: dict[TokenType, int]

    def __init__(self, **kwargs: int | None):
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        self._usage = cast(dict[TokenType, int], filtered_kwargs)

    def __getitem__(self, key: TokenType) -> int:
        return self._usage.get(key, 0)

    def __setitem__(self, key: TokenType, value: int):
        self._usage[key] = value

    def to_dict(self) -> dict[TokenType, int]:
        # Filter out 0 values to avoid cluttering the database
        return {k: v for k, v in self._usage.items() if v != 0}

    @property
    def total_tokens(self) -> int:
        return self["input"] + self["output"]


class LLMCompletion(BaseModel):
    """A single completion from an LLM.

    Attributes:
        text: The generated text content.
        tool_calls: List of tool calls made during the completion.
        finish_reason: Reason why the completion finished.
        top_logprobs: Probability distribution for top token choices.
    """

    text: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: FinishReasonType | None = None
    top_logprobs: list[list[TopLogprob]] | None = None
    reasoning_tokens: str | None = None

    @property
    def no_text(self) -> bool:
        """Check if the completion has no text.

        Returns:
            bool: True if text is None or empty, False otherwise.
        """
        return self.text is None or len(self.text) == 0


@dataclass
class LLMOutput:
    """Container for LLM output, potentially with multiple completions.

    Aggregates completions from an LLM along with metadata and error information.

    Attributes:
        model: The name/identifier of the model used.
        completions: List of individual completions.
        errors: List of error types encountered during generation.
    """

    model: str
    completions: list[LLMCompletion]
    errors: list[LLMException] = field(default_factory=list)
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    from_cache: bool = False
    duration: float | None = None

    @property
    def non_empty(self) -> bool:
        """Check if there are any completions.

        Returns:
            bool: True if there's at least one completion, False otherwise.
        """
        return len(self.completions) > 0

    @property
    def first(self) -> LLMCompletion | None:
        """Get the first completion if available.

        Returns:
            LLMCompletion | None: The first completion or None if no completions exist.
        """
        return self.completions[0] if self.non_empty else None

    @property
    def first_text(self) -> str | None:
        """Get the text of the first completion if available.

        Returns:
            str | None: The text of the first completion or None if no completion exists.
        """
        return self.first.text if self.first else None

    @property
    def did_error(self) -> bool:
        """Check if any errors occurred during generation.

        Returns:
            bool: True if there were errors, False otherwise.
        """
        return bool(self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "completions": [comp.model_dump() for comp in self.completions],
            "errors": [e.error_type_id for e in self.errors],
            "usage": self.usage.to_dict(),
            "from_cache": self.from_cache,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMOutput":
        error_type_map = {e.error_type_id: e for e in LLM_ERROR_TYPES}
        errors = data.get("errors", [])
        error_types_to_not_log: list[str] = [
            CompletionTooLongException.error_type_id,
            ContextWindowException.error_type_id,
        ]
        errors_to_log = [e for e in errors if e not in error_types_to_not_log]
        if errors_to_log:
            logger.error(f"Loading LLM output with errors: {errors}")
        errors = [error_type_map.get(e, LLMException)() for e in errors]

        completions = data.get("completions", [])
        completions = [LLMCompletion.model_validate(comp) for comp in completions]

        usage: dict[TokenType, int] = {}
        if data_usage := data.get("usage"):
            usage = cast(dict[TokenType, int], data_usage)

        return cls(
            model=data["model"],
            completions=completions,
            errors=errors,
            usage=UsageMetrics(**usage),
            from_cache=bool(data.get("from_cache", False)),
            duration=data.get("duration"),
        )


@dataclass
class ToolCallPartial:
    """Partial representation of a tool call before full processing.

    Used as an intermediate format before finalizing into a complete ToolCall.

    Args:
        id: The identifier for the tool call.
        function: The name of the function to call.
        arguments_raw: Raw JSON string of arguments for the function.
        type: The type of the tool call, always "function".
    """

    id: str | None
    function: str | None
    arguments_raw: str | None
    type: Literal["function"]


class LLMCompletionPartial(LLMCompletion):
    """Partial representation of an LLM completion before finalization.

    Extends LLMCompletion but with tool_calls being a list of ToolCallPartial.
    This is used during the processing stage before tool calls are fully parsed.

    Attributes:
        tool_calls: List of partial tool call representations.
    """

    tool_calls: list[ToolCallPartial | None] | None = None  # type: ignore


class LLMOutputPartial(LLMOutput):
    """Partial representation of LLM output before finalization.

    Extends LLMOutput but with completions being a list of LLMCompletionPartial.
    Used as an intermediate format during processing.

    Attributes:
        completions: List of partial completions.
    """

    completions: list[LLMCompletionPartial]  # type: ignore


def finalize_llm_output_partial(partial: LLMOutputPartial) -> LLMOutput:
    """Convert a partial LLM output into a finalized LLM output.

    Processes tool calls by parsing their arguments from raw JSON strings,
    handles errors in JSON parsing, and provides warnings for truncated completions.

    Args:
        partial: The partial LLM output to finalize.

    Returns:
        LLMOutput: The finalized LLM output with processed tool calls.

    Raises:
        CompletionTooLongException: If the completion was truncated due to length
            and resulted in empty text.
        ValueError: If tool call ID or function is missing in the partial data.
    """

    def _parse_tool_call(tc_partial: ToolCallPartial):
        if tc_partial.id is None:
            raise ValueError("Tool call ID not found in partial; check for parsing errors")
        if tc_partial.function is None:
            raise ValueError("Tool call function not found in partial; check for parsing errors")

        arguments: dict[str, Any] = {}
        # Attempt to load arguments into JSON
        try:
            arguments = json.loads(tc_partial.arguments_raw or "{}")
            parse_error = None
        # If the tool call arguments are not valid JSON, return an empty dict with the error
        except Exception as e:
            arguments = {"__parse_error_raw_args": tc_partial.arguments_raw}
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
                reasoning_tokens=c.reasoning_tokens,
            )
            for c in partial.completions
        ],
        usage=partial.usage,
        from_cache=False,
    )

    # If the completion is empty and was truncated (likely due to too much reasoning), raise an exception
    if output.first and output.first.finish_reason == "length" and output.first.no_text:
        raise CompletionTooLongException(
            "Completion empty due to truncation. Consider increasing max_new_tokens."
        )
    for c in output.completions:
        if c.finish_reason == "length":
            logger.warning(
                "Completion truncated due to length; consider increasing max_new_tokens."
            )

    return output


class AsyncLLMOutputStreamingCallback(Protocol):
    """Protocol for asynchronous streaming callbacks with batch index.

    Defines the expected signature for callbacks that handle streaming output
    with a batch index.

    Args:
        batch_index: The index of the current batch.
        llm_output: The LLM output for the current batch.
    """

    async def __call__(
        self,
        batch_index: int,
        llm_output: LLMOutput,
    ) -> None: ...


class AsyncSingleLLMOutputStreamingCallback(Protocol):
    """Protocol for asynchronous streaming callbacks without batch indexing.

    Defines the expected signature for callbacks that handle streaming output
    without batch indexing.

    Args:
        llm_output: The LLM output to process.
    """

    async def __call__(
        self,
        llm_output: LLMOutput,
    ) -> None: ...


class AsyncEmbeddingStreamingCallback(Protocol):
    """Protocol for sending progress updates for embedding generation."""

    async def __call__(self, progress: int) -> None: ...
