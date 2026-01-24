# Plan: Add Anthropic Structured Outputs (Constrained Decoding)

## 1. Goal
Enable `ResponseFormat` (JSON Schema–based constrained decoding) for Anthropic in `docent/docent/_llm_util/providers/anthropic.py`, matching the existing OpenAI/OpenRouter support. The goal is to remove the current `NotImplementedError` and pass the proper `output_format` + beta header so Claude returns JSON that conforms to the schema.

## 2. Key Findings (Repo + SDK + Docs)

### 2.1 Anthropic provider currently blocks response_format
File: `docent/docent/_llm_util/providers/anthropic.py`

Both streaming and non‑streaming code paths raise `NotImplementedError` when `response_format` is provided:

```python
# get_anthropic_chat_completion_streaming_async (around lines 223–226)
if response_format is not None:
    raise NotImplementedError(
        "Structured outputs (response_format) are not implemented for Anthropic yet."
    )
```

```python
# get_anthropic_chat_completion_async (around lines 423–426)
if response_format is not None:
    raise NotImplementedError(
        "Structured outputs (response_format) are not implemented for Anthropic yet."
    )
```

Both functions build `create_kwargs` and call:

```python
await client.messages.create(**create_kwargs)
```

So the natural extension is to add `output_format` + beta header into `create_kwargs`.

### 2.2 Unified ResponseFormat model
File: `docent/docent/data_models/chat/response_format.py`

- Unified type used for OpenAI/OpenRouter.
- Fields: `type`, `name`, `schema_`, `strict` (default `True`).
- The docstring already mentions Anthropic: “output_format parameter (with beta header)”.

### 2.3 Anthropic SDK supports structured output via beta
The local SDK (`.venv/.../anthropic`) shows a beta messages API that accepts `output_format` and `betas`:

```python
# .venv/lib/python3.13/site-packages/anthropic/resources/beta/messages/messages.py
# create(..., output_format: Optional[BetaJSONOutputFormatParam], betas: List[AnthropicBetaParam], ...)
```

Beta output format type (local SDK):

```python
# .venv/lib/python3.13/site-packages/anthropic/types/beta/beta_json_output_format_param.py
class BetaJSONOutputFormatParam(TypedDict, total=False):
    schema: Required[Dict[str, object]]
    type: Required[Literal["json_schema"]]
```

So the SDK expects:

```json
{"type": "json_schema", "schema": { ... }}
```

### 2.4 Anthropic docs (Structured Outputs)
The Claude docs show structured outputs gated by a beta flag and `output_format`:

- Example call uses `client.beta.messages.create(...)`
- Requires `betas=["structured-outputs-2025-11-13"]` (or equivalent `anthropic-beta` header)
- `output_format` in the docs matches `{"type": "json_schema", "schema": {...}}`

This matches the SDK beta param shape above.

### 2.5 Docs in this repo explicitly say Anthropic is not supported
File: `mint-docs/concepts/rubrics-and-judges.mdx`

- `CONSTRAINED_DECODING` section currently says: “Supported by OpenAI and OpenRouter. Not yet implemented for Anthropic or Google (will raise NotImplementedError).”
- This should be updated if we add Anthropic support.

## 3. Approach Options

### Option A (Recommended): Use `client.messages.create` with `extra_headers` + `extra_body`
- Keep the existing non‑beta call and stream event types unchanged.
- Add `extra_headers={"anthropic-beta": "structured-outputs-2025-11-13"}`.
- Add `extra_body={"output_format": {...}}`.

**Pros**
- Minimal changes; no need to update streaming event parsing or imports.
- Avoids touching `update_llm_output` (which is tied to non‑beta types).

**Cons**
- Type hints in the SDK don’t include `output_format` for non‑beta messages, so we rely on `extra_body`.

### Option B: Use `client.beta.messages.create`
- Pass `betas=["structured-outputs-2025-11-13"]` and `output_format` directly.

**Pros**
- Aligned with SDK typing and docs.

**Cons**
- Streaming types become beta types (`BetaRawMessageStreamEvent`, `BetaTextDelta`, etc.), which would require modifying `update_llm_output` and related imports.
- Larger change surface for this task.

## 4. Decisions from User Feedback (Resolved)

These resolve the original uncertainties and are now hard requirements for implementation:

1. **`ResponseFormat.strict` handling**
   - **Decision:** If `response_format.strict` is `False`, raise a `ValueError` explaining that Anthropic structured outputs do not support non‑strict mode.

2. **`ResponseFormat.name` handling**
   - **Decision:** Ignore `name` for Anthropic, but log a warning when it is provided (it is always required in `ResponseFormat`).

3. **Beta header version**
   - **Decision:** Pin the header to `structured-outputs-2025-11-13` for now (no config/env override).

## 5. Recommended Implementation (Option A)

### 5.1 Add a ResponseFormat → output_format helper
File: `docent/docent/_llm_util/providers/anthropic.py`

Add a helper similar to OpenAI/OpenRouter:

```python
def _build_output_format(response_format: ResponseFormat | None) -> dict[str, Any] | None:
    if response_format is None:
        return None
    if response_format.strict is False:
        raise ValueError(
            "Anthropic structured outputs do not support strict=False; "
            "set ResponseFormat.strict=True."
        )
    if response_format.type != "json_schema":
        raise ValueError(
            f"Unsupported response format type: {response_format.type}. "
            "Only 'json_schema' is currently supported."
        )
    if response_format.name:
        logger.warning(
            "Anthropic output_format ignores ResponseFormat.name; proceeding without it."
        )
    return {
        "type": "json_schema",
        "schema": response_format.schema_,
    }
```

Notes:
- Anthropic’s beta schema only accepts `type` + `schema`, so `name` is ignored and `strict=False` is rejected (per user decision).

### 5.2 Enable response_format in streaming path
File: `docent/docent/_llm_util/providers/anthropic.py`

Replace the `NotImplementedError` block in `get_anthropic_chat_completion_streaming_async` and add output format + beta header:

```python
if response_format is not None:
    output_format = _build_output_format(response_format)
    create_kwargs["extra_headers"] = {
        "anthropic-beta": "structured-outputs-2025-11-13",
    }
    create_kwargs["extra_body"] = {"output_format": output_format}
```

This goes after `create_kwargs` is built (so you can reuse it for other flags).

### 5.3 Enable response_format in non‑streaming path
File: `docent/docent/_llm_util/providers/anthropic.py`

Do the same in `get_anthropic_chat_completion_async`, replacing the current `NotImplementedError` guard and adding the header/body into `create_kwargs`.

### 5.4 Update docs to reflect new support
File: `mint-docs/concepts/rubrics-and-judges.mdx`

Update the `CONSTRAINED_DECODING` description to say Anthropic is supported now (Google still not implemented). Example edit:

```md
- `CONSTRAINED_DECODING`: Parse entire output as JSON (uses structured output). Supported by OpenAI, OpenRouter, and Anthropic. Not yet implemented for Google.
```

If there are other docs that mention the limitation, update them similarly.

### 5.5 (Optional) Add a tiny unit test or manual verification notes
If you want automated coverage, create a unit test that injects a mocked `AsyncAnthropic` client and asserts `extra_headers` and `extra_body` are passed when `response_format` is provided. This can be a simple async test that stubs `client.messages.create` and inspects its kwargs.

## 6. Validation Steps

- **Manual API check** (recommended):
  - Call Anthropic with `response_format` and confirm the returned `LLMCompletion.text` is valid JSON matching the schema.
  - Validate both streaming and non‑streaming paths if possible.

- **Regression check**:
  - Ensure existing Anthropic calls without `response_format` continue to work (no extra headers/body added).

## 7. Remaining Uncertainties

- None. All prior questions were resolved by user feedback.
