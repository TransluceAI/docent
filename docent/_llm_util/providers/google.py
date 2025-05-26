import asyncio
from typing import Literal

import backoff
import requests
from backoff.types import Details
from google import genai
from google.genai import errors, types
from google.genai.client import AsyncClient as AsyncGoogle

from docent._env_util import ENV
from docent._llm_util.data_models.exceptions import (
    CompletionTooLongException,
    RateLimitException,
)
from docent._llm_util.data_models.llm_output import (
    AsyncSingleLLMOutputStreamingCallback,
    LLMCompletion,
    LLMOutput,
)
from docent._log_util import get_logger
from docent.data_models.chat import ChatMessage, Content, ToolInfo


def get_google_client_async() -> AsyncGoogle:
    # Ensure environment variables are loaded.
    # Technically you don't have to run this, but just makes clear where the envvars are used
    _ = ENV

    return genai.Client().aio


logger = get_logger(__name__)


def _print_backoff_message(e: Details):
    logger.warning(
        f"Google backing off for {e['wait']:.2f}s due to {e['exception'].__class__.__name__}"  # type: ignore
    )


def _is_retryable_error(exception: BaseException) -> bool:
    """Checks if the exception is a retryable error based on the criteria."""
    if isinstance(exception, errors.APIError):
        return exception.code in [429, 502, 503, 504]
    if isinstance(exception, requests.exceptions.ConnectionError):
        return True
    return False


@backoff.on_exception(
    backoff.expo,
    exception=(Exception),
    giveup=lambda e: not _is_retryable_error(e),
    max_tries=3,
    factor=2.0,
    on_backoff=_print_backoff_message,
)
async def get_google_chat_completion_async(
    client: AsyncGoogle,
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
    if logprobs or top_logprobs is not None:
        raise NotImplementedError(
            "We have not implemented logprobs or top_logprobs for Google yet."
        )

    system, input_messages = _parse_chat_messages(messages)
    if tools:
        raise NotImplementedError(f"We have not implemented tools for Google yet, got: {tools}")

    try:
        async with asyncio.timeout(timeout) if timeout else asyncio.nullcontext():  # type: ignore
            raw_output = await client.models.generate_content(
                model=model_name,
                contents=input_messages,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    thinking_config=types.ThinkingConfig(
                        include_thoughts=True,
                        thinking_budget=(
                            int(
                                max_new_tokens
                                * (
                                    0.75
                                    if reasoning_effort == "high"
                                    else (0.5 if reasoning_effort == "medium" else 0.25)
                                )
                            )
                            if reasoning_effort
                            else None
                        )  # Just heuristics
                    ),
                    max_output_tokens=max_new_tokens,
                    system_instruction=system,
                ),
            )

            output = _parse_google_completion(raw_output, model_name)
            if output.first and output.first.finish_reason == "length" and output.first.no_text:
                raise CompletionTooLongException(
                    f"Completion empty due to truncation. Consider increasing max_new_tokens (currently {max_new_tokens})."
                )

            return output
    except errors.APIError as e:
        if e.code in [429, 502, 503, 504]:
            raise RateLimitException(e) from e
        raise


async def get_google_chat_completion_streaming_async(
    client: AsyncGoogle,
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
) -> LLMOutput:
    # TODO: implement this with actual streaming.
    output = await get_google_chat_completion_async(
        client=client,
        messages=messages,
        model_name=model_name,
        tools=tools,
        tool_choice=tool_choice,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        logprobs=logprobs,
        top_logprobs=top_logprobs,
        timeout=timeout,
    )
    if streaming_callback is not None:
        await streaming_callback(output)
    return output


def _parse_chat_messages(
    messages: list[ChatMessage],
) -> tuple[str | None, list[types.Content]]:
    result: list[types.Content] = []
    system_prompt: str | None = None

    for message in messages:
        if message.role == "user" or message.role == "assistant":
            result.append(
                types.Content(
                    role=message.role if message.role == "user" else "model",
                    parts=_parse_message_content(message.content),
                )
            )
        elif message.role == "system":
            system_prompt = message.text
        else:
            raise ValueError(f"Unknown message role: {message.role}")

    return system_prompt, result


def _parse_message_content(content: str | list[Content]) -> list[types.Part]:
    if isinstance(content, str):
        return [types.Part.from_text(text=content)]
    else:
        result: list[types.Part] = []
        for sub_content in content:
            if sub_content.type == "text":
                result.append(types.Part.from_text(text=sub_content.text))
            else:
                raise ValueError(f"Unsupported content type: {sub_content.type}")
        return result


def _parse_google_completion(message: types.GenerateContentResponse, model: str) -> LLMOutput:
    if not message.candidates:
        return LLMOutput(
            model=model,
            completions=[],
            errors=["no_response"],
        )

    candidate = message.candidates[0]

    if candidate.finish_reason == types.FinishReason.STOP:
        finish_reason = "stop"
    elif candidate.finish_reason == types.FinishReason.MAX_TOKENS:
        finish_reason = "length"
    else:
        finish_reason = "error"

    text = ''
    content_parts = candidate.content.parts if candidate.content else []
    content_parts = content_parts or []
    # tool_calls: list[ToolCall] = []
    for part in content_parts:
        if part.text is not None and not part.thought:
            text += part.text
        elif part.thought:
            logger.warning("Google returned thinking block; we should support this soon.")
        else:
            raise ValueError(f"Unknown content part: {part}")

    return LLMOutput(
        model=model,
        completions=[
            LLMCompletion(
                text=text,
                finish_reason=finish_reason,
            )
        ],
    )
