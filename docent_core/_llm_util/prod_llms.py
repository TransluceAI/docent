"""
At some point we'll want to do a refactor to support different types of provider/key swapping
due to different scenarios. However, this'll probably be a breaking change, which is why I'm
not doing it now.

- mengk
"""

import traceback
from contextlib import nullcontext
from functools import partial
from typing import (
    Any,
    AsyncContextManager,
    Literal,
    Protocol,
    Sequence,
    cast,
    runtime_checkable,
)

import anyio
from anyio.abc import TaskGroup
from tqdm.auto import tqdm

from docent._log_util import get_logger
from docent.data_models.chat import ChatMessage, ToolInfo, parse_chat_message
from docent_core._llm_util.data_models.exceptions import (
    DocentUsageLimitException,
    LLMException,
    RateLimitException,
    ValidationFailedException,
)
from docent_core._llm_util.data_models.llm_output import (
    AsyncLLMOutputStreamingCallback,
    AsyncSingleLLMOutputStreamingCallback,
    LLMOutput,
)
from docent_core._llm_util.llm_cache import LLMCache
from docent_core._llm_util.providers.preferences import ModelOption
from docent_core._llm_util.providers.provider_registry import (
    PROVIDERS,
    SingleOutputGetter,
    SingleStreamingOutputGetter,
)

MAX_VALIDATION_ATTEMPTS = 3

logger = get_logger(__name__)


@runtime_checkable
class MessageResolver(Protocol):
    def __call__(self) -> list[ChatMessage | dict[str, Any]]: ...


MessagesInput = Sequence[ChatMessage | dict[str, Any]] | MessageResolver


def _resolve_messages_input(messages_input: MessagesInput) -> list[ChatMessage]:
    raw_messages = (
        messages_input() if isinstance(messages_input, MessageResolver) else messages_input
    )
    return [parse_chat_message(msg) for msg in raw_messages]


def _get_single_streaming_callback(
    batch_index: int,
    streaming_callback: AsyncLLMOutputStreamingCallback,
) -> AsyncSingleLLMOutputStreamingCallback:
    async def single_streaming_callback(llm_output: LLMOutput):
        await streaming_callback(batch_index, llm_output)

    return single_streaming_callback


async def _parallelize_calls(
    single_output_getter: SingleOutputGetter | SingleStreamingOutputGetter,
    streaming_callback: AsyncLLMOutputStreamingCallback | None,
    validation_callback: AsyncLLMOutputStreamingCallback | None,
    completion_callback: AsyncLLMOutputStreamingCallback | None,
    # Arguments for the individual completion getter
    client: Any,
    inputs: list[MessagesInput],
    model_name: str,
    tools: list[ToolInfo] | None,
    tool_choice: Literal["auto", "required"] | None,
    max_new_tokens: int,
    temperature: float,
    reasoning_effort: Literal["low", "medium", "high"] | None,
    logprobs: bool,
    top_logprobs: int | None,
    timeout: float,
    semaphore: AsyncContextManager[anyio.Semaphore] | None,
    # use_tqdm: bool,
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

    responses: list[LLMOutput | None] = [None for _ in inputs]
    pbar = (
        tqdm(
            total=len(inputs),
            desc=f"Calling {model_name} (reasoning_effort={reasoning_effort}) API",
        )
        if len(inputs) > 1
        else None
    )

    # Save resolved messages to avoid multiple resolutions
    resolved_messages: list[list[ChatMessage] | None] = [None] * len(inputs)

    cancelled_due_to_usage_limit: bool = False

    async def _limited_task(i: int, cur_input: MessagesInput, tg: TaskGroup):
        nonlocal responses, pbar, resolved_messages, cancelled_due_to_usage_limit

        async with semaphore or nullcontext():
            messages = _resolve_messages_input(cur_input)
            resolved_messages[i] = messages

            retry_count = 0
            result = None

            # Check if there's a cached result
            cached_result = (
                cache.get(
                    messages,
                    model_name,
                    tools=tools,
                    tool_choice=tool_choice,
                    reasoning_effort=reasoning_effort,
                    temperature=temperature,
                    logprobs=logprobs,
                    top_logprobs=top_logprobs,
                )
                if cache is not None
                else None
            )
            if cached_result is not None:
                result = cached_result
                if streaming_callback is not None:
                    await streaming_callback(i, result)
            else:
                while retry_count < MAX_VALIDATION_ATTEMPTS:
                    try:
                        if streaming_callback is None:
                            result = await base_func(client=client, messages=messages)
                        else:
                            result = await base_func(
                                client=client,
                                streaming_callback=_get_single_streaming_callback(
                                    i, streaming_callback
                                ),
                                messages=messages,
                            )

                        # Validate if validation callback provided and result is successful
                        if validation_callback and not result.did_error:
                            await validation_callback(i, result)

                        break
                    except ValidationFailedException as e:
                        retry_count += 1
                        logger.warning(
                            f"Validation failed for {model_name} after {retry_count} attempts: {e}"
                        )
                        if retry_count >= MAX_VALIDATION_ATTEMPTS:
                            logger.error(
                                f"Validation failed for {model_name} after {MAX_VALIDATION_ATTEMPTS} attempts: {e}"
                            )
                            result = LLMOutput(
                                model=model_name,
                                completions=[],
                                errors=[e],
                            )
                            break
                    except DocentUsageLimitException as e:
                        result = LLMOutput(
                            model=model_name,
                            completions=[],
                            errors=[],  # Usage limit exceptions will be added to all results later if cancelled_due_to_usage_limit
                        )
                        cancelled_due_to_usage_limit = True
                        tg.cancel_scope.cancel()
                        break
                    except Exception as e:
                        if not isinstance(e, LLMException):
                            logger.warning(
                                f"LLM call raised an exception that is not an LLMException: {e}"
                            )
                            llm_exception = LLMException(e)
                            llm_exception.__cause__ = e
                        else:
                            llm_exception = e

                        error_message = f"Call to {model_name} failed even with backoff: {e.__class__.__name__}."

                        if not isinstance(e, RateLimitException):
                            error_message += f" Failure traceback:\n{traceback.format_exc()}"
                        logger.error(error_message)

                        result = LLMOutput(
                            model=model_name,
                            completions=[],
                            errors=[llm_exception],
                        )
                        break

            # Always call completion callback with final result (success or error)
            if completion_callback and result is not None:
                try:
                    await completion_callback(i, result)
                # LLMService uses this callback to record cost, and may throw an error if we just exceeded limit
                except DocentUsageLimitException as e:
                    result.errors.append(e)
                    cancelled_due_to_usage_limit = True
                    tg.cancel_scope.cancel()

            responses[i] = result
            if pbar is not None:
                pbar.update(1)
            if pbar is None or pbar.n == pbar.total:
                tg.cancel_scope.cancel()

    def _cache_responses():
        nonlocal responses, cache

        if cache is not None:
            indices = [
                i
                for i, response in enumerate(responses)
                if resolved_messages[i] is not None
                and response is not None
                and not response.did_error
            ]
            cache.set_batch(
                # We already checked that each index has a resolved messages list
                [cast(list[ChatMessage], resolved_messages[i]) for i in indices],
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
            # Start all the individual tasks
            for i, cur_input in enumerate(inputs):
                tg.start_soon(_limited_task, i, cur_input, tg)

    # Cache what we have so far if something got cancelled
    except anyio.get_cancelled_exc_class():
        num_cached = _cache_responses()
        logger.info(
            f"Cancelled {len(inputs) - num_cached} unfinished LLM API calls; cached {num_cached} completed responses"
        )
        raise

    if cancelled_due_to_usage_limit:
        for i in range(len(responses)):
            if responses[i] is None:
                responses[i] = LLMOutput(
                    model=model_name,
                    completions=[],
                    errors=[DocentUsageLimitException()],
                )
            else:
                responses[i].errors.append(DocentUsageLimitException())

    # Cache results if available
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
        api_key_overrides: dict[str, str] | None = None,
        use_cache: bool = False,
    ):
        # TODO(mengk): make this more robust, possibly move to a NoSQL database or something
        try:
            self.cache = LLMCache() if use_cache else None
        except ValueError as e:
            logger.warning(f"Disabling LLM cache due to init error: {e}")
            self.cache = None

        self.model_options = model_options
        self.current_model_option_index = 0
        self.api_key_overrides = api_key_overrides or {}

    async def get_completions(
        self,
        inputs: list[MessagesInput],
        tools: list[ToolInfo] | None = None,
        tool_choice: Literal["auto", "required"] | None = None,
        max_new_tokens: int = 32,
        temperature: float = 1.0,
        logprobs: bool = False,
        top_logprobs: int | None = None,
        max_concurrency: int | None = None,
        timeout: float = 5.0,
        streaming_callback: AsyncLLMOutputStreamingCallback | None = None,
        validation_callback: AsyncLLMOutputStreamingCallback | None = None,
        completion_callback: AsyncLLMOutputStreamingCallback | None = None,
    ) -> list[LLMOutput]:
        while True:
            # Parse the current model option
            cur_option = self.model_options[self.current_model_option_index]
            provider, model_name, reasoning_effort = (
                cur_option.provider,
                cur_option.model_name,
                cur_option.reasoning_effort,
            )

            override_key = self.api_key_overrides.get(provider)

            client = PROVIDERS[provider]["async_client_getter"](override_key)
            single_output_getter = PROVIDERS[provider]["single_output_getter"]
            single_streaming_output_getter = PROVIDERS[provider]["single_streaming_output_getter"]

            # Get completions for uncached messages
            outputs: list[LLMOutput] = await _parallelize_calls(
                (
                    single_output_getter
                    if streaming_callback is None
                    else single_streaming_output_getter
                ),
                streaming_callback,
                validation_callback,
                completion_callback,
                client,
                inputs,
                model_name,
                tools=tools,
                tool_choice=tool_choice,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                logprobs=logprobs,
                top_logprobs=top_logprobs,
                timeout=timeout,
                semaphore=(
                    anyio.Semaphore(max_concurrency) if max_concurrency is not None else None
                ),
                cache=self.cache,
            )
            assert len(outputs) == len(inputs), "Number of outputs must match number of messages"

            # Only count errors that should trigger model rotation (API errors, not validation/usage errors)
            num_rotation_errors = sum(
                1
                for output in outputs
                if output.did_error
                and any(
                    not isinstance(e, (ValidationFailedException, DocentUsageLimitException))
                    for e in output.errors
                )
            )
            if num_rotation_errors > 0:
                logger.warning(f"{model_name}: {num_rotation_errors} API errors")
                if not self._rotate_model_option():
                    break
            else:
                break

        return outputs

    def _rotate_model_option(self) -> ModelOption | None:
        self.current_model_option_index += 1
        if self.current_model_option_index >= len(self.model_options):
            logger.error("All model options are exhausted")
            return None

        new_model_option = self.model_options[self.current_model_option_index]
        logger.warning(f"Switched to next model {new_model_option.model_name}")
        return new_model_option


async def get_llm_completions_async(
    inputs: list[MessagesInput],
    model_options: list[ModelOption],
    tools: list[ToolInfo] | None = None,
    tool_choice: Literal["auto", "required"] | None = None,
    max_new_tokens: int = 1024,
    temperature: float = 1.0,
    logprobs: bool = False,
    top_logprobs: int | None = None,
    max_concurrency: int = 100,
    timeout: float = 120.0,
    streaming_callback: AsyncLLMOutputStreamingCallback | None = None,
    validation_callback: AsyncLLMOutputStreamingCallback | None = None,
    completion_callback: AsyncLLMOutputStreamingCallback | None = None,
    use_cache: bool = False,
    api_key_overrides: dict[str, str] | None = None,
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
        api_key_overrides=api_key_overrides,
        use_cache=use_cache,
    )

    return await llm_manager.get_completions(
        inputs,
        tools=tools,
        tool_choice=tool_choice,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        logprobs=logprobs,
        top_logprobs=top_logprobs,
        max_concurrency=max_concurrency,
        timeout=timeout,
        streaming_callback=streaming_callback,
        validation_callback=validation_callback,
        completion_callback=completion_callback,
    )
