"""
At some point we'll want to do a refactor to support different types of provider/key swapping
due to different scenarios. However, this'll probably be a breaking change, which is why I'm
not doing it now.

- mengk
"""

import os
import traceback
from contextlib import nullcontext
from functools import partial
from typing import Any, Literal, Protocol, Sequence, TypedDict

import anyio
from anthropic import AsyncAnthropic
from docent._llm_util import anthropic, openai
from docent._llm_util.anthropic import (
    get_anthropic_chat_completion_async,
    get_anthropic_chat_completion_streaming_async,
)
from docent._llm_util.llm_cache import LLMCache
from docent._llm_util.openai import (
    get_openai_chat_completion_async,
    get_openai_chat_completion_streaming_async,
)
from docent._llm_util.types import (
    AsyncSingleStreamingCallback,
    AsyncStreamingCallback,
    ChatMessage,
    LLMApiKeys,
    LLMOutput,
    ModelCallParams,
    RateLimitException,
    ToolInfo,
    get_single_streaming_callback,
    parse_chat_message,
)
from docent._log_util import get_logger
from openai import AsyncOpenAI

logger = get_logger(__name__)


class AllOutputsErroredException(Exception):
    pass


class SingleOutputGetter(Protocol):
    async def __call__(
        self,
        client: Any,
        messages: list[ChatMessage],
        model_name: str,
        *,
        tools: list[ToolInfo] | None,
        tool_choice: Literal["auto", "required"] | None,
        max_new_tokens: int,
        temperature: float,
        reasoning_effort: Literal["low", "medium", "high"] | None,
        logprobs: bool,
        top_logprobs: int | None,
        timeout: float,
    ) -> LLMOutput: ...


class SingleStreamingOutputGetter(Protocol):
    async def __call__(
        self,
        client: Any,
        streaming_callback: AsyncSingleStreamingCallback | None,
        messages: list[ChatMessage],
        model_name: str,
        *,
        tools: list[ToolInfo] | None,
        tool_choice: Literal["auto", "required"] | None,
        max_new_tokens: int,
        temperature: float,
        reasoning_effort: Literal["low", "medium", "high"] | None,
        logprobs: bool,
        top_logprobs: int | None,
        timeout: float,
    ) -> LLMOutput: ...


class ProviderConfig(TypedDict):
    keys: list[str]
    current_key_index: int
    async_client: AsyncOpenAI | AsyncAnthropic
    single_output_getter: SingleOutputGetter
    single_streaming_output_getter: SingleStreamingOutputGetter
    models: dict[str, str]


async def _parallelize_calls(
    single_output_getter: SingleOutputGetter | SingleStreamingOutputGetter,
    streaming_callback: AsyncStreamingCallback | None,
    completion_callback: AsyncStreamingCallback | None,
    # Arguments for the individual completion getter
    client: Any,
    messages_list: list[list[ChatMessage]],
    model_name: str,
    tools: list[ToolInfo] | None,
    tool_choice: Literal["auto", "required"] | None,
    max_new_tokens: int,
    temperature: float,
    reasoning_effort: Literal["low", "medium", "high"] | None,
    logprobs: bool,
    top_logprobs: int | None,
    timeout: float,
    max_concurrency: int | None,
    semaphore: anyio.Semaphore | None,
    use_tqdm: bool,
    cache: LLMCache | None = None,
):
    base_func = partial(
        single_output_getter,
        client=client,
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
    if max_concurrency is not None:
        ctx = anyio.Semaphore(max_concurrency)
    else:
        ctx = nullcontext() if semaphore is None else semaphore

    responses: list[LLMOutput | None] = [None for _ in messages_list]

    async def _limited_task(i: int, messages: list[ChatMessage]) -> LLMOutput:
        nonlocal responses

        async with ctx:
            try:
                # Use streaming if streaming_callback is provided, otherwise use non-streaming
                if streaming_callback is None:
                    result = await base_func(client=client, messages=messages)
                    # Call the completion callback if provided
                    if completion_callback:
                        await completion_callback(i, result)
                else:
                    result = await base_func(
                        client=client,
                        streaming_callback=get_single_streaming_callback(i, streaming_callback),
                        messages=messages,
                    )

                responses[i] = result
            except Exception as e:
                error_message = (
                    f"Call to {model_name} failed even with backoff: {e.__class__.__name__}."
                )

                # If the error is not a rate limit (which we don't need details for), add the traceback
                if not isinstance(e, RateLimitException):
                    error_message += f" Failure traceback:\n{traceback.format_exc()}"

                logger.error(error_message)
                error_output = LLMOutput(
                    model=model_name,
                    completions=[],
                    errors=["rate_limit" if isinstance(e, RateLimitException) else "other"],
                )
                # Call the completion callback for errors too if provided
                if completion_callback:
                    await completion_callback(i, error_output)
                return error_output

    def _cache_responses():
        nonlocal responses, cache

        if cache is not None:
            indices = [
                i
                for i, response in enumerate(responses)
                if isinstance(response, LLMOutput) and not response.did_error
            ]
            cache.set_batch(
                [messages_list[i] for i in indices],
                model_name,
                [responses[i] for i in indices],
                tools=tools,
                tool_choice=tool_choice,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                logprobs=logprobs,
                top_logprobs=top_logprobs,
            )
            return len(indices)
        else:
            return 0

    # Get all results
    try:
        async with anyio.create_task_group() as tg:
            for i, messages in enumerate(messages_list):
                tg.start_soon(_limited_task, i, messages)
    except anyio.get_cancelled_exc_class():
        # Cache what we have so far if something got cancelled
        num_cached = _cache_responses()
        logger.info(
            f"Cancelled {len(messages_list) - num_cached} unfinished LLM API calls; cached {num_cached} completed responses"
        )
        raise

    # Cache results if available
    if cache is not None:
        _cache_responses()

    return responses


class LLMManager:
    def __init__(
        self,
        default_provider: str = "anthropic",
        provider_blacklist: list[str] | None = None,
        max_concurrency: int = 100,
        rotate_providers: bool = True,
        use_cache: bool = False,
        llm_api_keys: LLMApiKeys | None = None,
    ):
        self.cache = LLMCache() if use_cache else None
        self.semaphore = anyio.Semaphore(max_concurrency)

        # Set API keys using ENV and function args
        hot_anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        hot_openai_api_key = os.getenv("OPENAI_API_KEY")
        if llm_api_keys:
            hot_anthropic_api_key = llm_api_keys["anthropic_key"] or hot_anthropic_api_key
            hot_openai_api_key = llm_api_keys["openai_key"] or hot_openai_api_key

        # Initialize providers that have API keys
        self.providers: dict[str, ProviderConfig] = {}
        if hot_anthropic_api_key:
            self.providers["anthropic"] = {
                "keys": [hot_anthropic_api_key],
                "current_key_index": 0,
                "async_client": anthropic.get_anthropic_client_async(),
                "single_output_getter": get_anthropic_chat_completion_async,
                "single_streaming_output_getter": get_anthropic_chat_completion_streaming_async,
                "models": {
                    "reasoning_smart": "claude-3-7-sonnet-20250219",
                    "smart": "claude-3-7-sonnet-20250219",
                    "fast": "claude-3-haiku-20240307",
                },
            }
        if hot_openai_api_key:
            self.providers["openai"] = {
                "keys": [hot_openai_api_key],
                "current_key_index": 0,
                "async_client": openai.get_openai_client_async(),
                "single_output_getter": get_openai_chat_completion_async,
                "single_streaming_output_getter": get_openai_chat_completion_streaming_async,
                "models": {
                    "smarter": "gpt-4.5-preview-2025-02-27",
                    "smart": "gpt-4o-2024-08-06",
                    "fast": "gpt-4o-mini-2024-07-18",
                    "reasoning_fast": "o3-mini",
                    "reasoning_smart_preview": "o1-preview",
                    "reasoning_smart": "o1",
                },
            }

        if not self.providers:
            raise ValueError("No valid API keys found for any provider")

        # Check if default provider exists, or pick the first available one
        if default_provider not in self.providers:
            new_default_provider = next(iter(self.providers.keys()))
            logger.warning(
                f"API key missing for default provider '{default_provider}', using '{new_default_provider}' instead"
            )
            default_provider = new_default_provider

        # Reorder provider_order to put default_provider first
        if rotate_providers:
            self.provider_order = [default_provider] + [
                p for p in self.providers.keys() if p != default_provider
            ]
        else:
            self.provider_order = [default_provider]

        if provider_blacklist is not None:
            self.provider_order = [p for p in self.provider_order if p not in provider_blacklist]

        self.current_provider_index = 0
        self.provider = self.providers[self.provider_order[self.current_provider_index]]
        self.model_name_index = 0

    async def get_completions(
        self,
        messages_list: list[list[ChatMessage]],
        model_category: str | None = None,
        model_call_params: list[ModelCallParams] | None = None,
        tools: list[ToolInfo] | None = None,
        tool_choice: Literal["auto", "required"] | None = None,
        max_new_tokens: int = 32,
        temperature: float = 1.0,
        reasoning_effort: Literal["low", "medium", "high"] | None = None,
        logprobs: bool = False,
        top_logprobs: int | None = None,
        max_concurrency: int | None = None,
        timeout: float = 5.0,
        streaming_callback: AsyncStreamingCallback | None = None,
        completion_callback: AsyncStreamingCallback | None = None,
    ) -> list[LLMOutput]:
        """
        If max_concurrency is None, use LLManager.semaphore to manage concurrency
        """
        results: list[LLMOutput | None] = [None] * len(messages_list)
        providers_rate_limited = {p: False for p in self.providers.keys()}

        model_call_params_passed_explicitly = model_call_params is not None
        if model_call_params_passed_explicitly:
            model_name = model_call_params[0].model_name
            reasoning_effort = model_call_params[0].reasoning_effort

        while True:
            try:
                client = self.provider["async_client"]
                client.api_key = self.provider["keys"][self.provider["current_key_index"]]
                if not model_call_params_passed_explicitly:
                    if model_category in self.provider["models"]:
                        model_name = self.provider["models"][model_category]
                    else:
                        raise AllOutputsErroredException(
                            f"Model category '{model_category}' not found in provider '{self.provider_order[self.current_provider_index]}'"
                        )

                # Check cache if available
                if self.cache is not None:
                    uncached_indices: list[int] = []
                    uncached_messages: list[list[ChatMessage]] = []
                    hits = 0

                    for i, messages in enumerate(messages_list):
                        cached_result = self.cache.get(
                            messages,
                            model_name,
                            tools=tools,
                            tool_choice=tool_choice,
                            reasoning_effort=reasoning_effort,
                            temperature=temperature,
                            logprobs=logprobs,
                            top_logprobs=top_logprobs,
                        )
                        if cached_result is not None:
                            results[i] = cached_result
                            hits += 1
                        else:
                            uncached_indices.append(i)
                            uncached_messages.append(messages)

                    misses = len(messages_list) - hits
                    logger.info(f"{model_name}: {hits} cache hits, {misses} misses")
                # Otherwise, everything is uncached
                else:
                    uncached_indices = list(range(len(messages_list)))
                    uncached_messages = messages_list

                # Call streaming callback for cached messages
                if streaming_callback is not None:
                    for i, messages in enumerate(messages_list):
                        result = results[i]
                        if result is not None:
                            await streaming_callback(i, result)

                # Call completion callback for cached messages
                if completion_callback is not None:
                    for i, messages in enumerate(messages_list):
                        result = results[i]
                        if result is not None:
                            await completion_callback(i, result)

                # Get completions for uncached messages
                if uncached_messages:
                    outputs = await _parallelize_calls(
                        (
                            self.provider["single_output_getter"]
                            if streaming_callback is None
                            else self.provider["single_streaming_output_getter"]
                        ),
                        streaming_callback,
                        completion_callback,
                        client,
                        uncached_messages,
                        model_name,
                        tools=tools,
                        tool_choice=tool_choice,
                        max_new_tokens=max_new_tokens,
                        temperature=temperature,
                        reasoning_effort=reasoning_effort,
                        logprobs=logprobs,
                        top_logprobs=top_logprobs,
                        timeout=timeout,
                        max_concurrency=max_concurrency,
                        semaphore=self.semaphore,
                        use_tqdm=len(uncached_messages) >= 5,
                        cache=self.cache,
                    )

                    # Track rate limiting
                    num_rate_limited = sum(
                        1 for o in outputs if o.errors and "rate_limit" in o.errors
                    )
                    if num_rate_limited > 0:
                        providers_rate_limited[self.provider_order[self.current_provider_index]] = (
                            True
                        )
                    # Heuristic: if >= 50% of the outputs are rate limited, raise an exception
                    if num_rate_limited >= len(outputs) / 2:
                        raise AllOutputsErroredException

                    # If all completions are None, rotate keys and swap provider
                    # TODO(kevin): this is not a great key swapping condition; we should refactor at some point.
                    if all(output.did_error for output in outputs):
                        raise AllOutputsErroredException

                    # Parse completions and update results
                    for i, (messages, output) in enumerate(zip(uncached_messages, outputs)):
                        results[uncached_indices[i]] = output

                break  # Break to return the results
            except AllOutputsErroredException:
                if not self._rotate_key_for_provider():
                    if not model_call_params_passed_explicitly:
                        rotation_succeeded = self._rotate_provider()
                    else:
                        new_model_params = self._rotate_model_name(model_call_params)
                        if new_model_params is None:
                            rotation_succeeded = False
                        else:
                            model_name = new_model_params.model_name
                            reasoning_effort = new_model_params.reasoning_effort
                            rotation_succeeded = True
                    if not rotation_succeeded:
                        if all(providers_rate_limited.values()):
                            raise RateLimitException("All providers were rate limited")
                        break  # Break to return the results as is

        # If any results are None, set them to an error result
        final_results: list[LLMOutput] = []
        for result in results:
            if result is None:
                final_results.append(
                    LLMOutput(
                        model=f"all {','.join(self.providers.keys())} exhausted",
                        completions=[],
                        errors=["all_providers_exhausted"],
                    )
                )
            else:
                final_results.append(result)

        return final_results

    def _rotate_key_for_provider(self) -> bool:
        """
        Rotate to the next API key for the current provider.
        If all keys for the current provider are exhausted, return False, otherwise return True.
        """
        # Move to the next key index
        self.provider["current_key_index"] += 1

        if self.provider["current_key_index"] < len(self.provider["keys"]):
            # There are more keys in this provider
            provider_name = self.provider_order[self.current_provider_index]
            logger.warning(f"Switched to next key for provider '{provider_name}'.")
            return True
        else:
            # No more keys in this provider
            logger.warning(
                f"No more keys in provider '{self.provider_order[self.current_provider_index]}'."
            )
            return False

    def _rotate_provider(self) -> bool:
        """
        Rotate to the next provider, as the previous provider's keys are exhausted.
        If all providers are exhausted, return False, otherwise return True.
        """
        # No more keys in the current provider, reset and move to next provider
        self.provider["current_key_index"] = 0  # Reset key index for this provider
        self.current_provider_index += 1
        if self.current_provider_index < len(self.provider_order):
            # Move to next provider
            provider_name = self.provider_order[self.current_provider_index]
            self.provider = self.providers[provider_name]
            logger.warning(f"Switched to next provider '{provider_name}'.")
            return True
        else:
            # All providers and their keys have been exhausted
            logger.error("All providers and their keys have been exhausted.")
            return False

    def _rotate_model_name(
        self, model_call_params: list[ModelCallParams]
    ) -> ModelCallParams | None:
        """
        Rotate to the next model name.
        If all model names are done, return None, otherwise return the next model name.
        """
        self.model_name_index += 1
        if self.model_name_index == len(model_call_params):
            return None
        self.provider["current_key_index"] = 0  # Reset key index for prev provider
        new_model_params = model_call_params[self.model_name_index]
        provider_name = new_model_params.provider
        self.provider = self.providers[provider_name]
        logger.warning(
            f"Switched to next provider '{provider_name}', model '{new_model_params.model_name}'."
        )
        return new_model_params


async def get_llm_completions_async(
    messages_list: Sequence[Sequence[ChatMessage | dict[str, Any]]],
    model_category: str | None = None,
    model_call_params: list[ModelCallParams] | None = None,
    tools: list[ToolInfo] | None = None,
    tool_choice: Literal["auto", "required"] | None = None,
    max_new_tokens: int = 1024,
    temperature: float = 1.0,
    reasoning_effort: Literal["low", "medium", "high"] | None = None,
    logprobs: bool = False,
    top_logprobs: int | None = None,
    max_concurrency: int = 100,
    timeout: float = 60.0,
    default_provider: str = "anthropic",
    provider_blacklist: list[str] | None = None,
    streaming_callback: AsyncStreamingCallback | None = None,
    completion_callback: AsyncStreamingCallback | None = None,
    use_cache: bool = False,
    llm_api_keys: LLMApiKeys | None = None,
) -> list[LLMOutput]:
    if model_category is None and model_call_params is None:
        raise ValueError("Either model_category or model_call_params must be provided")
    if model_category is not None and model_call_params is not None:
        raise ValueError("Only one of model_category or model_call_params can be provided")

    if logprobs:
        print("Adding `anthropic` to provider blacklist since logprobs are not supported.")
        if provider_blacklist is None:
            provider_blacklist = []
        provider_blacklist.append("anthropic")

    llm_manager = LLMManager(
        default_provider=default_provider,
        provider_blacklist=provider_blacklist,
        max_concurrency=max_concurrency,
        use_cache=use_cache,
        llm_api_keys=llm_api_keys,
    )

    # Parse messages
    parsed_messages_list = [
        [
            message if isinstance(message, ChatMessage) else parse_chat_message(message)
            for message in messages
        ]
        for messages in messages_list
    ]

    return await llm_manager.get_completions(
        parsed_messages_list,
        model_category,
        model_call_params,
        tools=tools,
        tool_choice=tool_choice,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        logprobs=logprobs,
        top_logprobs=top_logprobs,
        max_concurrency=max_concurrency,
        timeout=timeout,
        streaming_callback=streaming_callback,
        completion_callback=completion_callback,
    )
