# Goal
- Build a focused helper (likely `personal/mengk/run_judges_lib.py`) that executes one or more `Rubric` objects against a batch of `AgentRun` records and persists the judge outputs to disk.
- Provide a thin, reusable wrapper around the existing judge stack (`docent.judges` + `docent_core.docent.ai_tools.rubric.evaluate_rubric`) similar in spirit to `personal/mengk/var_reduce_lib.py`, but targeting ad hoc judge sweeps rather than parameter sweeps.

# Scope & Interfaces
- **Inputs**
  - `rubrics: list[Rubric]` (objects already validated; duplicates allowed).
  - `agent_runs: list[AgentRun]` (fully hydrated transcripts).
  - `max_concurrent_llm_calls: int` (upper bound for LLM throughput; mirrors `evaluate_rubric`).
  - `output_path: Path` (JSON destination; follow atomic write pattern from `var_reduce_lib.run_experiments`).
- **Outputs**
  - JSON file containing a flat list; each element shaped as:
    ```json
    {
      "rubric": { ... serialized Rubric ... },
      "judge_result": { ... serialized JudgeResult ... },
      "agent_run_id": "..."
    }
    ```
    - Include `None` results when the judge fails for that run so downstream consumers can reason about completion vs. success.
    - Use `.model_dump(mode="json")` for both `Rubric` and `JudgeResult` to stay consistent with pydantic usage in `var_reduce_lib.ExperimentResultDump`.

# Execution Flow
1. **Validate & normalize inputs**
   - Ensure `output_path` does not already exist (raise) and create parent directories.
   - Coerce `max_concurrent_llm_calls ≥ 1`; mirror guardrails in `evaluate_rubric`.
2. **Iterate per-rubric**
   - For each rubric, call `evaluate_rubric(agent_runs, rubric, llm_svc, rollouts_per_input=rubric_rollouts, max_concurrent_llm_calls=max_concurrent_llm_calls, variant=...)`.
   - For now, default `rollouts_per_input=1` and `variant="majority"` unless we extend the API; surface knobs through optional params so the helper stays flexible.
   - Build/obtain an `LLMService` the same way `personal/mengk/var_reduce_lib.run_rubric_evaluation` does (via `DocentDB`, `MonoService`, `UsageService`).
3. **Flatten results**
   - For each `(rubric, JudgeResult | None)` pair, append serialized payload to an in-memory list.
   - Record rubric metadata once per output row (even when duplicates in input list) so repeated rubrics remain distinguishable (look at `Rubric.id`).
4. **Persist atomically**
   - Use temp file dance (`.with_suffix(".tmp")`, `write_text`, `replace`) mirrored from `run_experiments`.
   - Store alongside metadata: timestamp, parameters (`max_concurrent_llm_calls`, rollouts, judge variant) to ease downstream analysis.
5. **Logging & progress**
   - Reuse `tqdm` pattern from `var_reduce_lib` for a friendly progress bar per rubric.
   - Log start/finish for each rubric id and count of successful judge results.

# Concurrency Model
- Leverage `evaluate_rubric`'s internal semaphore handling instead of rolling our own; pass through the overall `max_concurrent_llm_calls`.
- To avoid hammering the DB/LLM service, keep rubric loop sequential at first; if we need parallel rubrics later, wrap in an `anyio.Semaphore` similarly to `run_experiments`.

# Testing & Validation
- Smoke test with a tiny fixture: two mock `AgentRun` objects + a simple rubric using an in-process `SimpleLLMService` stub (like `docent.judges.impl.MajorityVotingJudge` uses).
- Add CLI snippet (optional) for manual invocation that prints summary counts before writing JSON.
- Verify JSON schema by re-loading the file and reconstructing `Rubric`/`JudgeResult` via `model_validate`.
- Confirm repeated rubrics produce repeated entries, not merged aggregates.

# Follow-ups / Nice-to-haves
- Add optional callback hook (mirroring `JudgeResultCompletionCallback`) for streaming consumers.
- Support chunked output flushing for very large batches (append mode) if needed later.
