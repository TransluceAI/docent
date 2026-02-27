# Frontend Redux Tech Debt Candidates (`docent_core/_web`)

## High-confidence, low-risk removals

1. Stop storing `collectionId` in Redux and derive it from URL params / explicit props.
   - Current writer: `app/dashboard/[collection_id]/client-layout.tsx` (`setCollectionId` in `useEffect`).
   - Broad readers: charts, agent-run components, permissions hooks.

2. Prune dead `collectionSlice` fields/actions.
   - Likely removable: `hasInitSearchQuery`, slice-level `baseFilter` mirror, `setSortField`, `setSortDirection`.
   - `setCollectionId` also removable once `collectionId` is URL-driven.

3. Remove `embedSlice` from store.
   - Appears unused outside slice/store registration.

4. Remove empty `rubric` and `refinement` reducers from store.
   - These files are effectively being used for shared TypeScript types, not runtime Redux state.
   - Move exported types to `app/types/*` to decouple from Redux.

5. Prune dead `transcriptSlice` fields/actions.
   - Likely unused: `curAgentRun`, dashboard preview fields, solution-summary fields, `updateDraftContent`.

## Medium effort refactors (good payoff)

6. Move `ExperimentViewer` sorting state out of Redux into local/component state.
   - `sortField`/`sortDirection` are currently persisted in localStorage already and mostly scoped to `ExperimentViewer`.
   - This would remove the last meaningful cross-component need for `collectionSlice` sorting state.

7. Remove `replaceFilters` thunk path in chart click handlers.
   - `use-chart-filters` dispatches `replaceFilters` primarily to access Redux `collectionId`.
   - Replace with direct `postBaseFilter` mutation using explicit `collectionId`.

8. Remove `toastSlice` + `ReduxToastHandler` bridge.
   - Current flow: `sseService -> dispatch(setToastNotification) -> ReduxToastHandler -> sonner toast`.
   - Replace with direct toast calls in service or shared helper.

9. Localize `dqlChat` state into `useDqlChat` (or component-local provider), then drop `dqlChatSlice`.
   - Currently used through `useDqlChat` and `DqlAutoGeneratorPanel`.

10. Localize saved-filter selection state, then drop `savedFilterSlice`.
   - `savedFilter` only tracks `surfaceId -> activeFilterId` and is consumed by `useSavedFilters`.
   - Candidate replacement: hook-local state + `sessionStorage`/`localStorage` keyed by `surfaceId`.

## Suggested order

1. Remove empty/unused slices (`embed`, `rubric`, `refinement`) and dead `transcript`/`collection` fields.
2. Eliminate global `collectionId`.
3. Migrate `ExperimentViewer` sort state off Redux.
4. Remove thunk-style filter dispatch in chart handlers.
5. De-Redux toasts.
6. Decide whether to migrate `dqlChat` and `savedFilter` now or keep as follow-up.
