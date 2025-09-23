from typing import Any, Literal, cast

import backoff
import requests
from backoff.types import Details
from google import genai
from google.genai import errors, types
from google.genai.client import AsyncClient as AsyncGoogle

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
)
from docent_core._llm_util.providers.common import (
    async_timeout_ctx,
    coerce_tool_args,
    reasoning_budget,
)


def get_google_client_async(api_key: str | None = None) -> AsyncGoogle:
    # Ensure environment variables are loaded.
    # Technically you don't have to run this, but just makes clear where the envvars are used
    _ = ENV

    if api_key:
        return genai.Client(api_key=api_key).aio
    return genai.Client().aio


logger = get_logger(__name__)


def _convert_google_error(e: errors.APIError):
    if e.code in [429, 502, 503, 504]:
        return RateLimitException(e)
    elif e.code == 400 and "maximum number of tokens" in str(e).lower():
        return ContextWindowException()
    return None


def _print_backoff_message(e: Details):
    logger.warning(
        f"Google backing off for {e['wait']:.2f}s due to {e['exception'].__class__.__name__}"  # type: ignore
    )


def _is_retryable_error(exception: BaseException) -> bool:
    """Checks if the exception is a retryable error based on the criteria."""
    if isinstance(exception, errors.APIError):
        return exception.code in [429, 500, 502, 503, 504]
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

    system, input_messages = _parse_chat_messages(messages, tools_provided=bool(tools))

    async with async_timeout_ctx(timeout):
        thinking_cfg = None
        if reasoning_effort:
            thinking_cfg = types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=reasoning_budget(max_new_tokens, reasoning_effort),
            )

        raw_output = await client.models.generate_content(
            model=model_name,
            contents=input_messages,  # type: ignore
            config=types.GenerateContentConfig(
                temperature=temperature,
                thinking_config=thinking_cfg,
                max_output_tokens=max_new_tokens,
                system_instruction=system,
                tools=_parse_tools(tools) if tools else None,
                tool_config=(
                    types.ToolConfig(function_calling_config=_parse_tool_choice(tool_choice))
                    if tool_choice is not None
                    else None
                ),
            ),
        )

        output = _parse_google_completion(raw_output, model_name)
        if output.first and output.first.finish_reason == "length" and output.first.no_text:
            raise CompletionTooLongException(
                f"Completion empty due to truncation. Consider increasing max_new_tokens (currently {max_new_tokens})."
            )

        return output


@backoff.on_exception(
    backoff.expo,
    exception=(Exception),
    giveup=lambda e: not _is_retryable_error(e),
    max_tries=3,
    factor=2.0,
    on_backoff=_print_backoff_message,
)
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
    if logprobs or top_logprobs is not None:
        raise NotImplementedError(
            "We have not implemented logprobs or top_logprobs for Google yet."
        )

    system, input_messages = _parse_chat_messages(messages, tools_provided=bool(tools))

    try:
        async with async_timeout_ctx(timeout):
            thinking_cfg = None
            if reasoning_effort:
                thinking_cfg = types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=reasoning_budget(max_new_tokens, reasoning_effort),
                )

            stream = await client.models.generate_content_stream(
                model=model_name,
                contents=input_messages,  # type: ignore
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    thinking_config=thinking_cfg,
                    max_output_tokens=max_new_tokens,
                    system_instruction=system,
                    tools=_parse_tools(tools) if tools else None,
                    tool_config=(
                        types.ToolConfig(function_calling_config=_parse_tool_choice(tool_choice))
                        if tool_choice is not None
                        else None
                    ),
                ),
            )

            accumulated_text = ""
            accumulated_tool_calls: list[ToolCall] = []
            finish_reason: str | None = None
            total_tokens: int | None = None

            async for chunk in stream:
                if chunk.usage_metadata and chunk.usage_metadata.total_token_count is not None:
                    total_tokens = chunk.usage_metadata.total_token_count

                candidate = chunk.candidates[0] if chunk.candidates else None
                if candidate and candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text is not None and not part.thought:
                            accumulated_text += part.text or ""
                        elif part.function_call is not None:
                            fc = part.function_call
                            args = coerce_tool_args(getattr(fc, "args", {}))
                            accumulated_tool_calls.append(
                                ToolCall(
                                    id=getattr(fc, "id", None)
                                    or f"{getattr(fc, 'name', 'tool')}_call",
                                    function=getattr(fc, "name", "unknown"),
                                    arguments=args,
                                    type="function",
                                )
                            )

                if candidate and candidate.finish_reason is not None:
                    if candidate.finish_reason == types.FinishReason.STOP:
                        finish_reason = "stop"
                    elif candidate.finish_reason == types.FinishReason.MAX_TOKENS:
                        finish_reason = "length"
                    else:
                        finish_reason = "error"

                if streaming_callback is not None:
                    await streaming_callback(
                        LLMOutput(
                            model=model_name,
                            completions=[LLMCompletion(text=accumulated_text)],
                        )
                    )

            return LLMOutput(
                model=model_name,
                completions=[
                    LLMCompletion(
                        text=accumulated_text,
                        tool_calls=(accumulated_tool_calls or None),
                        finish_reason=finish_reason,
                    )
                ],
                total_tokens=total_tokens,
            )
    except errors.APIError as e:
        if e2 := _convert_google_error(e):
            raise e2 from e
        else:
            raise


def _parse_chat_messages(
    messages: list[ChatMessage],
    *,
    tools_provided: bool = False,
) -> tuple[str | None, list[types.Content]]:
    result: list[types.Content] = []
    system_prompt: str | None = None

    for message in messages:
        if message.role == "user":
            parts = _parse_message_content(message.content)
            if parts:  # Avoid sending empty text parts
                result.append(
                    types.Content(
                        role="user",
                        parts=parts,
                    )
                )
        elif message.role == "assistant":
            parts: list[types.Part] = _parse_message_content(message.content)
            # If assistant previously made tool calls, include them so the model has full context
            for tool_call in getattr(message, "tool_calls", []) or []:
                try:
                    parts.append(
                        types.Part.from_function_call(
                            name=tool_call.function,
                            args=tool_call.arguments,  # type: ignore[arg-type]
                            id=tool_call.id,  # type: ignore[call-arg]
                        )
                    )
                except Exception:
                    # Fallback without id if the SDK signature differs
                    parts.append(
                        types.Part.from_function_call(
                            name=tool_call.function,
                            args=tool_call.arguments,  # type: ignore[arg-type]
                        )
                    )
            if parts:  # If only tool calls with no text, we still include function_call parts
                result.append(types.Content(role="model", parts=parts))
            elif getattr(message, "tool_calls", []):
                # Include just the tool calls if present
                result.append(types.Content(role="model", parts=parts))
        elif message.role == "tool":
            # Represent tool result as a function_response part (Gemini tool execution result)
            if not tools_provided:
                # If no tools configured, pass through as plain text
                parts = _parse_message_content(message.content)
                if parts:
                    result.append(types.Content(role="user", parts=parts))
            else:
                tool_name = getattr(message, "function", None) or "unknown_tool"
                tool_id = getattr(message, "tool_call_id", None)
                # Try to parse tool content as JSON if it looks like JSON; otherwise wrap as text
                tool_text = message.text or ""
                response_obj: dict[str, Any]
                try:
                    import json as _json

                    parsed = _json.loads(tool_text)
                    if isinstance(parsed, dict):  # type: ignore[redundant-cast]
                        response_obj = cast(dict[str, Any], parsed)
                    else:
                        response_obj = {"result": parsed}
                except Exception:
                    response_obj = {"result": tool_text}

                part = _make_function_response_part(name=tool_name, response=response_obj, id=tool_id)  # type: ignore[arg-type]
                result.append(types.Content(role="user", parts=[part]))
        elif message.role == "system":
            system_prompt = message.text
        else:
            raise ValueError(f"Unknown message role: {message.role}")

    return system_prompt, result


def _parse_message_content(content: str | list[Content]) -> list[types.Part]:
    if isinstance(content, str):
        text = content.strip()
        return [types.Part.from_text(text=text)] if text else []
    else:
        result: list[types.Part] = []
        for sub_content in content:
            if sub_content.type == "text":
                txt = (sub_content.text or "").strip()
                if txt:
                    result.append(types.Part.from_text(text=txt))
            else:
                raise ValueError(f"Unsupported content type: {sub_content.type}")
        return result


def _parse_google_completion(message: types.GenerateContentResponse, model: str) -> LLMOutput:
    if not message.candidates:
        return LLMOutput(
            model=model,
            completions=[],
            errors=[NoResponseException()],
        )

    candidate = message.candidates[0]

    if candidate.finish_reason == types.FinishReason.STOP:
        finish_reason = "stop"
    elif candidate.finish_reason == types.FinishReason.MAX_TOKENS:
        finish_reason = "length"
    else:
        finish_reason = "error"

    text = ""
    tool_calls: list[ToolCall] = []
    content_parts = candidate.content.parts if candidate.content else []
    content_parts = content_parts or []
    for part in content_parts:
        if part.text is not None and not part.thought:
            text += part.text
        elif part.thought:
            logger.warning("Google returned thinking block; we should support this soon.")
        elif getattr(part, "function_call", None) is not None:
            fc = part.function_call
            # Attempt to parse arguments as a dictionary
            args = coerce_tool_args(getattr(fc, "args", {}))
            tool_calls.append(
                ToolCall(
                    id=getattr(fc, "id", None) or f"{getattr(fc, 'name', 'tool')}_call",
                    function=getattr(fc, "name", "unknown"),
                    arguments=args,
                    type="function",
                )
            )
        else:
            raise ValueError(f"Unknown content part: {part}")

    # Extract total tokens from usage metadata if available
    total_tokens = None
    if message.usage_metadata:
        total_tokens = message.usage_metadata.total_token_count

    return LLMOutput(
        model=model,
        completions=[
            LLMCompletion(
                text=text,
                finish_reason=("tool_calls" if tool_calls else finish_reason),
                tool_calls=(tool_calls or None),
            )
        ],
        total_tokens=total_tokens,
    )


def _parse_tools(tools: list[ToolInfo]) -> list[types.Tool]:
    # Gemini expects a list of Tool objects, each with one or more FunctionDeclarations
    fds: list[types.FunctionDeclaration] = []
    for tool in tools:
        fds.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=_convert_toolparams_to_schema(tool.parameters),
            )
        )
    # Group all function declarations into a single Tool for simplicity
    return [types.Tool(function_declarations=fds)]


def _parse_tool_choice(tool_choice: Literal["auto", "required"] | None):
    if tool_choice is None:
        return None
    # Map our values to SDK enum; if unavailable, return None so default behavior applies
    try:
        if tool_choice == "auto":
            return types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.AUTO)
        elif tool_choice == "required":
            return types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.ANY)
    except Exception:
        return None


def _convert_toolparams_to_schema(params: Any) -> types.Schema:
    properties: dict[str, types.Schema] = {}
    params_props: dict[str, Any] = getattr(params, "properties", {}) or {}
    for name, param in params_props.items():
        prop_schema = _convert_json_schema_to_gemini_schema(
            (getattr(param, "input_schema", {}) or {})
        )
        desc: Any = getattr(param, "description", None)
        if desc and prop_schema.description is None:
            prop_schema.description = desc
        properties[str(name)] = prop_schema

    required_names: list[str] | None = None
    required_raw: Any = getattr(params, "required", None)
    if isinstance(required_raw, list):
        required_list: list[Any] = cast(list[Any], required_raw)
        required_names = [str(item) for item in required_list]

    return types.Schema(
        type=types.Type.OBJECT,
        properties=properties or None,
        required=required_names,
    )


def _convert_json_schema_to_gemini_schema(js: dict[str, Any]) -> types.Schema:
    type_get: Any = js.get("type")
    type_name: str
    if isinstance(type_get, str):
        type_name = type_get.lower()
    elif isinstance(type_get, list):
        # Convert list to list[str] then take first
        type_list: list[str] = [str(v) for v in cast(list[Any], type_get)]
        type_name = type_list[0].lower() if type_list else ""
    elif type_get is None:
        type_name = ""
    else:
        type_name = str(type_get).lower()
    if type_name == "string":
        t: types.Type | None = types.Type.STRING
    elif type_name == "number":
        t = types.Type.NUMBER
    elif type_name == "integer":
        t = types.Type.INTEGER
    elif type_name == "boolean":
        t = types.Type.BOOLEAN
    elif type_name == "array":
        t = types.Type.ARRAY
    elif type_name == "object":
        t = types.Type.OBJECT
    elif type_name == "null":
        t = types.Type.NULL
    else:
        t = None
    description = js.get("description")
    enum_vals_any: Any = js.get("enum")
    enum_vals: list[str] | None = None
    if isinstance(enum_vals_any, list):
        enum_vals = [str(v) for v in cast(list[Any], enum_vals_any)] or None

    props_in_raw_any: Any = js.get("properties") or {}
    props_in_raw: dict[str, Any] = (
        cast(dict[str, Any], props_in_raw_any) if isinstance(props_in_raw_any, dict) else {}
    )
    props_out: dict[str, types.Schema] | None = None
    if props_in_raw:
        tmp_props: dict[str, types.Schema] = {}
        for key, val in props_in_raw.items():
            if isinstance(val, dict):
                tmp_props[str(key)] = _convert_json_schema_to_gemini_schema(
                    cast(dict[str, Any], val)
                )
        props_out = tmp_props if tmp_props else None

    required_out: list[str] | None = None
    required_raw_js: Any = js.get("required")
    if isinstance(required_raw_js, list):
        tmp_required_any: list[Any] = cast(list[Any], required_raw_js)
        tmp_required: list[str] = [str(item) for item in tmp_required_any]
        required_out = tmp_required or None

    items_in_any: Any = js.get("items")
    items_out: types.Schema | None = None
    if isinstance(items_in_any, dict):
        items_out = _convert_json_schema_to_gemini_schema(cast(dict[str, Any], items_in_any))

    return types.Schema(
        type=t,
        description=description,
        enum=enum_vals,
        properties=props_out,
        required=required_out,
        items=items_out,
    )


def _make_function_response_part(
    *, name: str, response: dict[str, object], id: str | None
) -> types.Part:
    try:
        return types.Part.from_function_response(name=name, response=response, id=id)  # type: ignore[call-arg]
    except Exception:
        return types.Part.from_function_response(name=name, response=response)
