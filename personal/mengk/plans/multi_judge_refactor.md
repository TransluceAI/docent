**Consolidated feature checklist**
**`evaluate_rubric` expectations**
- Keep the existing signature `(agent_runs, rubric, llm_svc, callback=None, max_concurrent_llm_calls=...)`.
- Validate inputs (non-empty agent runs, positive concurrency limits, rollouts per input).
- Reuse the richer concurrency logic so each agent run respects `n_rollouts_per_input`.
- Track per-agent duration metadata and merge into results.
- Provide optional progress reporting scoped to the agent-run loop (and make it suppressible as needed).
- Trigger callbacks exactly once per agent run with the computed `JudgeResult | None`.
- Preserve ordering of returned results.

**Multi-judge helpers (new)**
- Accept a sequence of `Rubric` configs plus a single shared `BaseLLMService` instance.
- Coordinate judge-level concurrency, logging, and progress similar to `_run_judges`.
- Collect outputs into `JudgeSweepRow` objects while maintaining judge/agent ordering.
- Offer an atomic file-writing helper (temp file swap, JSON serialization) for persisted sweeps.
