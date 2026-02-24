# Add Collapsible + Pinned Rubric Cards in Agent Run Judge Outputs

## Summary
Implement two UX improvements in the `Judge outputs` tab for agent runs:
1. Make rubric cards collapsible to reduce visual overload.
2. Add pin/unpin behavior for rubric groups, persisted in `localStorage`, with pinned groups always rendered first.

State will be scoped per collection so the same view behavior is reused across agent runs within that collection.

## Scope and Intent
In scope:
1. UI behavior in `docent_core/_web/app/dashboard/[collection_id]/agent_run/components/AgentRunJudgeOutputs.tsx`
2. Local persistence for collapsed/pinned state
3. Stable ordering logic (pinned first)

Out of scope:
1. Backend/API contract changes
2. Changes to judge-output payload shape
3. New global settings pages

## Decisions Locked
1. Collapse behavior: rubric cards only (not per-rollout).
2. Pin scope: rubric ID across versions.
3. Persistence scope: per collection, and reused across agent runs in that collection.

## Implementation Plan

### 1. Add UI state model in `AgentRunJudgeOutputs`
Introduce two sets in component state:
1. `collapsedRubricKeys: Set<string>` where key = `${rubric_id}:${rubric_version}`
2. `pinnedRubricIds: Set<string>` where key = `rubric_id`

Add helper constants/functions:
1. `makeRubricCardKey(rubricId, rubricVersion)`
2. `getUiPrefsStorageKey(collectionId)` (collection-scoped key)
3. Safe `readPrefsFromLocalStorage` and `writePrefsToLocalStorage` with `try/catch`.

### 2. Add localStorage persistence (collection-scoped)
Storage key format:
1. `docent-agent-run-judge-outputs-ui:${collectionId}`

Stored JSON shape:
1. `{ pinnedRubricIds: string[], collapsedRubricKeys: string[] }`

On mount (or `collectionId` change):
1. Read persisted state and hydrate sets.
2. If malformed/missing, fall back to empty sets.

On state changes:
1. Persist both sets back to localStorage.
2. Keep error handling silent except optional `console.warn` parity with existing patterns.

### 3. Add collapsible rubric card UI
For each rubric card:
1. Header becomes a clickable toggle row.
2. Add chevron icon (`ChevronDown` when expanded, `ChevronRight` when collapsed).
3. Keep pin action as a separate icon button in header; stop propagation to avoid accidental collapse toggle.

Body rendering:
1. Render current rollout content only when expanded.
2. Continue using existing `SchemaValueRenderer` and `FailedResultCard` so citation rendering/navigation remains unchanged.

### 4. Add pin/unpin controls and ordering
Add pin button in rubric header (`Pin`/`PinOff` or `Pin` with filled style when active).
Toggle pin by `rubric_id` (not version).

Sorting logic:
1. Partition current response list into `pinned` and `unpinned` by `rubric_id`.
2. Render `pinned` first, then `unpinned`.
3. Preserve original backend order within each partition (stable order).

### 5. Visual/interaction details
1. Add small pinned indicator in header text (icon tint and/or `Pinned` badge).
2. Preserve current spacing conventions (`p-3`, `space-y-3` style consistency).
3. Keep loading/empty/error states as-is.

## Public APIs / Interfaces / Types
Backend REST API: no changes.
RTK query types/endpoints: no changes.

New persisted client-side preference schema in localStorage:
1. Key: `docent-agent-run-judge-outputs-ui:${collectionId}`
2. Value: `{ pinnedRubricIds: string[]; collapsedRubricKeys: string[] }`

## Edge Cases and Failure Modes
1. Malformed localStorage JSON: ignore and reset to defaults.
2. Stale collapsed keys for rubrics not present in current run: harmless; ignored.
3. Pinned rubric ID with no current entries: harmless; no render effect.
4. Multiple versions of a pinned rubric: all versions stay in pinned section.
5. Citation behavior while collapsed: no change; citations work when expanded because renderer path is unchanged.

## Test Cases and Scenarios
Manual behavior checks:
1. Open Judge outputs tab with many rubric groups; collapse/expand individual cards.
2. Refresh page; collapsed states persist.
3. Navigate to another agent run in the same collection; collapsed and pinned states persist.
4. Switch to a different collection; state isolation confirmed.
5. Pin one rubric ID that has multiple versions; all matching cards move to top.
6. Unpin and confirm cards return to unpinned section while preserving base order.
7. Click citation links inside expanded cards; navigation still targets transcript blocks correctly.

Regression checks:
1. Loading, empty, and error states still render.
2. Failure results still render via `FailedResultCard`.
3. No changes to existing API calls/network payloads.

## Assumptions
1. Current backend ordering (newest rubric/version first) is acceptable as the base order.
2. Persisting only pin/collapse state (no global expand all/collapse all controls) is sufficient for this iteration.
3. Existing lint/type checks remain green after UI updates.
