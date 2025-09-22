'use client';

import { useParams, useSearchParams } from 'next/navigation';
import React, { Suspense, useCallback, useEffect, useRef } from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { setAgentRunSidebarTab } from '@/app/store/transcriptSlice';
import { Card } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import AgentSummary from '../components/AgentSummary';
import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../components/AgentRunViewer';
import TranscriptChat from '@/components/TranscriptChat';
import { useCitationNavigation } from '../../rubric/[rubric_id]/NavigateToCitationContext';

export default function AgentRunPage() {
  const dispatch = useAppDispatch();

  const collectionId = useAppSelector(
    (state) => state.collection?.collectionId
  );
  const rightSidebarOpen = useAppSelector(
    (state) => state.transcript?.rightSidebarOpen
  );
  const selectedTab = useAppSelector(
    (state) => state.transcript?.agentRunSidebarTab ?? 'chat'
  );

  const params = useParams();
  const curAgentRunId = Array.isArray(params.agent_run_id)
    ? params.agent_run_id[0]
    : params.agent_run_id;

  const agentRunViewerRef = useRef<AgentRunViewerHandle | null>(null);

  const alreadyScrolledRef = useRef(false);
  const searchParams = useSearchParams();
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
        <AgentRunViewer agentRunId={curAgentRunId} ref={setViewerRef} />
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
              <TabsTrigger value="agent" className="text-xs">
                Summary
              </TabsTrigger>
              <TabsTrigger value="chat" className="text-xs">
                Chat
              </TabsTrigger>
            </TabsList>

            <TabsContent value="agent" className="flex-1 mt-0 min-h-0">
              <ScrollArea className="h-full pt-2">
                <AgentSummary agentRunId={curAgentRunId} />
              </ScrollArea>
            </TabsContent>

            <TabsContent value="chat" className="flex-1 mt-0 min-h-0">
              <div className="h-full pt-2 flex flex-col min-h-0">
                <TranscriptChat
                  runId={curAgentRunId}
                  collectionId={collectionId}
                  title="Transcript Chat"
                  className="flex-1 flex flex-col min-w-0 min-h-0"
                />
              </div>
            </TabsContent>
          </Tabs>
        </Card>
      )}
    </Suspense>
  );
}
