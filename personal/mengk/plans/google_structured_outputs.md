# Plan: Add structured output (constrained decoding) support for Google Gemini provider

## Goal
Enable `ResponseFormat` (JSON Schema–based structured outputs) in `docent/docent/_llm_util/providers/google.py` for both non‑streaming and streaming completions, using the Gemini structured output API.

## Request restatement
The user asked to investigate supporting constrained decoding for the Google provider and to base the plan on the Gemini structured output documentation.

## Current state (codebase findings)

### Google provider blocks response_format
`docent/docent/_llm_util/providers/google.py` currently raises `NotImplementedError` when `response_format` is provided in both async and streaming paths:

- `get_google_chat_completion_async` (`docent/docent/_llm_util/providers/google.py:74-130`)

```python
async def get_google_chat_completion_async(..., response_format: ResponseFormat | None = None) -> LLMOutput:
    if response_format is not None:
        raise NotImplementedError(
            "Structured outputs (response_format) are not implemented for Google yet."
        )
    ...
    raw_output = await client.models.generate_content(
        model=model_name,
        contents=input_messages,
        config=types.GenerateContentConfig(
            temperature=temperature,
            thinking_config=thinking_cfg,
            max_output_tokens=max_new_tokens,
            system_instruction=system,
            tools=cast(Any, _parse_tools(tools)) if tools else None,
            tool_config=(
                types.ToolConfig(function_calling_config=_parse_tool_choice(tool_choice))
                if tool_choice is not None
                else None
            ),
        ),
    )
```

- `get_google_chat_completion_streaming_async` (`docent/docent/_llm_util/providers/google.py:141-227`)

```python
async def get_google_chat_completion_streaming_async(..., response_format: ResponseFormat | None = None) -> LLMOutput:
    if response_format is not None:
        raise NotImplementedError(
            "Structured outputs (response_format) are not implemented for Google yet."
        )
    ...
    stream = await client.models.generate_content_stream(
        model=model_name,
        contents=input_messages,
        config=types.GenerateContentConfig(
            temperature=temperature,
            thinking_config=thinking_cfg,
            max_output_tokens=max_new_tokens,
            system_instruction=system,
            tools=cast(Any, _parse_tools(tools)) if tools else None,
            tool_config=(
                types.ToolConfig(function_calling_config=_parse_tool_choice(tool_choice))
                if tool_choice is not None
                else None
            ),
        ),
    )
```

### Unified ResponseFormat model
`docent/docent/data_models/chat/response_format.py` defines the unified structured output spec:

```python
class ResponseFormat(BaseModel):
    type: Literal["json_schema"] = "json_schema"
    name: str
    schema_: dict[str, Any] = Field(alias="schema")
    strict: bool = True
```

### Provider patterns for response_format
- OpenAI and OpenRouter convert `ResponseFormat` to provider-specific config and validate `type == "json_schema"`:
  - `docent/docent/_llm_util/providers/openai.py:_build_response_format`
  - `docent/docent/_llm_util/providers/openrouter.py:_build_response_format`

These are good patterns to mirror for Google.

### SDK capabilities (local)
The local `google-genai` SDK’s `types.GenerateContentConfig` supports the fields needed for structured output:
- `response_mime_type`
- `response_json_schema`
- `response_schema`

(Observed via `.venv/bin/python` introspection of `google.genai.types.GenerateContentConfig`.)

## External requirements (Gemini structured outputs)
From the Gemini structured output docs:
- To get JSON output, set `response_mime_type` to `"application/json"` and provide `response_json_schema` (valid JSON Schema). The model returns a syntactically valid JSON string matching the schema, in the same key order as the schema.
- Streaming returns valid *partial* JSON strings that can be concatenated into the final JSON.
- Only a subset of JSON Schema is supported (types include string/number/integer/boolean/object/array/null; object properties include `properties`, `required`, `additionalProperties`; arrays include `items`, `prefixItems`, `minItems`, `maxItems`; etc.).
- Model support list (per docs):
  - `gemini-3-pro-preview`, `gemini-3-flash-preview`
  - `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`
  - `gemini-2.0-flash`, `gemini-2.0-flash-lite`
  - Gemini 2.0 explicitly requires a `propertyOrdering` list in the JSON input to define preferred structure.
- Structured outputs can be used alongside tools in the request config (preview for Gemini 3 Pro/Flash Preview).

(These constraints should guide implementation and any optional schema adaptation.)

## Options considered

### Option A: Minimal pass-through (recommended if we want smallest change)
- Accept `ResponseFormat` and pass `response_mime_type` + `response_json_schema` directly.
- Do **not** mutate the schema or enforce `propertyOrdering`.
- Pros: minimal risk; respects caller-provided schema.
- Cons: Gemini 2.0 users must supply `propertyOrdering` themselves; otherwise may get sub‑optimal output or errors.

### Option B: Auto‑inject `propertyOrdering` for Gemini 2.0
- Detect Gemini 2.0 model names (e.g., `model_name.startswith("gemini-2.0")`).
- Deep‑copy schema and insert `propertyOrdering` for any object schema that lacks it, using the `properties` key order.
- Pros: reduces user burden; aligns with Gemini 2.0 requirement.
- Cons: mutates schema (even if only in a copy); may surprise users relying on explicit ordering or custom property ordering.

### Option C: Convert to `types.Schema` and set `response_schema`
- Use `_convert_json_schema_to_gemini_schema` to transform JSON Schema into `types.Schema` and pass as `response_schema`.
- Pros: aligns with SDK’s typed schema support.
- Cons: loses JSON Schema features not captured by the converter; structured output docs emphasize `response_json_schema`, so this may be less compatible.

## Recommended approach
Proceed with **Option A** for minimal and predictable behavior. Do **not** auto‑inject `propertyOrdering` (callers must include it in `ResponseFormat.schema_` when targeting Gemini 2.0). Do **not** gate models; let the API return errors for unsupported models. Update the `ResponseFormat` docstring to list Google as supported.

## Implementation steps (detailed)

### 1) Add Google response_format builder
File: `docent/docent/_llm_util/providers/google.py`

Add a helper similar to OpenAI/OpenRouter:

```python
def _build_response_format_config(
    response_format: ResponseFormat | None,
    *,
    model_name: str,
) -> dict[str, Any]:
    if response_format is None:
        return {}

    if response_format.type != "json_schema":
        raise ValueError(
            f"Unsupported response format type: {response_format.type}. "
            "Only 'json_schema' is currently supported."
        )

    schema = response_format.schema_

    return {
        "response_mime_type": "application/json",
        "response_json_schema": schema,
    }
```

Note: this helper does **not** inject `propertyOrdering`. Callers targeting Gemini 2.0 must include it in `ResponseFormat.schema_` themselves.

### 2) Wire response_format into non‑streaming call
File: `docent/docent/_llm_util/providers/google.py`

Replace the `NotImplementedError` block with config wiring:

```python
    response_format_config = _build_response_format_config(
        response_format,
        model_name=model_name,
    )

    raw_output = await client.models.generate_content(
        model=model_name,
        contents=input_messages,
        config=types.GenerateContentConfig(
            temperature=temperature,
            thinking_config=thinking_cfg,
            max_output_tokens=max_new_tokens,
            system_instruction=system,
            tools=cast(Any, _parse_tools(tools)) if tools else None,
            tool_config=(
                types.ToolConfig(function_calling_config=_parse_tool_choice(tool_choice))
                if tool_choice is not None
                else None
            ),
            **response_format_config,
        ),
    )
```

### 3) Wire response_format into streaming call
File: `docent/docent/_llm_util/providers/google.py`

Apply the same config when calling `generate_content_stream`:

```python
    response_format_config = _build_response_format_config(
        response_format,
        model_name=model_name,
    )

    stream = await client.models.generate_content_stream(
        model=model_name,
        contents=input_messages,
        config=types.GenerateContentConfig(
            temperature=temperature,
            thinking_config=thinking_cfg,
            max_output_tokens=max_new_tokens,
            system_instruction=system,
            tools=cast(Any, _parse_tools(tools)) if tools else None,
            tool_config=(
                types.ToolConfig(function_calling_config=_parse_tool_choice(tool_choice))
                if tool_choice is not None
                else None
            ),
            **response_format_config,
        ),
    )
```

### 4) Update docs / comments
Update `docent/docent/data_models/chat/response_format.py` docstring to include Google as a supported provider for structured outputs.

### 5) Optional: Tests
If tests are desired, add lightweight unit tests for the helper(s):
- Verify `_build_response_format_config` returns the correct dict and raises on unsupported type.
- If Option B is chosen, verify `_ensure_property_ordering` injects ordering and preserves nested object order.

Potential test location: `tests/unit/test_llm_util/test_google_response_format.py` (new).

## Risks and constraints
- Gemini structured outputs only support a subset of JSON Schema; unsupported features are ignored or may cause API errors.
- Gemini 2.0 models require explicit `propertyOrdering` in the schema; this plan does **not** inject it automatically.
- `ResponseFormat.strict` has no clear mapping in Gemini; we should pass the schema as‑is and rely on downstream validation.

## Resolved decisions (from user feedback)
- Do **not** auto‑inject `propertyOrdering`; callers supply it if needed.
- Do **not** gate model names; rely on Gemini API errors for unsupported models.
- Update `ResponseFormat` docstring to mention Google structured outputs support.
