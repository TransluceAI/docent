# Plan: QA Rubric Elicitation Prototype

## Goal
Create a prototype dashboard page at `docent_core/_web/app/dashboard/[collection_id]/qa` that triggers a REST endpoint to run the rubric ambiguity pipeline up to question framing and renders the questions with clickable citations. When a citation is clicked, keep the QA results visible and open the cited agent run side-by-side (mirroring the judge results layout behavior).

## Context
- `personal/mengk/rubric_elicit/elicit_ambiguities.py` defines the sampling, per-run uncertainty, aggregation, and question framing steps, plus `resolve_citations_with_context` usage to emit `InlineCitation`-shaped data.
- `docent_core/_web/components/CitationRenderer.tsx` provides `TextWithCitations`/`MarkdownWithCitations` and uses `useCitationNavigation` for click handling.
- `docent_core/_web/providers/CitationNavigationProvider.tsx` implements pending citation routing and `wrapCitationHandlerWithRouting` for cross-agent-run navigation.
- `docent_core/_web/app/dashboard/[collection_id]/rubric/[rubric_id]/layout.tsx` and `docent_core/_web/app/dashboard/[collection_id]/agent_run/[agent_run_id]/layout.tsx` show how citation navigation handlers are registered.
- `docent_core/_web/app/dashboard/[collection_id]/qa/page.tsx` currently registers a citation handler that routes to the full agent run page:
  ```tsx
  router.push(
    `/dashboard/${collectionId}/agent_run/${target.item.agent_run_id}`,
    { scroll: false } as any
  );
  ```
  This replaces the QA results view instead of keeping it side-by-side.
- `docent_core/_web/app/dashboard/[collection_id]/qa/layout.tsx` only wraps `CitationNavigationProvider` and does not implement a split-panel layout.
- `docent_core/docent/server/rest/router.py` exposes collection agent-run endpoints via `MonoService`, and `docent_core/docent/server/dependencies/services.py` provides `get_llm_svc` for LLM-backed work.
- `docent_core/_server/_rest/_all_routers.py` is where new REST routers are registered.
- Judge results split layout reference:
  - `docent_core/_web/app/dashboard/[collection_id]/rubric/[rubric_id]/layout.tsx` uses `ResizablePanelGroup`/`ResizablePanel`/`ResizableHandle` to keep side-by-side panels and hides the right panel when not on a result route. It also registers a citation handler when *not* on the agent run route:
    ```tsx
    const handler = ({ target }: { target: any; source?: string }) => {
      citationNav.setPendingCitation(target);
      router.push(
        `/dashboard/${collectionId}/rubric/${rubricId}/agent_run/${target.item.agent_run_id}`
      );
    };
    ```
  - `docent_core/_web/app/dashboard/[collection_id]/rubric/[rubric_id]/agent_run/[agent_run_id]/layout.tsx` renders `AgentRunViewer` and uses `wrapCitationHandlerWithRouting` to focus citations and navigate across agent runs.

## Questions
No open questions. Inputs include rubric text plus `num_samples` and `top_k`, the default model is `claude-opus-4-5-20251101`, the UI renders question + context + example options, sampling should be randomized, and QA results must stay visible while agent runs open side-by-side.

## Approach
- Add a prototype REST endpoint (new router or `user_router`) that accepts `collection_id`, rubric description, and `num_samples`/`top_k`, then runs sampling -> per-run uncertainty -> aggregation -> framing using `MonoService` and `LLMService` with the `claude-opus-4-5-20251101` model. Randomize the sampled agent runs (not first N). Reuse/adapt logic from `elicit_ambiguities.py` so the response includes `framed_question`, `question_context`, `example_options`, and their citation arrays in `InlineCitation` format.
- Move the QA UI into a reusable component (e.g., `docent_core/_web/app/dashboard/[collection_id]/qa/components/QaRubricElicitationPanel.tsx`) and render it from the QA layout so it stays mounted across nested routes.
- Update `docent_core/_web/app/dashboard/[collection_id]/qa/layout.tsx` to mirror the judge results layout: use a `ResizablePanelGroup` with the QA panel on the left and `{children}` on the right, showing the right panel only when `agent_run_id` is present. Register the citation handler **in the layout** (not the page) and route to `/dashboard/${collectionId}/qa/agent_run/${agent_run_id}` so the QA panel remains visible.
- Add a QA-specific agent-run nested layout at `docent_core/_web/app/dashboard/[collection_id]/qa/agent_run/[agent_run_id]/layout.tsx` that renders `AgentRunViewer` and registers a citation handler that focuses the current run or routes to another QA agent run while preserving pending citations.

## Steps
1. Define the REST request/response models and implement the endpoint that returns framed questions, context, and example options plus citations, using `MonoService` and `LLMService` with randomized agent run sampling and the prompt/citation logic from `elicit_ambiguities.py`.
2. Register the new router in `docent_core/_server/_rest/_all_routers.py` if it is not added to `user_router`.
3. Extract the QA UI into `docent_core/_web/app/dashboard/[collection_id]/qa/components/QaRubricElicitationPanel.tsx`:
   - Move the existing `qa/page.tsx` content into this component.
   - Remove the `useCitationNavigation` handler and `router.push` logic from the component (the layout will handle navigation).
   - Keep the `apiRestClient` POST, inputs, and `TextWithCitations` rendering unchanged.
4. Refactor `docent_core/_web/app/dashboard/[collection_id]/qa/layout.tsx` into a split layout:
   - Keep `CitationNavigationProvider` at the top.
   - Inside a client `QaLayoutBody`, use `useParams` to read `collection_id` and optional `agent_run_id`.
   - Use `ResizablePanelGroup`/`ResizablePanel`/`ResizableHandle` (as in `rubric/[rubric_id]/layout.tsx`) to render the QA panel on the left and `{children}` on the right.
   - Hide or collapse the right panel when `agent_run_id` is absent. Optionally use `ImperativePanelHandle` refs to resize left/right when toggling routes (see `rubric/[rubric_id]/layout.tsx` for `resize(...)` usage).
   - Register the citation handler here when not on an agent run route:
     ```tsx
     const handler = ({ target }: { target: CitationTarget; source?: string }) => {
       if (target.item.item_type === 'analysis_result') return;
       citationNav.setPendingCitation(target);
       router.push(
         `/dashboard/${collectionId}/qa/agent_run/${target.item.agent_run_id}`,
         { scroll: false } as any
       );
     };
     ```
     Clean up with `citationNav.registerHandler(null)` on unmount or when `agent_run_id` appears.
5. Update `docent_core/_web/app/dashboard/[collection_id]/qa/page.tsx` to a minimal placeholder (like `rubric/[rubric_id]/page.tsx`) so the layout controls rendering, e.g.:
   ```tsx
   return (
     <Suspense>
       <div className="flex-1" />
     </Suspense>
   );
   ```
6. Add `docent_core/_web/app/dashboard/[collection_id]/qa/agent_run/[agent_run_id]/layout.tsx` to render the agent run viewer:
   - Import `AgentRunViewer` and `AgentRunViewerHandle` from `docent_core/_web/app/dashboard/[collection_id]/agent_run/components/AgentRunViewer.tsx`.
   - Use a `ref` to call `focusCitationTarget` on the viewer.
   - Register a citation handler (similar to `wrapCitationHandlerWithRouting`) that:
     - focuses citations when `target.item.agent_run_id === agentRunId` or `item_type === 'analysis_result'`;
     - otherwise calls `citationNav.setPendingCitation(target, source)` and `router.push(`/dashboard/${collectionId}/qa/agent_run/${citedId}`, { scroll: false } as any)`.
   - Clean up `registerHandler(null)` on unmount.
7. Manually exercise the flow end-to-end:
   - Run QA prototype and click citations.
   - Confirm QA results remain on the left and the agent run viewer appears on the right.
   - Confirm cross-run citations keep the `/qa/agent_run/...` route and still focus the cited content.

## Risks / Open Issues
- LLM calls can be slow or exceed typical HTTP timeouts; the endpoint may need longer timeouts or background jobs if it proves too slow.
- Citation indices must align with returned question text; any mismatch breaks highlighting or click targets.
- Large agent runs may need truncation like the script to avoid token limits.
- Access control should be read-scoped to the collection; confirm the proper permission dependency for the new endpoint.
- Layout changes can leave stale citation handlers registered; ensure only one handler is active at a time when toggling between QA-only and QA+agent-run routes.

## Implementation Notes / Handoff Context
- Decisions from user feedback: accept rubric text + `num_samples` + `top_k`, use `claude-opus-4-5-20251101`, render question + context + example options, and randomize agent run sampling.
- Pipeline reference: `personal/mengk/rubric_elicit/elicit_ambiguities.py` (sampling -> per-run uncertainties -> aggregation -> question framing; uses `LLMContext` + `resolve_citations_with_context`, `truncate_text`, and `ModelOption`).
- Citation rendering: `docent_core/_web/components/CitationRenderer.tsx` (`TextWithCitations` expects `InlineCitation[]` with valid start/end indices).
- Citation types: `docent_core/_web/app/types/citationTypes.ts`.
- Citation navigation: `docent_core/_web/providers/CitationNavigationProvider.tsx` and patterns in `docent_core/_web/app/dashboard/[collection_id]/agent_run/[agent_run_id]/layout.tsx` and `docent_core/_web/app/dashboard/[collection_id]/rubric/[rubric_id]/layout.tsx`.
- REST router registry: `docent_core/_server/_rest/_all_routers.py` (add new router if needed).
- Server services: `docent_core/docent/server/dependencies/services.py` (`get_llm_svc`, `get_mono_svc`), `docent_core/docent/services/monoservice.py` (`get_agent_run_ids`, `get_agent_run`).
- Frontend API base: `docent_core/_web/app/constants.ts` (`BASE_URL`) and `docent_core/_web/app/services/apiService.ts` (`apiRestClient`).
- New UI route location: `docent_core/_web/app/dashboard/[collection_id]/qa/layout.tsx` renders the QA panel; `docent_core/_web/app/dashboard/[collection_id]/qa/page.tsx` can be a placeholder; nested route `docent_core/_web/app/dashboard/[collection_id]/qa/agent_run/[agent_run_id]/layout.tsx` renders `AgentRunViewer` in the right panel.
- Click handling: in QA layout, register a handler that calls `setPendingCitation(target)` and routes to `/dashboard/${collectionId}/qa/agent_run/${target.item.agent_run_id}`. The agent run layout then focuses the pending citation via its `AgentRunViewer` handler.
