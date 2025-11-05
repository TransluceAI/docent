'use client';

import { useParams, useSearchParams } from 'next/navigation';
import React, { Suspense, useCallback, useEffect, useRef } from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { setAgentRunSidebarTab } from '@/app/store/transcriptSlice';
import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../components/AgentRunViewer';
import TranscriptChat from '@/components/TranscriptChat';
import AgentRunLabels from '../components/AgentRunLabels';
import { useCitationNavigation } from '../../rubric/[rubric_id]/NavigateToCitationContext';

export default function AgentRunPage() {
  const searchParams = useSearchParams();
  const disableAITools = searchParams.get('tools') === 'false';

  const dispatch = useAppDispatch();

  const { collection_id: collectionId, agent_run_id: agentRunId } = useParams<{
    collection_id: string;
    agent_run_id: string;
  }>();

  const rightSidebarOpen = useAppSelector(
    (state) => state.transcript?.rightSidebarOpen
  );
  const selectedTab = useAppSelector(
    (state) =>
      state.transcript?.agentRunSidebarTab ??
      (disableAITools ? 'labels' : 'chat')
  );

  const agentRunViewerRef = useRef<AgentRunViewerHandle | null>(null);

  const alreadyScrolledRef = useRef(false);
  const blockIdxParam = searchParams.get('block_idx');
  const blockIdx = blockIdxParam ? parseInt(blockIdxParam, 10) : undefined;
  const transcriptIdxParam = searchParams.get('transcript_idx');
  const transcriptIdx = transcriptIdxParam
    ? parseInt(transcriptIdxParam, 10)
    : undefined;
  const setViewerRef = useCallback(
    (node: AgentRunViewerHandle | null) => {
      agentRunViewerRef.current = node;
      if (node && blockIdx !== undefined && !alreadyScrolledRef.current) {
        alreadyScrolledRef.current = true;
        node.scrollToBlock({
          blockIdx,
          transcriptIdx: transcriptIdx || 0,
          agentRunIdx: 0,
          highlightDuration: 500,
          citation: undefined,
        });
      }
    },
    [blockIdx, transcriptIdx]
  );

  const citationNav = useCitationNavigation();
  useEffect(() => {
    if (citationNav) {
      citationNav.registerHandler(({ citation }) => {
        agentRunViewerRef.current?.focusCitation(citation);
      });
    }
  }, [citationNav]);

  return (
    <Suspense>
      {/* Transcript */}
      <Card
        className="h-full basis-1/2 p-3 min-h-0 min-w-0 flex flex-col space-y-2"
        style={{ flexGrow: '2' }}
      >
        <AgentRunViewer agentRunId={agentRunId} ref={setViewerRef} />
      </Card>

      {/* Assistant summary / transcript chat */}
      {rightSidebarOpen && (
        <Card className="shrink-0 grow-1 h-full p-3 flex flex-col min-w-0 min-h-0 bg-background basis-2/5">
          <Tabs
            value={selectedTab}
            onValueChange={(value) => dispatch(setAgentRunSidebarTab(value))}
            className="h-full flex flex-col"
          >
            <TabsList className="grid w-full grid-cols-2 h-8">
              <TabsTrigger
                value="chat"
                className="text-xs"
                disabled={disableAITools}
              >
                Chat
              </TabsTrigger>
              <TabsTrigger value="labels" className="text-xs">
                Labels
              </TabsTrigger>
            </TabsList>

            <TabsContent value="chat" className="flex-1 mt-0 min-h-0">
              <div className="h-full pt-2 flex flex-col min-h-0">
                <TranscriptChat
                  agentRunId={agentRunId}
                  collectionId={collectionId}
                  title="Transcript Chat"
                  className="flex-1 flex flex-col min-w-0 min-h-0"
                />
              </div>
            </TabsContent>

            <TabsContent value="labels" className="flex-1 mt-0 min-h-0">
              <div className="h-full pt-2 flex flex-col min-h-0">
                <AgentRunLabels
                  agentRunId={agentRunId}
                  collectionId={collectionId}
                />
              </div>
            </TabsContent>
          </Tabs>
        </Card>
      )}
    </Suspense>
  );
}
