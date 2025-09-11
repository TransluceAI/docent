'use client';

import React, {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';

import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../../../../agent_run/components/AgentRunViewer';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import TranscriptChat from '@/components/TranscriptChat';
import { useGetRubricRunStateQuery } from '@/app/api/rubricApi';
import { useGetAgentRunQuery } from '@/app/api/collectionApi';

import { skipToken } from '@reduxjs/toolkit/query';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { setRunCitations } from '@/app/store/transcriptSlice';
import { Citation } from '@/app/types/experimentViewerTypes';
import { useCitationNavigation } from '../../NavigateToCitationContext';
import { Loader2 } from 'lucide-react';
import LabelArea from './components/LabelArea';
import { useRubricVersion } from '@/providers/use-rubric-version';

export default function JudgeResultPage() {
  const {
    result_id: resultId,
    collection_id: collectionId,
    rubric_id: rubricId,
  } = useParams<{
    result_id: string;
    collection_id: string;
    rubric_id: string;
  }>();

  const dispatch = useAppDispatch();
  const router = useRouter();
  const citationNav = useCitationNavigation();

  const rightSidebarOpen = useAppSelector(
    (state) => state.transcript.rightSidebarOpen
  );

  const searchParams = useSearchParams();
  const { version } = useRubricVersion();
  const activeTabFromUrl = searchParams.get('tab');

  // Local state for active tab, initialized from URL or default to 'chat'
  const [activeTab, setActiveTab] = useState(activeTabFromUrl || 'chat');

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

  const results = rubricRunState?.results;
  const result = results?.find((result) => result.id === resultId);
  const citations = result?.output?.explanation?.citations;
  const agentRunId = result?.agent_run_id as string | undefined;

  // Route guard: redirect if result not found after rubric run state loads
  // But first try refetching once in case the cache is stale
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

  // Calculate initial transcript index from citations
  const initialTranscriptIdx = useMemo(() => {
    if (!citations || citations.length === 0) return undefined;
    return citations[0].transcript_idx ?? 0;
  }, [citations]);

  useEffect(() => {
    if (agentRunId) {
      dispatch(
        setRunCitations({
          [agentRunId]: citations || [],
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

    const citation = citations && citations.length > 0 ? citations[0] : null;
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

  // Update local state when URL parameter changes
  useEffect(() => {
    if (activeTabFromUrl) {
      setActiveTab(activeTabFromUrl);
    }
  }, [activeTabFromUrl]);

  // Handle tab changes by updating local state
  const handleTabChange = useCallback((value: string) => {
    setActiveTab(value);
  }, []);

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
        <ResizablePanelGroup
          direction="horizontal"
          className="h-full min-h-0 min-w-0 flex flex-row border rounded-xl"
          style={{ flexGrow: '2' }}
        >
          <ResizablePanel
            defaultSize={70}
            className="min-w-0 p-3  min-h-0 flex flex-col overflow-hidden"
          >
            <AgentRunViewer
              ref={agentRunViewerRef}
              agentRun={agentRun}
              initialTranscriptIdx={initialTranscriptIdx}
            />
          </ResizablePanel>

          {agentRun && rightSidebarOpen && (
            <ResizableHandle withHandle={true} />
          )}

          {agentRun && rightSidebarOpen && (
            <ResizablePanel
              defaultSize={30}
              className="p-3 min-w-0 min-h-0 h-full flex flex-col"
            >
              <Tabs
                className="flex flex-col h-full min-h-0"
                value={activeTab}
                onValueChange={handleTabChange}
              >
                <TabsList className="grid w-full grid-cols-2 mb-2">
                  <TabsTrigger value="chat">Chat</TabsTrigger>
                  <TabsTrigger value="label">Label</TabsTrigger>
                </TabsList>

                <TabsContent value="chat" className="flex-1 h-full min-h-0">
                  {/* Transcript chat */}
                  <TranscriptChat
                    runId={agentRun.id}
                    collectionId={collectionId}
                    judgeResult={result}
                    resultContext={{
                      rubricId,
                      resultId: result?.id || '',
                    }}
                    onNavigateToCitation={handleNavigateToCitation}
                    className="flex flex-col min-w-0 h-full"
                  />
                </TabsContent>

                <TabsContent value="label" className="flex-1 min-h-0">
                  <LabelArea
                    result={result!}
                    collectionId={collectionId}
                    rubricId={rubricId}
                  />
                </TabsContent>
              </Tabs>
            </ResizablePanel>
          )}
        </ResizablePanelGroup>
      );
    }
  }

  return <Suspense>{agentRunViewerContent}</Suspense>;
}
