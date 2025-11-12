'use client';

import React, { Suspense, useEffect, useRef } from 'react';
import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../../../../agent_run/components/AgentRunViewer';
import { useParams } from 'next/navigation';
import { useGetRubricRunStateQuery } from '@/app/api/rubricApi';

import { useAppDispatch } from '@/app/store/hooks';
import { setRunCitations } from '@/app/store/transcriptSlice';
import { useCitationNavigation } from '../../NavigateToCitationContext';
import { useRubricVersion } from '@/providers/use-rubric-version';
import { useLabelSets } from '@/providers/use-label-sets';

export default function JudgeResultPage() {
  const {
    agent_run_id: agentRunId,
    collection_id: collectionId,
    rubric_id: rubricId,
    result_id: resultId,
  } = useParams<{
    agent_run_id: string;
    collection_id: string;
    rubric_id: string;
    result_id?: string;
  }>();

  const dispatch = useAppDispatch();
  const citationNav = useCitationNavigation();
  const { version } = useRubricVersion();
  const { activeLabelSet } = useLabelSets(rubricId);
  const isResultRoute = !!resultId;

  // Get all results from rubric run state
  const { data: rubricRunState } = useGetRubricRunStateQuery(
    {
      collectionId,
      rubricId,
      version: version ?? null,
      labelSetId: activeLabelSet?.id ?? null,
    },
    { skip: !isResultRoute }
  );

  // Find the current result by resultId
  const currentAgentRunGroup = rubricRunState?.results?.find((arr) =>
    arr.results.some((r) => r.id === resultId)
  );
  const result = currentAgentRunGroup?.results.find((r) => r.id === resultId);

  const citations = result?.output?.explanation?.citations;

  const agentRunViewerRef = useRef<AgentRunViewerHandle>(null);
  // One-shot auto-scroll gate:
  // When a judge result loads, we programmatically scroll the AgentRunViewer to
  // the first citation exactly once. Data arrives in phases (Suspense hydration,
  // RTK queries, Redux updates), which can re-trigger effects and fight the
  // user's manual scroll. This ref flips true after the first programmatic
  // scroll and is reset when the selected result changes.
  const alreadyScrolledRef = useRef(false);

  useEffect(() => {
    if (agentRunId && result) {
      dispatch(
        setRunCitations({
          [agentRunId]: citations || [],
        })
      );
    }
  }, [result, agentRunId, citations, dispatch]);

  // Reset the gate whenever the selected result changes so the next result can
  // perform its own one-time initial scroll.
  useEffect(() => {
    alreadyScrolledRef.current = false;
  }, [agentRunId, resultId]);

  // Perform the initial one-time scroll to the first citation once both the
  // agent run and the result are available. Skip if we've already scrolled for
  // this result. We still call scroll even though `initialTranscriptIdx` is
  // provided to AgentRunViewer because block positions depend on loaded data.
  useEffect(() => {
    if (alreadyScrolledRef.current) return;
    if (!agentRunId || !result) return;

    const citation = citations && citations.length > 0 ? citations[0] : null;
    if (!citation) return;

    agentRunViewerRef.current?.focusCitation(citation);
    alreadyScrolledRef.current = true;
  }, [agentRunId, result, citations]);

  // Register the handler with the route-scoped provider so other components can invoke it
  // Only register when agentRun is loaded so AgentRunViewer is ready
  useEffect(() => {
    if (!agentRunId) return;

    if (citationNav?.registerHandler) {
      citationNav.registerHandler(({ citation }) => {
        agentRunViewerRef.current?.focusCitation(citation);
      });
    }
    return () => {
      if (citationNav?.registerHandler) {
        citationNav.registerHandler(null);
      }
    };
  }, [citationNav, agentRunId]);

  let agentRunViewerContent = null;
  if (agentRunId) {
    agentRunViewerContent = (
      <div className="h-full overflow-hidden flex flex-col space-y-2">
        <AgentRunViewer ref={agentRunViewerRef} agentRunId={agentRunId} />
      </div>
    );
  }

  return <Suspense>{agentRunViewerContent}</Suspense>;
}
