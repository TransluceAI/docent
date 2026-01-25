# Plan: Fix resume/save logic in rubric elicitation

## 1) Goal / Restatement
We need to update the save/restore logic in `personal/mengk/rubric_elicit/elicit_ambiguities.py` so that:
- `--resume-step` is **always required** when `--resume` is used.
- If resuming at an **earlier iteration** than the latest in the checkpoint, **truncate/delete later iterations** so we do not keep stale history.
- Backwards compatibility with legacy checkpoint fields is **not required** (so we can remove old fields entirely).
- Add the optional guard that a resume must still have **>= 10** agent runs fetched, similar to the fresh sample path.

## 2) Relevant Codebase Findings (self‑contained)

### 2.1 Checkpoint schema and legacy fields
File: `personal/mengk/rubric_elicit/elicit_ambiguities.py`

`PipelineCheckpoint` includes iteration history **and** legacy single-pass fields that are no longer used:
```python
class PipelineCheckpoint(BaseModel):
    # ...
    iteration_history: list[IterationState] = []
    final_rubric_text: str | None = None
    final_rubric_version: int | None = None
    convergence_reason: str | None = None

    # Legacy single-pass fields (kept for backwards compatibility with old checkpoints)
    extracted_questions: list[ElicitedQuestion] | None = None
    selected_questions: list[ElicitedQuestion] | None = None
    dedup_metadata: dict[str, Any] | None = None
    user_answers: list[UserAnswerWithContext] | None = None
    bottleneck_results: list[BottleneckExtractionResult] | None = None
    aggregated_result: AggregatedRubricResult | None = None
```
(around `personal/mengk/rubric_elicit/elicit_ambiguities.py:130-158`)

We no longer need these legacy fields. Remove them entirely.

### 2.2 Resume state selection
File: `personal/mengk/rubric_elicit/elicit_ambiguities.py`

`get_resume_state` currently allows auto-resume (no resume-step) when the last iteration is complete; otherwise it errors:
```python
def get_resume_state(checkpoint, resume_step_str):
    if resume_step_str:
        target_iteration, target_step = parse_resume_step(resume_step_str)
        iter_state = validate_resume_state(checkpoint, target_iteration, target_step)
        return (target_iteration, target_step, iter_state)

    if not checkpoint.iteration_history:
        return (1, 1, None)

    last_iteration = checkpoint.iteration_history[-1]
    if last_iteration.is_complete():
        return (len(checkpoint.iteration_history) + 1, 1, None)

    raise ValueError("Checkpoint has a partial iteration ... Use --resume-step ...")
```
(around `personal/mengk/rubric_elicit/elicit_ambiguities.py:289-330`)

We will change behavior so `--resume-step` is **required** whenever `--resume` is provided. This means the auto-resume branch should be removed or gated by explicit error if `resume_step_str` is missing.

### 2.3 Resuming logic in `run_elicitation`
File: `personal/mengk/rubric_elicit/elicit_ambiguities.py`

`run_elicitation` uses `get_resume_state` and then copies `iteration_history` as-is:
```python
if resume_from:
    target_iteration, target_step, existing_iter_state = get_resume_state(
        checkpoint, resume_step
    )
    ...
# later
iteration_history = list(checkpoint.iteration_history)
```
(around `personal/mengk/rubric_elicit/elicit_ambiguities.py:948-986`)

Later, in `save_step_checkpoint`, new iterations append to `iteration_history` if `iter_in_history` is false:
```python
if is_in_history:
    iter_history[iter_state.iteration - 1] = iter_state
else:
    iter_history.append(iter_state)
```
(around `personal/mengk/rubric_elicit/elicit_ambiguities.py:1007-1014`)

If we resume at an earlier iteration, stale later iterations remain, and new ones append, leading to duplicate iteration numbers and invalid history indexing. We need to truncate `iteration_history` when resuming earlier than the latest iteration.

### 2.4 Agent run fetching on resume
File: `personal/mengk/rubric_elicit/elicit_ambiguities.py`

Resume path fetches agent runs from saved IDs but does not enforce the same “>=10” minimum as `sample_agent_runs`:
```python
if resume_from and checkpoint.agent_run_ids:
    agent_runs = []
    for agent_run_id in checkpoint.agent_run_ids:
        agent_run = dc.get_agent_run(collection_id, agent_run_id)
        if agent_run is not None:
            agent_runs.append(agent_run)
        else:
            print(f"Warning: Could not fetch agent run {agent_run_id}")
    print(f"✓ Retrieved {len(agent_runs)} agent runs from checkpoint\n")
```
(around `personal/mengk/rubric_elicit/elicit_ambiguities.py:931-941`)

We should add a check here to raise a `ValueError` if fewer than 10 agent runs are actually retrieved.

## 3) Approach Options and Decision

### Option A (chosen): Require explicit `--resume-step` and truncate history
- Simpler logic, removes ambiguous auto-resume paths.
- Matches user requirement: resuming earlier than last iteration deletes later iterations.
- Avoids having to decide whether a converged checkpoint is “complete.”

### Option B: Keep auto-resume, add extra completion flags
- More code, requires extra state to mark completion when convergence happens.
- Not requested.

Decision: **Option A**.

## 4) Implementation Plan (concrete steps)

### Step 1: Require `--resume-step` whenever `--resume` is provided
File: `personal/mengk/rubric_elicit/elicit_ambiguities.py`

Where to enforce:
- Easiest and clearest: inside `run_elicitation`, right after loading the checkpoint and before calling `get_resume_state`.

Implementation detail (pseudocode):
```python
if resume_from and not resume_step:
    raise ValueError("--resume-step is required when using --resume")
```

Then simplify `get_resume_state` to only accept the explicit branch. It can either:
- be left as-is but assume `resume_step_str` is non-null, or
- remove the auto-detect branch entirely and raise if `resume_step_str` is None.

Keep `parse_resume_step` and `validate_resume_state` the same.

### Step 2: Truncate iteration history when resuming earlier than the latest iteration
File: `personal/mengk/rubric_elicit/elicit_ambiguities.py`

After `target_iteration, target_step, existing_iter_state = get_resume_state(...)`, add logic:

- If `target_iteration < len(checkpoint.iteration_history)`:
  - Truncate: `checkpoint.iteration_history = checkpoint.iteration_history[:target_iteration]`.
  - This ensures all later iterations are deleted.
- Also clear final/convergence markers because the resumed run is no longer final:
  - `checkpoint.final_rubric_text = None`
  - `checkpoint.final_rubric_version = None`
  - `checkpoint.convergence_reason = None`

Important: `target_iteration` is 1‑indexed while list slicing is 0‑indexed.

Suggested code snippet to embed (after `get_resume_state` call):
```python
if target_iteration < len(checkpoint.iteration_history):
    checkpoint.iteration_history = checkpoint.iteration_history[:target_iteration]
    checkpoint.final_rubric_text = None
    checkpoint.final_rubric_version = None
    checkpoint.convergence_reason = None
```

Note: This only truncates when resuming **earlier than the last iteration**. If resuming within the latest iteration (same iteration number), we keep history as-is.

### Step 3: Remove legacy checkpoint fields
File: `personal/mengk/rubric_elicit/elicit_ambiguities.py`

Remove these fields entirely from `PipelineCheckpoint`:
- `extracted_questions`
- `selected_questions`
- `dedup_metadata`
- `user_answers`
- `bottleneck_results`
- `aggregated_result`

Also remove any comments about backwards compatibility.

No other code references these fields (search confirmed), so this is safe.

### Step 4: Enforce minimum agent runs on resume
File: `personal/mengk/rubric_elicit/elicit_ambiguities.py`

After fetching agent runs from `checkpoint.agent_run_ids`, add the same validation used in `sample_agent_runs`:
```python
if len(agent_runs) < 10:
    raise ValueError(
        f"Only retrieved {len(agent_runs)} valid agent runs from checkpoint. "
        "Need at least 10 for meaningful analysis."
    )
```

This mirrors the fresh path and prevents a “resume” from silently proceeding with too few runs.

### Step 5: Update checkpoint save flow if needed
No functional change required, but ensure any truncation to `iteration_history` is persisted. After truncating, set `checkpoint.last_updated` and call `save_checkpoint` **before** continuing the run if you want immediate disk consistency.

A minimal approach:
- After truncation, just keep `checkpoint.iteration_history` in memory. The next `save_checkpoint` (after step completion) will persist it.

If you want immediate persistence, add:
```python
checkpoint.last_updated = datetime.now(timezone.utc)
save_checkpoint(checkpoint_path, checkpoint)
```

## 5) Edge Cases / Risks
- If the user resumes at iteration `1` when `iteration_history` is empty, truncation is a no‑op.
- If `resume_step` points to a step earlier than `iter_state.current_step` in the same iteration, we will keep the iteration record and overwrite it as steps re-run. This is OK.
- Removing legacy fields means older checkpoint JSONs might fail to validate if they rely on those fields exclusively (accepted per requirement).

## 6) Testing / Verification
Manual checks are sufficient (no automated tests here):
1. **Resume requires resume-step**:
   - Run: `python personal/mengk/rubric_elicit/elicit_ambiguities.py <collection> <rubric> --resume checkpoint.json`
   - Expect: Error about missing `--resume-step`.

2. **Truncation works**:
   - Create a checkpoint with 3 iterations in `iteration_history`.
   - Resume with `--resume-step 2.1`.
   - After first save, verify checkpoint JSON only contains iterations 1–2.

3. **Resume guard for agent runs**:
   - Edit checkpoint `agent_run_ids` to include mostly invalid IDs.
   - Resume; expect `ValueError` about fewer than 10 runs.

## 7) Open Questions / Assumptions
- Assumption: “Earlier iteration” means strictly smaller iteration number; resuming within the latest iteration does **not** truncate history.
- Assumption: It is acceptable for old checkpoints to fail validation if they lack `iteration_history` (no backwards compatibility required).
