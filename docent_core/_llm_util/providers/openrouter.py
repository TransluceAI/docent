"""OpenRouter provider implementation using aiohttp library."""

import json
from typing import Any, Literal

import aiohttp
import backoff
from backoff.types import Details

from docent._log_util import get_logger
from docent.data_models.chat import ChatMessage, Content, ToolCall, ToolInfo
from docent_core._env_util import ENV
from docent_core._llm_util.data_models.exceptions import (
    CompletionTooLongException,
    ContextWindowException,
    NoResponseException,
    RateLimitException,
)
from docent_core._llm_util.data_models.llm_output import (
    AsyncSingleLLMOutputStreamingCallback,
    LLMCompletion,
    LLMOutput,
    UsageMetrics,
)

logger = get_logger(__name__)

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


class OpenRouterClient:
    """Async client for OpenRouter API using aiohttp."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or ENV.get("OPENROUTER_API_KEY")
        self.base_url = OPENROUTER_API_BASE

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completions_create(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 32,
        temperature: float = 1.0,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Make an async chat completion request."""
        url = f"{self.base_url}/chat/completions"

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status != 200:
                    try:
                        error_data: dict[str, Any] = await response.json()
                        error_msg: Any = error_data.get("error", {}).get(
                            "message", await response.text()
                        )
                    except Exception:
                        error_msg = await response.text()
                    if response.status == 429:
                        raise RateLimitException(f"OpenRouter rate limit: {error_msg}")
                    elif response.status == 400 and "context" in str(error_msg).lower():
                        raise ContextWindowException()
                    else:
                        raise Exception(f"OpenRouter API error ({response.status}): {error_msg}")

                return await response.json()


def get_openrouter_client_async(api_key: str | None = None) -> OpenRouterClient:
    _ = ENV
    return OpenRouterClient(api_key=api_key)


def _print_backoff_message(e: Details):
    logger.warning(
        f"OpenRouter backing off for {e['wait']:.2f}s due to {e['exception'].__class__.__name__}"  # type: ignore
    )


def _is_retryable_error(e: BaseException) -> bool:
    if isinstance(e, RateLimitException):
        return True
    if isinstance(e, ContextWindowException):
        return False
    if isinstance(e, aiohttp.ClientError):
        return True
    return False


def _parse_message_content(
    content: str | list[Content],
) -> str | list[dict[str, str]]:
    if isinstance(content, str):
        return content
    else:
        result: list[dict[str, str]] = []
        for sub_content in content:
            if sub_content.type == "text":
                result.append({"type": "text", "text": sub_content.text})
            else:
                raise ValueError(f"Unsupported content type: {sub_content.type}")
        return result


def parse_chat_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Convert ChatMessage list to OpenRouter format."""
    result: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "user":
            result.append(
                {
                    "role": "user",
                    "content": _parse_message_content(message.content),
                }
            )
        elif message.role == "assistant":
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": _parse_message_content(message.content),
            }
            if message.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in message.tool_calls
                ]
            result.append(msg)
        elif message.role == "tool":
            result.append(
                {
                    "role": "tool",
                    "content": _parse_message_content(message.content),
                    "tool_call_id": str(message.tool_call_id),
                }
            )
        elif message.role == "system":
            result.append(
                {
                    "role": "system",
                    "content": _parse_message_content(message.content),
                }
            )

    return result


def parse_tools(tools: list[ToolInfo]) -> list[dict[str, Any]]:
    """Convert ToolInfo objects to OpenRouter format."""
    result: list[dict[str, Any]] = []

    for tool in tools:
        result.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters.model_dump(exclude_none=True),
                },
            }
        )

    return result


def _parse_openrouter_tool_call(tc: dict[str, Any]) -> ToolCall:
    """Parse tool call from OpenRouter response."""
    if tc.get("type") != "function":
        return ToolCall(
            id=tc.get("id", "unknown"),
            function="unknown",
            arguments={},
            parse_error=f"Unsupported tool call type: {tc.get('type')}",
            type=None,
        )

    function_data = tc.get("function", {})
    arguments: dict[str, Any] = {}
    try:
        arguments = json.loads(function_data.get("arguments", "{}"))
        parse_error = None
    except Exception as e:
        arguments = {"__parse_error_raw_args": function_data.get("arguments", "")}
        parse_error = f"Couldn't parse tool call arguments as JSON: {e}"

    return ToolCall(
        id=tc.get("id", "unknown"),
        function=function_data.get("name", "unknown"),
        arguments=arguments,
        parse_error=parse_error,
        type="function",
    )


def parse_openrouter_completion(response: dict[str, Any], model: str) -> LLMOutput:
    """Parse OpenRouter completion response."""
    choices = response.get("choices", [])
    if not choices:
        return LLMOutput(
            model=model,
            completions=[],
            errors=[NoResponseException()],
        )

    usage_data = response.get("usage", {})
    usage = UsageMetrics(
        input=usage_data.get("prompt_tokens", 0),
        output=usage_data.get("completion_tokens", 0),
    )

    completions: list[LLMCompletion] = []
    for choice in choices:
        message = choice.get("message", {})
        tool_calls_data = message.get("tool_calls")

        completions.append(
            LLMCompletion(
                text=message.get("content"),
                finish_reason=choice.get("finish_reason"),
                tool_calls=(
                    [_parse_openrouter_tool_call(tc) for tc in tool_calls_data]
                    if tool_calls_data
                    else None
                ),
            )
        )

    return LLMOutput(
        model=response.get("model", model),
        completions=completions,
        usage=usage,
    )


@backoff.on_exception(
    backoff.expo,
    exception=(Exception,),
    giveup=lambda e: not _is_retryable_error(e),
    max_tries=5,
    factor=3.0,
    on_backoff=_print_backoff_message,
)
async def get_openrouter_chat_completion_async(
    client: OpenRouterClient,
    messages: list[ChatMessage],
    model_name: str,
    tools: list[ToolInfo] | None = None,
    tool_choice: Literal["auto", "required"] | None = None,
    max_new_tokens: int = 32,
    temperature: float = 1.0,
    reasoning_effort: Literal["low", "medium", "high"] | None = None,
    logprobs: bool = False,
    top_logprobs: int | None = None,
    timeout: float = 30.0,
) -> LLMOutput:
    """Get completion from OpenRouter."""
    if logprobs or top_logprobs is not None:
        raise NotImplementedError(
            "We have not implemented logprobs or top_logprobs for OpenRouter yet."
        )

    if reasoning_effort is not None:
        logger.warning("OpenRouter does not support reasoning_effort parameter, ignoring.")

    input_messages = parse_chat_messages(messages)
    input_tools = parse_tools(tools) if tools else None

    response = await client.chat_completions_create(
        model=model_name,
        messages=input_messages,
        tools=input_tools,
        tool_choice=tool_choice,
        max_tokens=max_new_tokens,
        temperature=temperature,
        timeout=timeout,
    )

    output = parse_openrouter_completion(response, model_name)

    if output.first and output.first.finish_reason == "length" and output.first.no_text:
        raise CompletionTooLongException(
            "Completion empty due to truncation. Consider increasing max_new_tokens."
        )

    return output


@backoff.on_exception(
    backoff.expo,
    exception=(Exception,),
    giveup=lambda e: not _is_retryable_error(e),
    max_tries=5,
    factor=3.0,
    on_backoff=_print_backoff_message,
)
async def get_openrouter_chat_completion_streaming_async(
    client: OpenRouterClient,
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
    timeout: float = 30.0,
) -> LLMOutput:
    """Get streaming completion from OpenRouter (falls back to non-streaming)."""
    logger.warning("Streaming not yet implemented for OpenRouter, using non-streaming.")

    return await get_openrouter_chat_completion_async(
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


async def is_openrouter_api_key_valid(api_key: str) -> bool:
    """Test whether an OpenRouter API key is valid."""
    client = OpenRouterClient(api_key=api_key)

    try:
        # Make a minimal request to test the key
        await client.chat_completions_create(
            model="openai/gpt-5-nano",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            timeout=10.0,
        )
        return True
    except Exception as e:
        if "authentication" in str(e).lower() or "authorization" in str(e).lower():
            return False
        raise
