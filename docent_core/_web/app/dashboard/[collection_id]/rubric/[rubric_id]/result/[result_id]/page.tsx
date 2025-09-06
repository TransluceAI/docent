'use client';

import React, {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from 'react';

import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../../../../agent_run/components/AgentRunViewer';
import { useParams, useRouter } from 'next/navigation';
import TranscriptChat from '@/components/TranscriptChat';
import { Card } from '@/components/ui/card';
import { useGetRubricRunStateQuery } from '@/app/api/rubricApi';
import { useGetAgentRunQuery } from '@/app/api/collectionApi';

import { skipToken } from '@reduxjs/toolkit/query';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { setRunCitations } from '@/app/store/transcriptSlice';
import { Citation } from '@/app/types/experimentViewerTypes';
import { useCitationNavigation } from '../../NavigateToCitationContext';
import { Loader2 } from 'lucide-react';

export default function JudgeResultPage() {
  const params = useParams();
  const dispatch = useAppDispatch();
  const router = useRouter();
  const citationNav = useCitationNavigation();

  const rightSidebarOpen = useAppSelector(
    (state) => state.transcript.rightSidebarOpen
  );

  const resultId = params.result_id as string;
  const collectionId = params.collection_id as string;
  const rubricId = params.rubric_id as string;

  const {
    data: rubricRunState,
    isLoading: isLoadingRubricRunState,
    isError: isErrorRubricRunState,
  } = useGetRubricRunStateQuery(
    {
      collectionId,
      rubricId,
    },
    {
      pollingInterval: 0,
    }
  );

  const results = rubricRunState?.results;
  const result = results?.find((result) => result.id === resultId);
  const agentRunId = result?.agent_run_id as string | undefined;

  // Route guard: redirect if result not found after rubric run state loads
  useEffect(() => {
    if (
      !isLoadingRubricRunState &&
      !isErrorRubricRunState &&
      rubricRunState &&
      !result
    ) {
      router.replace(`/dashboard/${collectionId}/rubric/${rubricId}`);
    }
  }, [
    isLoadingRubricRunState,
    isErrorRubricRunState,
    rubricRunState,
    result,
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

  const resultCitations = result?.output.explanation?.citations;

  // Calculate initial transcript index from citations
  const initialTranscriptIdx = useMemo(() => {
    if (!resultCitations || resultCitations.length === 0) return undefined;
    return resultCitations[0].transcript_idx ?? 0;
  }, [resultCitations]);

  useEffect(() => {
    if (agentRunId) {
      dispatch(
        setRunCitations({
          [agentRunId]: resultCitations || [],
        })
      );
    }
  }, [result, agentRunId, dispatch]);

  const {
    data: agentRun,
    isLoading: isLoadingAgentRun,
    isError: isErrorAgentRun,
  } = useGetAgentRunQuery(
    agentRunId ? { collectionId, agentRunId } : skipToken
  );

  // Reset the gate whenever the selected result changes so the next result can
  // perform its own one-time initial scroll.
  useEffect(() => {
    alreadyScrolledRef.current = false;
  }, [resultId]);

  // Perform the initial one-time scroll to the first citation once both the
  // agent run and the result are available. Skip if we've already scrolled for
  // this result. We still call scroll even though `initialTranscriptIdx` is
  // provided to AgentRunViewer because block positions depend on loaded data.
  useEffect(() => {
    if (alreadyScrolledRef.current) return;
    if (!agentRun || !result) return;

    const citation =
      resultCitations && resultCitations.length > 0 ? resultCitations[0] : null;
    if (!citation) return;

    const blockIdx = citation.block_idx ?? 0;
    const transcriptIdx = citation.transcript_idx ?? 0;

    alreadyScrolledRef.current = true;
    agentRunViewerRef.current?.scrollToBlock(
      blockIdx,
      transcriptIdx,
      0,
      500,
      citation
    );
  }, [agentRun, result]);

  // Create citation navigation handler
  const handleNavigateToCitation = useCallback(
    ({
      citation,
      newTab: _newTab,
    }: {
      citation: Citation;
      newTab?: boolean;
    }) => {
      agentRunViewerRef.current?.scrollToBlock(
        citation.block_idx,
        citation.transcript_idx ?? 0,
        0,
        500,
        citation
      );
    },
    []
  );

  // Register the handler with the route-scoped provider so other components can invoke it
  // Only register when agentRun is loaded so AgentRunViewer is ready
  useEffect(() => {
    if (!agentRun) return;

    if (citationNav?.registerHandler) {
      citationNav.registerHandler(handleNavigateToCitation);
    }
    return () => {
      if (citationNav?.registerHandler) {
        citationNav.registerHandler(null);
      }
    };
  }, [citationNav, handleNavigateToCitation, agentRun]);

  if (isLoadingRubricRunState) {
    return (
      <div className="flex-1 flex items-center justify-center min-h-0">
        <Loader2 size={16} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isErrorRubricRunState || !rubricRunState) {
    return (
      <div className="flex-1 flex items-center text-xs text-muted-foreground justify-center min-h-0">
        Failed to load rubric run state.
      </div>
    );
  }

  let agentRunViewerContent = null;
  if (agentRunId) {
    if (isLoadingAgentRun) {
      agentRunViewerContent = <div>Loading agent run...</div>;
    } else if (isErrorAgentRun) {
      agentRunViewerContent = <div>Failed to load agent run.</div>;
    } else if (agentRun) {
      agentRunViewerContent = (
        <AgentRunViewer
          ref={agentRunViewerRef}
          agentRun={agentRun}
          initialTranscriptIdx={initialTranscriptIdx}
        />
      );
    }
  }

  return (
    <Suspense>
      {agentRunViewerContent}
      {agentRun && rightSidebarOpen && (
        <Card className="shrink-0 grow-1 basis-1/4 flex flex-col min-w-0 min-h-0 bg-background h-full">
          <TranscriptChat
            runId={agentRun.id}
            collectionId={collectionId}
            judgeResult={result}
            resultContext={{
              rubricId,
              resultId: result?.id || '',
            }}
            onNavigateToCitation={handleNavigateToCitation}
            className="flex-1 flex flex-col min-w-0 min-h-0"
          />
        </Card>
      )}
    </Suspense>
  );
}
