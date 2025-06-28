import asyncio
import json
from typing import Any, Literal, cast

import backoff
import tiktoken
from backoff.types import Details

# all errors: https://platform.openai.com/docs/guides/error-codes/api-errors#python-library-error-types
from openai import (
    APIConnectionError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from openai._types import NOT_GIVEN
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionChunk,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCall,
    ChatCompletionMessageToolCallParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.chat_completion_message_tool_call_param import (
    Function as OpenAIFunctionParam,
)
from openai.types.shared_params.function_definition import FunctionDefinition

from docent._log_util import get_logger
from docent.data_models.chat import ChatMessage, Content, ToolCall, ToolInfo
from docent_core._env_util import ENV
from docent_core._llm_util.data_models.exceptions import (
    CompletionTooLongException,
    RateLimitException,
)
from docent_core._llm_util.data_models.llm_output import (
    AsyncEmbeddingStreamingCallback,
    AsyncSingleLLMOutputStreamingCallback,
    FinishReasonType,
    LLMCompletion,
    LLMCompletionPartial,
    LLMOutput,
    LLMOutputPartial,
    ToolCallPartial,
    finalize_llm_output_partial,
)

logger = get_logger(__name__)
DEFAULT_TIKTOKEN_ENCODING = "cl100k_base"
MAX_EMBEDDING_TOKENS = 8000


def _print_backoff_message(e: Details):
    logger.warning(
        f"OpenAI backing off for {e['wait']:.2f}s due to {e['exception'].__class__.__name__}"  # type: ignore
    )


def _parse_message_content(
    content: str | list[Content],
) -> str | list[ChatCompletionContentPartTextParam]:
    if isinstance(content, str):
        return content
    else:
        result: list[ChatCompletionContentPartTextParam] = []
        for sub_content in content:
            if sub_content.type == "text":
                result.append(
                    ChatCompletionContentPartTextParam(type="text", text=sub_content.text)
                )
            else:
                raise ValueError(f"Unsupported content type: {sub_content.type}")
        return result


def _parse_chat_messages(messages: list[ChatMessage]) -> list[ChatCompletionMessageParam]:
    result: list[ChatCompletionMessageParam] = []

    for message in messages:
        if message.role == "user":
            result.append(
                ChatCompletionUserMessageParam(
                    role=message.role,
                    content=_parse_message_content(message.content),
                )
            )
        elif message.role == "assistant":
            tool_calls = (
                [
                    ChatCompletionMessageToolCallParam(
                        id=tool_call.id,
                        function=OpenAIFunctionParam(
                            name=tool_call.function,
                            arguments=json.dumps(tool_call.arguments),
                        ),
                        type="function",
                    )
                    for tool_call in message.tool_calls
                ]
                if message.tool_calls
                else None
            )
            # Redundant code annoyingly necessary due to typechecking, but maybe I'm missing something
            if not tool_calls:
                result.append(
                    ChatCompletionAssistantMessageParam(
                        role=message.role, content=_parse_message_content(message.content)
                    )
                )
            else:
                result.append(
                    ChatCompletionAssistantMessageParam(
                        role=message.role,
                        content=_parse_message_content(message.content),
                        tool_calls=tool_calls,
                    )
                )
        elif message.role == "tool":
            result.append(
                ChatCompletionToolMessageParam(
                    role=message.role,
                    content=_parse_message_content(message.content),
                    tool_call_id=str(message.tool_call_id),
                )
            )
        elif message.role == "system":
            result.append(
                ChatCompletionSystemMessageParam(
                    role=message.role,
                    content=_parse_message_content(message.content),
                )
            )

    return result


def _parse_tools(tools: list[ToolInfo]) -> list[ChatCompletionToolParam]:
    return [
        ChatCompletionToolParam(
            type="function",
            function=FunctionDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters.model_dump(exclude_none=True),
            ),
        )
        for tool in tools
    ]


@backoff.on_exception(
    backoff.expo,
    exception=(Exception,),
    giveup=lambda e: isinstance(e, BadRequestError)
    or isinstance(e, AuthenticationError)
    or isinstance(e, PermissionDeniedError)
    or isinstance(e, NotFoundError)
    or isinstance(e, UnprocessableEntityError),
    max_tries=5,
    factor=3.0,
    on_backoff=_print_backoff_message,
)
async def get_openai_chat_completion_streaming_async(
    client: AsyncOpenAI,
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
):
    input_messages = _parse_chat_messages(messages)
    input_tools = _parse_tools(tools) if tools else NOT_GIVEN

    try:
        async with asyncio.timeout(timeout) if timeout else asyncio.nullcontext():  # type: ignore
            stream = await client.chat.completions.create(
                model=model_name,
                messages=input_messages,
                tools=input_tools,
                tool_choice=tool_choice or NOT_GIVEN,
                max_completion_tokens=max_new_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort or NOT_GIVEN,
                logprobs=logprobs,
                top_logprobs=top_logprobs,
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
                return LLMOutput(model=model_name, completions=[], errors=["no_response"])
    except RateLimitError as e:
        # Raise a custom type that prod_llms can catch
        raise RateLimitException(e) from e


def update_llm_output(llm_output_partial: LLMOutputPartial | None, chunk: ChatCompletionChunk):
    # Collect exisitng outputs
    if llm_output_partial is not None:
        cur_texts: list[str | None] = [c.text for c in llm_output_partial.completions]
        cur_finish_reasons: list[FinishReasonType | None] = [
            c.finish_reason for c in llm_output_partial.completions
        ]
        cur_tool_calls_all: list[list[ToolCallPartial | None] | None] = [
            cast(list[ToolCallPartial | None], c.tool_calls) for c in llm_output_partial.completions
        ]
    else:
        cur_texts, cur_finish_reasons, cur_tool_calls_all = [], [], []

    # Define functions for getting and setting values of the current state
    def _get_text(i: int):
        if i >= len(cur_texts):
            return None
        else:
            return cur_texts[i]

    def _set_text(i: int, text: str):
        if i >= len(cur_texts):
            cur_texts.extend([None] * (i - len(cur_texts) + 1))
        cur_texts[i] = text

    def _get_finish_reason(i: int):
        if i >= len(cur_finish_reasons) or cur_finish_reasons[i] is None:
            return None
        else:
            return cur_finish_reasons[i]

    def _set_finish_reason(i: int, finish_reason: FinishReasonType | None):
        if i >= len(cur_finish_reasons):
            cur_finish_reasons.extend([None] * (i - len(cur_finish_reasons) + 1))
        cur_finish_reasons[i] = finish_reason

    def _get_tool_calls(i: int):
        if i >= len(cur_tool_calls_all):
            return None
        else:
            return cur_tool_calls_all[i]

    def _get_tool_call(i: int, j: int):
        if i >= len(cur_tool_calls_all):
            return None
        else:
            cur_tool_calls = cur_tool_calls_all[i]
            if cur_tool_calls is None or j >= len(cur_tool_calls):
                return None
            else:
                return cur_tool_calls[j]

    def _set_tool_call(i: int, j: int, tool_call: ToolCallPartial):
        if i >= len(cur_tool_calls_all):
            cur_tool_calls_all.extend([None] * (i - len(cur_tool_calls_all) + 1))

        # Add ToolCall to current choice index
        cur_tool_calls = cur_tool_calls_all[i] or []
        if j >= len(cur_tool_calls):
            cur_tool_calls.extend([None] * (j - len(cur_tool_calls) + 1))
        cur_tool_calls[j] = tool_call

        # Re-update the global array
        cur_tool_calls_all[i] = cur_tool_calls

    # Update existing completions based on this chunk
    for choice in chunk.choices:
        i, delta = choice.index, choice.delta

        # Resolve text and finish reason
        _set_text(i, (_get_text(i) or "") + (delta.content or ""))
        _set_finish_reason(i, choice.finish_reason or _get_finish_reason(i))

        # Tool call resolution is more complicated
        for tc_delta in delta.tool_calls or []:
            tc_idx = tc_delta.index
            tc_function = tc_delta.function.name if tc_delta.function else None
            tc_arguments = tc_delta.function.arguments if tc_delta.function else None

            old_tool_call = _get_tool_call(i, tc_idx)

            if old_tool_call:
                tool_call_partial = ToolCallPartial(
                    id=old_tool_call.id or tc_delta.id,
                    function=(old_tool_call.function or "") + (tc_function or ""),
                    arguments_raw=(old_tool_call.arguments_raw or "") + (tc_arguments or ""),
                    type="function",
                )
            else:
                tool_call_partial = ToolCallPartial(
                    id=tc_delta.id,
                    function=tc_function or "",
                    arguments_raw=tc_arguments or "",
                    type="function",
                )

            _set_tool_call(i, tc_idx, tool_call_partial)

    completions: list[LLMCompletionPartial] = []
    # TOOD assert all lengths are same
    for i in range(len(cur_texts)):
        completions.append(
            LLMCompletionPartial(
                text=_get_text(i),
                tool_calls=_get_tool_calls(i),
                finish_reason=_get_finish_reason(i),
            )
        )

    return LLMOutputPartial(completions=completions, model=chunk.model)


@backoff.on_exception(
    backoff.expo,
    exception=(Exception,),
    giveup=lambda e: isinstance(e, BadRequestError)
    or isinstance(e, AuthenticationError)
    or isinstance(e, PermissionDeniedError)
    or isinstance(e, NotFoundError)
    or isinstance(e, UnprocessableEntityError),
    max_tries=5,
    factor=3.0,
    on_backoff=_print_backoff_message,
)
async def get_openai_chat_completion_async(
    client: AsyncOpenAI,
    messages: list[ChatMessage],
    model_name: str,
    tools: list[ToolInfo] | None = None,
    tool_choice: Literal["auto", "none", "required"] | None = None,
    max_new_tokens: int = 32,
    temperature: float = 1.0,
    reasoning_effort: Literal["low", "medium", "high"] | None = None,
    logprobs: bool = False,
    top_logprobs: int | None = None,
    timeout: float = 5.0,
) -> LLMOutput:
    input_messages = _parse_chat_messages(messages)
    input_tools = _parse_tools(tools) if tools else NOT_GIVEN

    try:
        async with asyncio.timeout(timeout) if timeout else asyncio.nullcontext():  # type: ignore
            raw_output = await client.chat.completions.create(
                model=model_name,
                messages=input_messages,
                tools=input_tools,
                tool_choice=tool_choice or NOT_GIVEN,
                max_completion_tokens=max_new_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort or NOT_GIVEN,
                logprobs=logprobs,
                top_logprobs=top_logprobs,
            )

            # If the completion is empty and was truncated (likely due to too much reasoning), raise an exception
            output = parse_openai_completion(raw_output, model_name)
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
    except RateLimitError as e:
        # Raise a custom type that prod_llms can catch
        raise RateLimitException(e) from e


def get_openai_client_async() -> AsyncOpenAI:
    # Ensure environment variables are loaded.
    # Technically you don't have to run this, but just makes clear where the envvars are used
    _ = ENV

    return AsyncOpenAI()


def get_azure_openai_client_async() -> AsyncAzureOpenAI:
    # Ensure environment variables are loaded.
    # Technically you don't have to run this, but just makes clear where the envvars are used
    _ = ENV

    return AsyncAzureOpenAI()


def chunk_and_tokenize(
    text: list[str],
    window_size: int = 8191,
    overlap: int = 128,
) -> tuple[list[list[int]], list[int]]:
    """Encode a list of text into a list of token ids."""

    def _chunk_tokens(tokens: list[int], window_size: int, overlap: int) -> list[list[int]]:
        """Compute list chunks with overlap."""
        if overlap >= window_size:
            raise ValueError("overlap must be smaller than window_size")

        stride = window_size - overlap
        chunks: list[list[int]] = []
        for i in range(0, len(tokens), stride):
            chunks.append(tokens[i : i + window_size])
        return chunks

    encoding = tiktoken.get_encoding(DEFAULT_TIKTOKEN_ENCODING)

    all_chunks: list[list[int]] = []
    chunk_to_doc: list[int] = []

    for i, item in enumerate(text):
        tokens = encoding.encode(item)
        if len(tokens) <= window_size:
            chunks = [tokens]
        else:
            chunks = _chunk_tokens(tokens, window_size, overlap)

        all_chunks.extend(chunks)
        chunk_to_doc.extend([i] * len(chunks))

    return all_chunks, chunk_to_doc


@backoff.on_exception(
    backoff.expo,
    exception=(Exception,),
    giveup=lambda e: isinstance(e, BadRequestError)
    or isinstance(e, AuthenticationError)
    or isinstance(e, PermissionDeniedError)
    or isinstance(e, NotFoundError)
    or isinstance(e, UnprocessableEntityError)
    or isinstance(e, APIConnectionError),
    max_tries=5,
    factor=3.0,
    on_backoff=_print_backoff_message,
)
async def _get_openai_embeddings_async_one_batch(
    client: AsyncOpenAI, batch: list[str] | list[list[int]], model_name: str, dimensions: int | None
):
    try:
        response = await client.embeddings.create(
            model=model_name,
            input=batch,
            dimensions=dimensions if dimensions is not None else NOT_GIVEN,
        )
        return [data.embedding for data in response.data]
    except RateLimitError as e:
        raise RateLimitException(e) from e


async def get_chunked_openai_embeddings_async(
    texts: list[str],
    model_name: str = "text-embedding-3-small",
    dimensions: int | None = 512,
    window_size: int = MAX_EMBEDDING_TOKENS,
    overlap: int = 128,
    max_concurrency: int = 100,
    callback: AsyncEmbeddingStreamingCallback | None = None,
) -> tuple[list[list[float]], list[int]]:
    """
    Asynchronously get embeddings for a list of texts using OpenAI's embedding model.
    This function uses tiktoken for tokenization, truncates at 8000 tokens, and prints a warning if truncation occurs.
    Concurrency is limited using a semaphore.
    """

    if model_name != "text-embedding-3-large" and model_name != "text-embedding-3-small":
        assert dimensions is None, f"{model_name} does not have a variable dimension size"

    all_chunks, chunk_to_doc = chunk_and_tokenize(texts, window_size=window_size, overlap=overlap)

    # Create batches of 25 texts. Embedding endpoint has a token limit.
    batches = [all_chunks[i : i + 25] for i in range(0, len(all_chunks), 25)]

    client = get_openai_client_async()
    semaphore = asyncio.Semaphore(max_concurrency)

    batches_done = 0
    batches_total = len(batches)

    async def limited_task(batch: list[list[int]]):
        nonlocal batches_done

        async with semaphore:
            embeddings = await _get_openai_embeddings_async_one_batch(
                client, batch, model_name, dimensions
            )
            batches_done += 1

            if callback:
                progress = int(batches_done / batches_total * 100)
                await callback(progress)

            return embeddings

    # Run tasks concurrently
    tasks = [limited_task(batch) for batch in batches]
    results = await asyncio.gather(*tasks)

    # Flatten the results
    embeddings = [embedding for batch_result in results for embedding in batch_result]

    return embeddings, chunk_to_doc


async def get_openai_embeddings_async(
    client: AsyncOpenAI,
    texts: list[str],
    model_name: str = "text-embedding-3-large",
    dimensions: int | None = 3072,
    max_concurrency: int = 100,
) -> list[list[float] | None]:
    """
    Asynchronously get embeddings for a list of texts using OpenAI's embedding model.
    This function uses tiktoken for tokenization, truncates at 8000 tokens, and prints a warning if truncation occurs.
    Concurrency is limited using a semaphore.
    """

    if model_name != "text-embedding-3-large":
        assert dimensions is None, f"{model_name} does not have a variable dimension size"

    # Tokenize and truncate texts
    tokenizer = tiktoken.get_encoding(DEFAULT_TIKTOKEN_ENCODING)
    truncated_texts: list[str] = []
    for i, text in enumerate(texts):
        tokens = tokenizer.encode(text)
        if len(tokens) > MAX_EMBEDDING_TOKENS:
            print(
                f"Warning: Text at index {i} has been truncated from {len(tokens)} to {MAX_EMBEDDING_TOKENS} tokens."
            )
            tokens = tokens[:MAX_EMBEDDING_TOKENS]
        truncated_texts.append(tokenizer.decode(tokens))

    semaphore = asyncio.Semaphore(max_concurrency)

    async def limited_task(texts_batch: list[str]):
        async with semaphore:
            try:
                return await _get_openai_embeddings_async_one_batch(
                    client, texts_batch, model_name, dimensions
                )
            except Exception as e:
                print(f"Error in fetch_embeddings: {e}. Returning None.")
                return [None] * len(texts_batch)

    # Create batches of 1000 texts (OpenAI's current limit per request)
    batches = [truncated_texts[i : i + 1000] for i in range(0, len(truncated_texts), 1000)]

    # Run tasks concurrently
    tasks = [limited_task(batch) for batch in batches]
    results = await asyncio.gather(*tasks)

    # Flatten the results
    embeddings = [embedding for batch_result in results for embedding in batch_result]

    return embeddings


def get_openai_embeddings_sync(
    client: OpenAI,
    texts: list[str],
    model_name: str = "text-embedding-3-large",
    dimensions: int | None = 1536,
) -> list[list[float] | None]:
    """
    Synchronously get embeddings for a list of texts using OpenAI's embedding model.
    This function uses tiktoken for tokenization and truncates at 8000 tokens.
    """
    # Tokenize and truncate texts
    tokenizer = tiktoken.get_encoding(DEFAULT_TIKTOKEN_ENCODING)
    truncated_texts: list[str] = []
    for i, text in enumerate(texts):
        tokens = tokenizer.encode(text)
        if len(tokens) > MAX_EMBEDDING_TOKENS:
            print(
                f"Warning: Text at index {i} has been truncated from {len(tokens)} to {MAX_EMBEDDING_TOKENS} tokens."
            )
            tokens = tokens[:MAX_EMBEDDING_TOKENS]
        truncated_texts.append(tokenizer.decode(tokens))

    # Process in batches of 1000
    embeddings: list[list[float] | None] = []
    for i in range(0, len(truncated_texts), 1000):
        batch = truncated_texts[i : i + 1000]
        try:
            response = client.embeddings.create(
                model=model_name,
                input=batch,
                dimensions=dimensions if dimensions is not None else NOT_GIVEN,
            )
            batch_embeddings = [data.embedding for data in response.data]
            embeddings.extend(batch_embeddings)
        except Exception as e:
            print(f"Error in get_openai_embeddings_sync: {e}")
            embeddings.extend([None] * len(batch))

    return embeddings


def _parse_openai_tool_call(tc: ChatCompletionMessageToolCall) -> ToolCall:
    # Attempt to parse the tool call arguments as JSON
    arguments: dict[str, Any] = {}
    try:
        arguments = json.loads(tc.function.arguments)
        parse_error = None
    # If the tool call arguments are not valid JSON, return an empty dict with the error
    except Exception as e:
        parse_error = f"Couldn't parse tool call arguments as JSON: {e}. Original input: {tc.function.arguments}"

    return ToolCall(
        id=tc.id,
        function=tc.function.name,
        arguments=arguments,
        parse_error=parse_error,
        type=tc.type,
    )


def parse_openai_completion(response: ChatCompletion | None, model: str) -> LLMOutput:
    if response is None:
        return LLMOutput(
            model=model,
            completions=[],
            errors=["no_response"],
        )
    return LLMOutput(
        model=response.model,
        completions=[
            LLMCompletion(
                text=choice.message.content,
                finish_reason=choice.finish_reason,
                tool_calls=(
                    [_parse_openai_tool_call(tc) for tc in tcs]
                    if (tcs := choice.message.tool_calls)
                    else None
                ),
                top_logprobs=(
                    [pos.top_logprobs for pos in choice.logprobs.content]
                    if choice.logprobs and choice.logprobs.content is not None
                    else None
                ),
            )
            for choice in response.choices
        ],
    )


async def is_openai_api_key_valid(api_key: str) -> bool:
    """
    Test whether an OpenAI API key is valid or invalid.

    Args:
        api_key: The OpenAI API key to test.

    Returns:
        bool: True if the API key is valid, False otherwise.
    """
    client = AsyncOpenAI(api_key=api_key)

    try:
        # Attempt to make a simple API call with minimal tokens/cost
        await client.chat.completions.create(
            model="gpt-3.5-turbo", messages=[{"role": "user", "content": "hi"}], max_tokens=1
        )
        return True
    except AuthenticationError:
        # API key is invalid
        return False
    except Exception:
        # Any other error means the key might be valid but there's another issue
        # For testing key validity specifically, we'll return False only for auth errors
        return True
