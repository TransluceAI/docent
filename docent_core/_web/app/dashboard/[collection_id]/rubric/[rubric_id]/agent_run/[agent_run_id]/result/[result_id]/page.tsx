'use client';

import React, { Suspense, useEffect, useRef } from 'react';
import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../../../../../../agent_run/components/AgentRunViewer';
import { useParams, useRouter } from 'next/navigation';
import { useGetRubricRunStateQuery } from '@/app/api/rubricApi';

import { useAppDispatch } from '@/app/store/hooks';
import { setRunCitations } from '@/app/store/transcriptSlice';
import { useCitationNavigation } from '../../../../NavigateToCitationContext';
import { Loader2 } from 'lucide-react';
import { useRubricVersion } from '@/providers/use-rubric-version';
import { useGetAgentRunQuery } from '@/app/api/collectionApi';

export default function JudgeResultPage() {
  const {
    agent_run_id: agentRunId,
    collection_id: collectionId,
    rubric_id: rubricId,
  } = useParams<{
    agent_run_id: string;
    collection_id: string;
    rubric_id: string;
  }>();

  const dispatch = useAppDispatch();
  const router = useRouter();
  const citationNav = useCitationNavigation();

  const { version } = useRubricVersion();

  const {
    data: rubricRunState,
    isLoading: isLoadingRubricRunState,
    isError: isErrorRubricRunState,
  } = useGetRubricRunStateQuery(
    {
      collectionId,
      rubricId,
      version: version ?? null,
    },
    {
      pollingInterval: 0,
      refetchOnMountOrArgChange: true,
    }
  );

  const {
    data: agentRun,
    isLoading: isLoadingAgentRun,
    isError: isErrorAgentRun,
  } = useGetAgentRunQuery({
    collectionId,
    agentRunId,
  });

  const results = rubricRunState?.results;
  const result = results?.find((result) => result.agent_run_id === agentRunId);
  const citations = result?.output?.explanation?.citations;

  // Route guard: redirect if agent run not found after rubric run state loads
  // NOTE(cadentj): Maybe better to not have this, and just show an agent run viewer placeholder?
  useEffect(() => {
    if (!isLoadingAgentRun && !isErrorAgentRun && !agentRun) {
      router.replace(`/dashboard/${collectionId}/rubric/${rubricId}`);
    }
  }, [
    isLoadingAgentRun,
    isErrorAgentRun,
    agentRun,
    router,
    collectionId,
    rubricId,
  ]);

  const agentRunViewerRef = useRef<AgentRunViewerHandle>(null);
  // One-shot auto-scroll gate:
  // When a judge result loads, we programmatically scroll the AgentRunViewer to
  // the first citation exactly once. Data arrives in phases (Suspense hydration,
  // RTK queries, Redux updates), which can re-trigger effects and fight the
  // user's manual scroll. This ref flips true after the first programmatic
  // scroll and is reset when the selected result changes.
  const alreadyScrolledRef = useRef(false);

  useEffect(() => {
    if (agentRunId) {
      dispatch(
        setRunCitations({
          [agentRunId]: citations || [],
        })
      );
    }
  }, [result, agentRunId, dispatch]);

  // Reset the gate whenever the selected result changes so the next result can
  // perform its own one-time initial scroll.
  useEffect(() => {
    alreadyScrolledRef.current = false;
  }, [agentRunId]);

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
  }, [agentRunId, result]);

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

  if (isLoadingRubricRunState) {
    return (
      <div className="flex-1 flex items-center justify-center min-h-0 h-full">
        <Loader2 size={16} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isErrorRubricRunState || !rubricRunState) {
    return (
      <div className="flex-1 flex items-center text-xs text-muted-foreground justify-center min-h-0 h-full">
        Failed to load rubric run state.
      </div>
    );
  }

  let agentRunViewerContent = null;
  if (agentRunId) {
    if (isLoadingRubricRunState) {
      agentRunViewerContent = <div>Loading agent run...</div>;
    } else if (isErrorRubricRunState) {
      agentRunViewerContent = <div>Failed to load agent run.</div>;
    } else if (rubricRunState) {
      agentRunViewerContent = (
        <div className="h-full border rounded-xl p-3 overflow-hidden flex flex-col space-y-2">
          <AgentRunViewer ref={agentRunViewerRef} agentRunId={agentRunId} />
        </div>
      );
    }
  }

  return <Suspense>{agentRunViewerContent}</Suspense>;
}
