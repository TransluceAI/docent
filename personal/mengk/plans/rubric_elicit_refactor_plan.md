# Plan: Refactor rubric elicitation helpers into shared library

## 1. Goal / Request Restatement
Refactor the overlapping rubric-elicitation logic in:
- `personal/mengk/rubric_elicit/elicit_ambiguities.py`
- `docent_core/docent/server/rest/qa.py`

so the shared/common functionality lives in a reusable library module at:
- `docent_core/docent/ai_tools/rubric/elicit.py`

while preserving current behavior in both call sites.

## 2. Codebase Exploration (Relevant Findings)

### Shared helpers duplicated in both files
Both files include very similar helper functions:

1) `truncate_text(text: str, max_length: int = 150000) -> tuple[str, bool]`
- In `personal/mengk/rubric_elicit/elicit_ambiguities.py:99-115` and `docent_core/docent/server/rest/qa.py:77-83`.
- Same logic: return `(text, False)` if length <= max; otherwise append a truncation marker.

2) `parse_llm_json_response(response: str) -> dict[str, Any] | None`
- In `personal/mengk/rubric_elicit/elicit_ambiguities.py:151-185` and `docent_core/docent/server/rest/qa.py:85-106`.
- Both attempt direct `json.loads`, then fenced ```json``` block, then regex fallback.
- Differences:
  - `qa.py` fallback regex checks for keys in `("uncertainties", "top_ambiguities", "question")`.
  - `elicit_ambiguities.py` only looks for `"uncertainties"` in fallback regex.
  - `elicit_ambiguities.py` uses a single `match` for `"uncertainties"` only.

3) `create_aggregation_prompt(per_run_results, top_k)`
- Nearly identical blocks in `personal/mengk/rubric_elicit/elicit_ambiguities.py:284-341` and `docent_core/docent/server/rest/qa.py:223-275`.
- Same prompt text and logic for flattening uncertainties.

4) `identify_per_run_uncertainties(...)`
- Same high-level behavior in both files:
  - Build prompts for each run.
  - Batch call `llm_svc.get_completions`.
  - Parse responses with `parse_llm_json_response` and extract `uncertainties`.
- Differences:
  - `elicit_ambiguities.py` uses `BaseLLMService` and prints progress.
  - `qa.py` uses `LLMService` and logs with `logger`.
  - `elicit_ambiguities.py` defines a local `model_option` instead of a shared constant.
  - The `create_per_run_prompt` wording differs between files:
    - `qa.py` prompt is stricter/longer (decision-relevant ambiguities with quality threshold).
    - `elicit_ambiguities.py` prompt is shorter and less strict.

### Other similar but not identical helpers
- `create_question_framing_prompt` is similar but not identical in `elicit_ambiguities.py:413-470` vs `qa.py:302-357`.
- `frame_questions_for_all_ambiguities` is structurally similar but uses different services (Docent client vs MonoService + ViewContext), and returns different model types (`dict` vs `ElicitedQuestion`).

### Existing module under rubric tools
- There is already a rubric tool folder at `docent_core/docent/ai_tools/rubric/` (e.g., `rewrite.py`, `refine.py`).
- New shared library should fit alongside these, so `docent_core/docent/ai_tools/rubric/elicit.py` is consistent.

## 3. Proposed Approach (Minimal Refactor)
Create `docent_core/docent/ai_tools/rubric/elicit.py` containing the shared helpers, and update the two call sites to import/use them. Keep behavior consistent by allowing small configuration differences (e.g., the regex keys for JSON parsing, and prompt text differences staying local).

### Functions to move into the library
1) `DEFAULT_MODEL_OPTION`
- Shared constant used for LLM calls. Currently duplicated in `qa.py` and local variables in `elicit_ambiguities.py`.
- Put in library to standardize.

2) `truncate_text(text: str, max_length: int = 150000) -> tuple[str, bool]`
- Pure utility.

3) `parse_llm_json_response(response: str, keys: Sequence[str]) -> dict[str, Any] | None`
- Generalized to accept the set of keys to search for in the regex fallback.
- Keeps behavior consistent with each caller by providing explicit keys at call sites.
- Example signature:
  ```python
  from collections.abc import Sequence

  def parse_llm_json_response(response: str, keys: Sequence[str]) -> dict[str, Any] | None:
      try:
          return json.loads(response)
      except json.JSONDecodeError:
          pass

      match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
      if match:
          try:
              return json.loads(match.group(1))
          except json.JSONDecodeError:
              pass

      for key in keys:
          match = re.search(rf'\{{.*"{re.escape(key)}".*\}}', response, re.DOTALL)
          if match:
              try:
                  return json.loads(match.group(0))
              except json.JSONDecodeError:
                  continue

      return None
  ```

4) `create_aggregation_prompt(per_run_results: list[dict[str, Any]], top_k: int = 10) -> str`
- The prompt construction block is identical; move it to library and import from both files.

5) Optional: `build_per_run_inputs(...)`
- If desired, split out the repeated prompt/input building loop from `identify_per_run_uncertainties`.
- Keep logging/printing in the caller.

### Keep local in each file
- `create_per_run_prompt(...)`: prompt text differs; keep these local to avoid changing output quality or behavior.
- `create_question_framing_prompt(...)` and `frame_questions_for_all_ambiguities(...)`: similarities exist but diverge in API and return types. Refactoring these into one shared function risks over-engineering and behavior changes.

## 4. Detailed Step-by-Step Plan

### Step 1: Add new shared module
Create `docent_core/docent/ai_tools/rubric/elicit.py` with:
- `DEFAULT_MODEL_OPTION` constant (same as in `qa.py`).
- `truncate_text`.
- `parse_llm_json_response` with `keys` parameter.
- `create_aggregation_prompt`.

Suggested file skeleton:
```python
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from docent._llm_util.providers.preference_types import ModelOption

DEFAULT_MODEL_OPTION = ModelOption(
    provider="anthropic",
    model_name="claude-opus-4-5-20251101",
    reasoning_effort=None,
)


def truncate_text(text: str, max_length: int = 150000) -> tuple[str, bool]:
    if len(text) <= max_length:
        return text, False

    truncated = text[:max_length]
    return truncated + f"\n\n[... TRUNCATED. Original length: {len(text)} chars]", True


def parse_llm_json_response(response: str, keys: Sequence[str]) -> dict[str, Any] | None:
    ...


def create_aggregation_prompt(per_run_results: list[dict[str, Any]], top_k: int = 10) -> str:
    ...
```

### Step 2: Update `docent_core/docent/server/rest/qa.py`
- Remove local definitions of `DEFAULT_MODEL_OPTION`, `truncate_text`, `parse_llm_json_response`, and `create_aggregation_prompt`.
- Import replacements from `docent_core.docent.ai_tools.rubric.elicit`.
- Update calls to `parse_llm_json_response` to pass explicit keys:
  ```python
  parsed = parse_llm_json_response(llm_response or "", keys=("uncertainties", "top_ambiguities", "question"))
  ```
- All other logic should remain the same.

### Step 3: Update `personal/mengk/rubric_elicit/elicit_ambiguities.py`
- Remove local definitions of `truncate_text`, `parse_llm_json_response`, `create_aggregation_prompt`.
- Import these helpers (and optionally `DEFAULT_MODEL_OPTION`) from the new library.
- Replace local `model_option = ModelOption(...)` blocks with `DEFAULT_MODEL_OPTION` where feasible.
- Update `parse_llm_json_response` usages to include appropriate keys:
  - Per-run uncertainties:
    ```python
    parsed = parse_llm_json_response(llm_response or "", keys=("uncertainties",))
    ```
  - Aggregation:
    ```python
    parsed = parse_llm_json_response(llm_response or "", keys=("top_ambiguities",))
    ```
  - Framing:
    ```python
    parsed = parse_llm_json_response(llm_response or "", keys=("question", "example_options", "context"))
    ```
  - Answer sampling:
    ```python
    parsed = parse_llm_json_response(llm_response or "", keys=("answers",))
    ```

### Step 4: Sanity-check behavior and types
- Ensure imports don’t create circular dependencies. The new module only depends on `ModelOption` and standard libs, so it should be safe.
- Confirm `DEFAULT_MODEL_OPTION` is still a good fit for all LLM calls (same as before).
- Ensure `parse_llm_json_response` regex uses escaped keys to avoid regex errors for unusual keys.

### Step 5: (Optional) Consider additional consolidation later
- If desired in a follow-up, evaluate whether to generalize `identify_per_run_uncertainties` or `create_question_framing_prompt` into shared helpers. For this pass, keep them local to avoid over-engineering.

## 5. Open Questions / Clarifications
1) Should `parse_llm_json_response` default keys be set in the shared library, or should all callers always pass explicit keys? (Plan assumes explicit keys for clarity.)
2) Do you want `DEFAULT_MODEL_OPTION` to be shared across the script and API, or should the script continue to create its own `ModelOption` per function? (Plan assumes shared constant is acceptable.)

## 6. Risks / Edge Cases
- If any caller relies on the old fallback regex with only `"uncertainties"`, passing a new key set could change parsing behavior for malformed responses. Using explicit keys per call keeps behavior aligned.
- The personal script lives under `personal/` and may not be imported in production code; ensure imports from `docent_core` are allowed in that environment.

## 7. Implementation Notes
- Keep the refactor minimal: only move identical code and avoid prompt changes.
- Preserve logging vs printing differences by leaving those sections in place.
- Use existing type hints from the original helpers to avoid Pyright regressions.
