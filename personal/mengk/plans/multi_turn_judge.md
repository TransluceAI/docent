Goal: build a multi-turn judge that consumes the agent run transcript once, reasons over multiple assistant turns, and only produces the final JSON verdict by calling a dedicated tool. The tool must enforce the existing output schema so we never persist invalid judge outputs.

Research notes:
- `docent_core/docent/services/refinement.py:404-523` shows the looping pattern we can mirror: detect the role of the last message, call `llm_svc.get_completions` with `tool_choice="auto"`, and stream partial assistant content while caching the final assistant message before appending.
- Tool definitions and execution helpers live alongside the agent logic (`docent_core/docent/ai_tools/rubric/refine.py:154-210`). The `ToolInfo` factory + `execute_*` helper pattern keeps JSON validation centralized and emits `ToolMessage` responses—the judge can reuse this structure for schema validation.
- Judge variants are selected through `docent/docent/judges/impl.py:388-396` and surfaced in the SQLA layer (`docent_core/docent/db/schemas/rubric.py:47-86`), so adding a new variant requires updates in both places as well as the enum in `docent/docent/judges/types.py`.

Open design questions:
- Decide whether to keep the existing `Rubric.system_prompt_template` for multi-turn or author a new, multi-step-friendly system message. The baseline prompt forces immediate JSON output, so we likely need either a new template field or to dynamically rewrite the system prompt when the variant is multi-turn.
- Determine how much intermediate reasoning we want to persist; for now, a simple loop with an assistant scratchpad and a `finalize_judge_result` tool may be enough, but we may also want to allow reflection retries if the tool rejects the JSON.
- Figure out whether we keep the judge result metadata (e.g., list of intermediate thoughts) and how to surface that to callers.

Implementation plan:
1. Extend configuration & enum plumbing
   - Add `MULTI_TURN` (or similar) to `JudgeVariant` and thread it through `SQLARubric.judge_variant` defaults.
   - Update `build_judge` factory to construct the new class and ensure serialization/deserialization handles the variant cleanly.
2. Define the schema-validation tool interface
   - Create a `ToolInfo` factory that matches the refine agent style but tailored to judges (probably with a single `output` argument).
   - Implement an executor that parses the proposed JSON via `parse_and_validate_llm_output`, returning either the normalized payload (success) or an error `ToolMessage` that the model can recover from.
3. Implement `MultiTurnJudge` in `docent/docent/judges/impl.py`
   - Start from a `BaseJudge` subclass but override `__call__` to manage a conversation loop similar to refinement: maintain `list[ChatMessage]`, cap iterations, and use `llm_svc.get_completions(..., tools=[validation_tool], tool_choice="auto")`.
   - On assistant messages with tool calls, execute them synchronously; persist successful validation output and break the loop, otherwise append the returned error message and continue.
   - Ensure the final `JudgeResult` adds any useful metadata (e.g., intermediate assistant turns, tool call status) and still sets `ResultType.DIRECT_RESULT`.
4. Update single-rollout utilities and testing hooks
   - Decide whether `BaseJudge.single_rollout` needs a polymorphic hook or if `MultiTurnJudge` provides its own entry point (may require refactoring to share validation callback logic).
   - Wire the variant into any CLI/dev scripts under `personal/mengk` so manual testing is straightforward.
5. Testing & verification
   - Add targeted unit tests that mock the LLM service to cover: successful multi-turn completion, tool rejection path, and iteration cap.
   - Run existing judge regression tests to confirm other variants are unaffected.

Follow-ups once the core loop works:
- Explore richer telemetry (timestamps per turn, tool call counts) to help debug judge behavior.
- Consider streaming callbacks for partial assistant messages if we want UI parity with the refinement agent.
