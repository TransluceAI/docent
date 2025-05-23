"""
At some point we'll want to do a refactor to support different types of provider/key swapping
due to different scenarios. However, this'll probably be a breaking change, which is why I'm
not doing it now.

- mengk
"""

import traceback
from contextlib import nullcontext
from functools import partial
from typing import Any, Callable, Literal, Protocol, Sequence, TypedDict, cast

import anyio
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

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
    LLMCompletion,
    LLMOutput,
    ModelOption,
    RateLimitException,
    ToolInfo,
    get_single_streaming_callback,
    parse_chat_message,
)
from docent._log_util import get_logger

logger = get_logger(__name__)


class PleaseRotate(Exception):
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
    async_client_getter: Callable[[], AsyncOpenAI | AsyncAnthropic]
    single_output_getter: SingleOutputGetter
    single_streaming_output_getter: SingleStreamingOutputGetter


PROVIDERS: dict[str, ProviderConfig] = {
    "anthropic": {
        "async_client_getter": anthropic.get_anthropic_client_async,
        "single_output_getter": get_anthropic_chat_completion_async,
        "single_streaming_output_getter": get_anthropic_chat_completion_streaming_async,
    },
    "openai": {
        "async_client_getter": openai.get_openai_client_async,
        "single_output_getter": get_openai_chat_completion_async,
        "single_streaming_output_getter": get_openai_chat_completion_streaming_async,
    },
}


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
    fill_cache: str | None = None,
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

    async def _limited_task(i: int, messages: list[ChatMessage]):
        nonlocal responses

        if fill_cache is not None:
            responses[i] = LLMOutput(
                model=model_name,
                completions=[
                    LLMCompletion(
                        text=fill_cache,
                    )
                ],
                errors=None,
            )
            if i % 10 == 0:
                print("hacking cache!")
            return

        async with ctx:
            try:
                if streaming_callback is None:
                    result = await base_func(client=client, messages=messages)
                else:
                    result = await base_func(
                        client=client,
                        streaming_callback=get_single_streaming_callback(i, streaming_callback),
                        messages=messages,
                    )

                # Always call the completion callback if provided
                if completion_callback:
                    await completion_callback(i, result)
            except Exception as e:
                error_message = (
                    f"Call to {model_name} failed even with backoff: {e.__class__.__name__}."
                )
                if not isinstance(e, RateLimitException):
                    # If the error is not a rate limit (which we don't need details for), add the traceback
                    error_message += f" Failure traceback:\n{traceback.format_exc()}"
                logger.error(error_message)

                result = LLMOutput(
                    model=model_name,
                    completions=[],
                    errors=["rate_limit" if isinstance(e, RateLimitException) else "other"],
                )

                # # Call the completion callback for errors too if provided
                # if completion_callback:
                #     await completion_callback(i, error_output)

            # Set the result in either case
            responses[i] = result

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
                # We already checked that each index corresponds to an LLMOutput object
                [cast(LLMOutput, responses[i]) for i in indices],
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

    # Get all results concurrently
    try:
        async with anyio.create_task_group() as tg:
            for i, messages in enumerate(messages_list):
                tg.start_soon(_limited_task, i, messages)

    # Cache what we have so far if something got cancelled
    except anyio.get_cancelled_exc_class():
        num_cached = _cache_responses()
        logger.info(
            f"Cancelled {len(messages_list) - num_cached} unfinished LLM API calls; cached {num_cached} completed responses"
        )
        raise

    # Cache results if available
    if cache is not None:
        _cache_responses()

    # At this point, all indices should have a result
    assert all(
        isinstance(r, LLMOutput) for r in responses
    ), "Some indices were never set to an LLMOutput, which should never happen"

    return cast(list[LLMOutput], responses)


class LLMManager:
    def __init__(
        self,
        model_options: list[ModelOption],
        max_concurrency: int = 100,
        use_cache: bool = False,
    ):
        self.cache = LLMCache() if use_cache else None
        self.semaphore = anyio.Semaphore(max_concurrency)

        self.model_options = model_options
        self.current_model_option_index = 0

    async def get_completions(
        self,
        messages_list: list[list[ChatMessage]],
        tools: list[ToolInfo] | None = None,
        tool_choice: Literal["auto", "required"] | None = None,
        max_new_tokens: int = 32,
        temperature: float = 1.0,
        logprobs: bool = False,
        top_logprobs: int | None = None,
        max_concurrency: int | None = None,
        timeout: float = 5.0,
        streaming_callback: AsyncStreamingCallback | None = None,
        completion_callback: AsyncStreamingCallback | None = None,
        fill_cache: str | None = None,
    ) -> list[LLMOutput]:
        """
        If max_concurrency is None, use LLManager.semaphore to manage concurrency
        """
        results: list[LLMOutput | None] = [None] * len(messages_list)

        while True:
            try:
                # Parse the current model option
                cur_option = self.model_options[self.current_model_option_index]
                provider, model_name, reasoning_effort = (
                    cur_option.provider,
                    cur_option.model_name,
                    cur_option.reasoning_effort,
                )
                client = PROVIDERS[provider]["async_client_getter"]()
                single_output_getter = PROVIDERS[provider]["single_output_getter"]
                single_streaming_output_getter = PROVIDERS[provider][
                    "single_streaming_output_getter"
                ]

                # Collect inputs that don't have a result yet
                null_inputs = [
                    (i, messages_list[i]) for i, result in enumerate(results) if result is None
                ]

                # Check cache if available
                if self.cache is not None:
                    uncached_indices: list[int] = []
                    uncached_messages: list[list[ChatMessage]] = []
                    hits = 0

                    for i, messages in null_inputs:
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

                            # Call completion and streaming callbacks for cache hits
                            # TODO(mengk): we should make the callbacks batchable
                            if completion_callback:
                                await completion_callback(i, cached_result)
                            if streaming_callback:
                                await streaming_callback(i, cached_result)
                        else:
                            uncached_indices.append(i)
                            uncached_messages.append(messages)

                    misses = len(messages_list) - hits
                    logger.info(f"{model_name}: {hits} cache hits, {misses} misses")
                # Otherwise, everything is uncached
                else:
                    uncached_indices = [i for i, _ in null_inputs]
                    uncached_messages = [messages for _, messages in null_inputs]

                # Get completions for uncached messages
                if uncached_messages:
                    outputs = await _parallelize_calls(
                        (
                            single_output_getter
                            if streaming_callback is None
                            else single_streaming_output_getter
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
                        fill_cache=fill_cache,
                    )
                    for i, (messages, output) in enumerate(zip(uncached_messages, outputs)):
                        results[uncached_indices[i]] = output if not output.did_error else None

                # If there are still some None results, rotate model options
                num_error = sum(1 for result in results if result is None)
                if num_error > 0:
                    logger.warning(f"{model_name}: {num_error} failed calls")
                    if not self._rotate_model_option():
                        break  # Stop looping
                # Otherwise, we're done and can break
                else:
                    break
            except PleaseRotate:
                if not self._rotate_model_option():
                    break  # Stop looping

        # If any results are None, set them to an error result
        final_results: list[LLMOutput] = []
        for result in results:
            if result is None:
                final_results.append(
                    LLMOutput(
                        model="all model options exhausted",
                        completions=[],
                        errors=["all_providers_exhausted"],
                    )
                )
            else:
                final_results.append(result)

        return final_results

    def _rotate_model_option(self) -> ModelOption | None:
        self.current_model_option_index += 1
        if self.current_model_option_index >= len(self.model_options):
            logger.error("All model options are exhausted")
            return None

        new_model_option = self.model_options[self.current_model_option_index]
        logger.warning(f"Switched to next model {new_model_option.model_name}")
        return new_model_option


async def get_llm_completions_async(
    messages_list: Sequence[Sequence[ChatMessage | dict[str, Any]]],
    model_options: list[ModelOption],
    tools: list[ToolInfo] | None = None,
    tool_choice: Literal["auto", "required"] | None = None,
    max_new_tokens: int = 1024,
    temperature: float = 1.0,
    logprobs: bool = False,
    top_logprobs: int | None = None,
    max_concurrency: int = 100,
    timeout: float = 60.0,
    streaming_callback: AsyncStreamingCallback | None = None,
    completion_callback: AsyncStreamingCallback | None = None,
    use_cache: bool = False,
    fill_cache: str | None = None,
) -> list[LLMOutput]:
    # We don't support logprobs for Anthropic yet
    if logprobs:
        for model_option in model_options:
            if model_option.provider == "anthropic":
                raise ValueError(
                    f"Logprobs are not supported for Anthropic, so we can't use model {model_option.model_name}"
                )

    # Create the LLM manager
    llm_manager = LLMManager(
        model_options=model_options,
        max_concurrency=max_concurrency,
        use_cache=use_cache,
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
        tools=tools,
        tool_choice=tool_choice,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        logprobs=logprobs,
        top_logprobs=top_logprobs,
        max_concurrency=max_concurrency,
        timeout=timeout,
        streaming_callback=streaming_callback,
        completion_callback=completion_callback,
        fill_cache=fill_cache,
    )
