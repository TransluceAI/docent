from typing import Any, Literal, cast

import backoff

# all errors: https://docs.anthropic.com/en/api/errors
from anthropic import (
    AsyncAnthropic,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from anthropic._types import NOT_GIVEN
from anthropic.types import (
    InputJSONDelta,
    Message,
    MessageParam,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
    RawMessageDeltaEvent,
    RawMessageStartEvent,
    RawMessageStreamEvent,
    SignatureDelta,
    TextBlockParam,
    TextDelta,
    ThinkingDelta,
    ToolChoiceAnyParam,
    ToolChoiceAutoParam,
    ToolChoiceParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
)
from backoff.types import Details

from docent._llm_util.data_models.exceptions import (
    CompletionTooLongException,
    ContextWindowException,
    NoResponseException,
    RateLimitException,
)
from docent._llm_util.data_models.llm_output import (
    AsyncSingleLLMOutputStreamingCallback,
    FinishReasonType,
    LLMCompletion,
    LLMCompletionPartial,
    LLMOutput,
    LLMOutputPartial,
    ToolCallPartial,
    UsageMetrics,
    finalize_llm_output_partial,
)
from docent._llm_util.providers.common import (
    async_timeout_ctx,
    reasoning_budget,
)
from docent._log_util import get_logger
from docent.data_models.chat import ChatMessage, Content, ToolCall, ToolInfo

logger = get_logger(__name__)


def _print_backoff_message(e: Details):
    logger.warning(
        f"Anthropic backing off for {e['wait']:.2f}s due to {e['exception'].__class__.__name__}"  # type: ignore
    )


def _is_retryable_error(e: BaseException) -> bool:
    if (
        isinstance(e, BadRequestError)
        or isinstance(e, ContextWindowException)
        or isinstance(e, AuthenticationError)
        or isinstance(e, NotImplementedError)
        or isinstance(e, PermissionDeniedError)
        or isinstance(e, NotFoundError)
        or isinstance(e, UnprocessableEntityError)
    ):
        return False
    return True


def _parse_message_content(content: str | list[Content]) -> str | list[TextBlockParam]:
    if isinstance(content, str):
        return content
    else:
        result: list[TextBlockParam] = []
        for sub_content in content:
            if sub_content.type == "text":
                result.append(TextBlockParam(text=sub_content.text, type="text"))
            else:
                raise ValueError(f"Unsupported content type: {sub_content.type}")
        return result


def parse_chat_messages(messages: list[ChatMessage]) -> tuple[str | None, list[MessageParam]]:
    result: list[MessageParam] = []
    system_prompt: str | None = None

    for message in messages:
        if message.role == "user":
            result.append(
                MessageParam(
                    role=message.role,
                    content=_parse_message_content(message.content),
                )
            )
        elif message.role == "assistant":
            message_content = _parse_message_content(message.content)
            # Build content list without creating empty text blocks
            if isinstance(message_content, str):
                stripped = message_content.strip()
                all_content = cast(
                    list[TextBlockParam | ToolUseBlockParam],
                    ([TextBlockParam(text=stripped, type="text")] if stripped else []),
                )
            else:
                all_content = cast(list[TextBlockParam | ToolUseBlockParam], message_content)
            for tool_call in message.tool_calls or []:
                all_content.append(
                    ToolUseBlockParam(
                        id=tool_call.id,
                        input=tool_call.arguments,
                        name=tool_call.function,
                        type="tool_use",
                    )
                )
            result.append(
                MessageParam(
                    role="assistant",
                    content=all_content,
                )
            )
        elif message.role == "tool":
            result.append(
                MessageParam(
                    role="user",
                    content=[
                        ToolResultBlockParam(
                            tool_use_id=str(message.tool_call_id),
                            type="tool_result",
                            content=_parse_message_content(message.content),
                            is_error=message.error is not None,
                        )
                    ],
                )
            )
        elif message.role == "system":
            system_prompt = message.text
        else:
            raise ValueError(f"Unknown message role: {message.role}")

    return system_prompt, result


def parse_tools(tools: list[ToolInfo]) -> list[ToolParam]:
    return [
        ToolParam(
            name=tool.name,
            description=tool.description,
            input_schema=tool.parameters.model_dump(exclude_none=True),
        )
        for tool in tools
    ]


def _parse_tool_choice(tool_choice: Literal["auto", "required"] | None) -> ToolChoiceParam | None:
    if tool_choice is None:
        return None
    elif tool_choice == "auto":
        return ToolChoiceAutoParam(type="auto")
    elif tool_choice == "required":
        return ToolChoiceAnyParam(type="any")


def _convert_anthropic_error(e: Exception):
    if isinstance(e, BadRequestError):
        if "context limit" in e.message.lower() or "prompt is too long" in e.message.lower():
            return ContextWindowException()
    if isinstance(e, RateLimitError):
        return RateLimitException(e)
    return None


@backoff.on_exception(
    backoff.expo,
    exception=(Exception),
    giveup=lambda e: not _is_retryable_error(e),
    max_tries=5,
    factor=3.0,
    on_backoff=_print_backoff_message,
)
async def get_anthropic_chat_completion_streaming_async(
    client: AsyncAnthropic,
    streaming_callback: AsyncSingleLLMOutputStreamingCallback | None,
    messages: list[ChatMessage],
    model_name: str,
    tools: list[ToolInfo] | None = None,
    tool_choice: Literal["auto", "required"] | None = None,
    max_new_tokens: int = 32,
    temperature: float = 1.0,
    reasoning_effort: Literal["low", "medium", "high"] | None = None,
    logprobs: bool = False,
    top_logprobs: int | None = None,
    timeout: float = 5.0,
):
    if logprobs or top_logprobs is not None:
        raise NotImplementedError(
            "We have not implemented logprobs or top_logprobs for Anthropic yet."
        )

    system, input_messages = parse_chat_messages(messages)
    input_tools = parse_tools(tools) if tools else NOT_GIVEN

    try:
        async with async_timeout_ctx(timeout):
            stream = await client.messages.create(
                model=model_name,
                messages=input_messages,
                thinking=(
                    {
                        "type": "enabled",
                        "budget_tokens": reasoning_budget(max_new_tokens, reasoning_effort),
                    }
                    if reasoning_effort
                    else NOT_GIVEN
                ),
                tools=input_tools,
                tool_choice=_parse_tool_choice(tool_choice) or NOT_GIVEN,
                max_tokens=max_new_tokens,
                temperature=temperature,
                system=system if system is not None else NOT_GIVEN,
                stream=True,
            )

            llm_output_partial = None
            async for chunk in stream:
                llm_output_partial = update_llm_output(llm_output_partial, chunk)
                if streaming_callback:
                    await streaming_callback(finalize_llm_output_partial(llm_output_partial))

            # Fully parse the partial output
            if llm_output_partial:
                return finalize_llm_output_partial(llm_output_partial)
            else:
                # Streaming did not produce anything
                return LLMOutput(model=model_name, completions=[], errors=[NoResponseException()])
    except (RateLimitError, BadRequestError) as e:
        if e2 := _convert_anthropic_error(e):
            raise e2 from e
        else:
            raise


FINISH_REASON_MAP: dict[str, FinishReasonType] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "refusal": "refusal",
}


def update_llm_output(
    llm_output_partial: LLMOutputPartial | None,
    chunk: RawMessageStreamEvent,
):
    """
    Note that Anthropic only allows one message to be streamed at a time.
    Thus there can only be one completion.
    """

    usage: UsageMetrics = llm_output_partial.usage if llm_output_partial else UsageMetrics()

    if llm_output_partial is not None:
        cur_text: str | None = llm_output_partial.completions[0].text
        cur_reasoning_tokens: str | None = llm_output_partial.completions[0].reasoning_tokens
        cur_finish_reason: FinishReasonType | None = llm_output_partial.completions[0].finish_reason
        cur_tool_calls: list[ToolCallPartial | None] | None = llm_output_partial.completions[0].tool_calls  # type: ignore[assignment]
        cur_model = llm_output_partial.model
    else:
        cur_text, cur_reasoning_tokens, cur_finish_reason, cur_model = None, None, None, None
        cur_tool_calls = None

    if isinstance(chunk, RawMessageStartEvent):
        cur_model = chunk.message.model
    elif isinstance(chunk, RawContentBlockStartEvent):
        # If a tool_use block starts, initialize a ToolCallPartial slot using the block index
        content_block = chunk.content_block
        if content_block.type == "tool_use":
            # Ensure the tool_calls array exists and is long enough
            index = chunk.index
            cur_tool_calls = cur_tool_calls or []
            if index >= len(cur_tool_calls):
                cur_tool_calls.extend([None] * (index - len(cur_tool_calls) + 1))

            # Initialize the partial with id/name; arguments will stream via InputJSONDelta
            cur_tool_calls[index] = ToolCallPartial(
                id=content_block.id,
                function=content_block.name,
                arguments_raw="",
                type="function",
            )
    elif isinstance(chunk, RawContentBlockDeltaEvent):
        if isinstance(chunk.delta, TextDelta):
            cur_text = (cur_text or "") + chunk.delta.text
        elif isinstance(chunk.delta, ThinkingDelta):
            cur_reasoning_tokens = (cur_reasoning_tokens or "") + chunk.delta.thinking
        elif isinstance(chunk.delta, InputJSONDelta):
            # Append streamed JSON into the corresponding ToolCallPartial
            index = chunk.index
            if (
                cur_tool_calls is None
                or index >= len(cur_tool_calls)
                or cur_tool_calls[index] is None
            ):
                # This should not happen with a well-behaved API, log and skip
                logger.warning(
                    f"Received InputJSONDelta before start event at index {index}, skipping"
                )
            else:
                cur_tool_calls[index] = ToolCallPartial(
                    id=cur_tool_calls[index].id,  # type: ignore[union-attr]
                    function=cur_tool_calls[index].function,  # type: ignore[union-attr]
                    arguments_raw=(cur_tool_calls[index].arguments_raw or "") + chunk.delta.partial_json,  # type: ignore[union-attr]
                    type="function",
                )
        elif isinstance(chunk.delta, SignatureDelta):
            logger.debug(
                "Anthropic streamed thinking signature block; we should support this soon."
            )
        else:
            raise ValueError(f"Unsupported delta type: {type(chunk.delta)}")
    elif isinstance(chunk, RawContentBlockStopEvent):
        # Nothing to do on stop; tool call is considered assembled once stop occurs
        pass
    elif isinstance(chunk, RawMessageDeltaEvent):
        if stop_reason := chunk.delta.stop_reason:
            cur_finish_reason = FINISH_REASON_MAP.get(stop_reason)
        # These token counts are cumulative
        usage = UsageMetrics(
            input=chunk.usage.input_tokens,
            output=chunk.usage.output_tokens,
            cache_read=chunk.usage.cache_read_input_tokens,
            cache_write=chunk.usage.cache_creation_input_tokens,
        )

    completions: list[LLMCompletionPartial] = []
    completions.append(
        LLMCompletionPartial(
            text=cur_text,
            tool_calls=cur_tool_calls,
            reasoning_tokens=cur_reasoning_tokens,
            finish_reason=cur_finish_reason,
        )
    )

    assert cur_model is not None, "First chunk should always set the cur_model"
    return LLMOutputPartial(
        completions=completions,  # type: ignore[arg-type]
        model=cur_model,
        usage=usage,
    )


@backoff.on_exception(
    backoff.expo,
    exception=(Exception),
    giveup=lambda e: not _is_retryable_error(e),
    max_tries=5,
    factor=3.0,
    on_backoff=_print_backoff_message,
)
async def get_anthropic_chat_completion_async(
    client: AsyncAnthropic,
    messages: list[ChatMessage],
    model_name: str,
    tools: list[ToolInfo] | None = None,
    tool_choice: Literal["auto", "required"] | None = None,
    max_new_tokens: int = 32,
    temperature: float = 1.0,
    reasoning_effort: Literal["low", "medium", "high"] | None = None,
    logprobs: bool = False,
    top_logprobs: int | None = None,
    timeout: float = 5.0,
) -> LLMOutput:
    """
    Note from kevin 1/29/2025:
        logprobs and top_logprobs were recently added to the OpenAI endpoint,
        which broke some of my code. I'm just adding it to Anthropic as well, to maintain
        "compatibility".

        We should actually implement this at some point, but it does not work.
    """

    if logprobs or top_logprobs is not None:
        raise NotImplementedError(
            "We have not implemented logprobs or top_logprobs for Anthropic yet."
        )

    system, input_messages = parse_chat_messages(messages)
    input_tools = parse_tools(tools) if tools else NOT_GIVEN

    try:
        async with async_timeout_ctx(timeout):
            raw_output = await client.messages.create(
                model=model_name,
                messages=input_messages,
                thinking=(
                    {
                        "type": "enabled",
                        "budget_tokens": reasoning_budget(max_new_tokens, reasoning_effort),
                    }
                    if reasoning_effort
                    else NOT_GIVEN
                ),
                tools=input_tools,
                tool_choice=_parse_tool_choice(tool_choice) or NOT_GIVEN,
                max_tokens=max_new_tokens,
                temperature=temperature,
                system=system if system is not None else NOT_GIVEN,
            )

            output = parse_anthropic_completion(raw_output, model_name)
            if output.first and output.first.finish_reason == "length" and output.first.no_text:
                raise CompletionTooLongException(
                    "Completion empty due to truncation. Consider increasing max_new_tokens."
                )

            return output
    except (RateLimitError, BadRequestError) as e:
        if e2 := _convert_anthropic_error(e):
            raise e2 from e
        else:
            raise


def get_anthropic_client_async(api_key: str | None = None) -> AsyncAnthropic:
    return AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()


def parse_anthropic_completion(message: Message | None, model: str) -> LLMOutput:
    if message is None:
        return LLMOutput(
            model=model,
            completions=[],
            errors=[NoResponseException()],
        )

    if message.stop_reason == "end_turn":
        finish_reason = "stop"
    elif message.stop_reason == "max_tokens":
        finish_reason = "length"
    elif message.stop_reason == "stop_sequence":
        finish_reason = "stop"
    elif message.stop_reason == "tool_use":
        finish_reason = "tool_calls"
    elif message.stop_reason == "refusal":
        finish_reason = "refusal"
    else:
        finish_reason = "error"

    text = None
    tool_calls: list[ToolCall] = []
    reasoning_tokens = None
    for block in message.content:
        if block.type == "text":
            if text is not None:
                raise ValueError(
                    "Anthropic API returned multiple text blocks; this was unexpected."
                )
            text = block.text
        elif block.type == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=block.id,
                    function=block.name,
                    arguments=cast(dict[str, Any], block.input),
                    type="function",
                )
            )
        elif block.type == "thinking":
            reasoning_tokens = block.thinking
        else:
            raise ValueError(f"Unknown block type: {block.type}")

    usage = UsageMetrics(
        input=message.usage.input_tokens,
        output=message.usage.output_tokens,
        cache_read=message.usage.cache_read_input_tokens,
        cache_write=message.usage.cache_creation_input_tokens,
    )

    return LLMOutput(
        model=model,
        completions=[
            LLMCompletion(
                text=text,
                tool_calls=tool_calls,
                reasoning_tokens=reasoning_tokens,
                finish_reason=finish_reason,  # type: ignore
            )
        ],
        usage=usage,
    )


async def is_anthropic_api_key_valid(api_key: str) -> bool:
    """
    Test whether an Anthropic API key is valid or invalid.

    Args:
        api_key: The Anthropic API key to test.

    Returns:
        bool: True if the API key is valid, False otherwise.
    """
    client = AsyncAnthropic(api_key=api_key)

    try:
        # Attempt to make a simple API call with minimal tokens/cost
        await client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return True
    except AuthenticationError:
        # API key is invalid
        return False
    except Exception:
        # Any other error means the key might be valid but there's another issue
        # For testing key validity specifically, we'll return False only for auth errors
        return True
