'use client';

import { useParams, useSearchParams } from 'next/navigation';
import React, { Suspense, useCallback, useEffect, useRef } from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { setAgentRunSidebarTab } from '@/app/store/transcriptSlice';
import { Card } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';

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
  const routeCollectionId = Array.isArray(params.collection_id)
    ? params.collection_id[0]
    : params.collection_id;

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

  if (!curAgentRunId) {
    return null;
  }

  return (
    <Suspense>
      <ResizablePanelGroup
        autoSaveId={`docent-agent-run-detail-v1-${routeCollectionId}`}
        direction="horizontal"
        id="agent-run-detail-workspace"
      >
        <ResizablePanel
          key="transcript"
          className="min-w-0 overflow-hidden"
          defaultSize={rightSidebarOpen ? 64 : 100}
          id="transcript"
          minSize={45}
          order={1}
        >
          <Card className="flex h-full min-h-0 min-w-0 flex-col space-y-2 overflow-hidden p-3">
            <AgentRunViewer agentRunId={curAgentRunId} ref={setViewerRef} />
          </Card>
        </ResizablePanel>

        {rightSidebarOpen && (
          <React.Fragment key="agent-details">
            <ResizableHandle
              aria-label="Resize transcript and agent details"
              id="agent-run-detail-handle"
              withHandle
            />
            <ResizablePanel
              className="min-w-0 overflow-hidden"
              defaultSize={36}
              id="agent-details"
              maxSize={52}
              minSize={24}
              order={2}
            >
              <Card className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background p-3">
                <Tabs
                  value={selectedTab}
                  onValueChange={(value) =>
                    dispatch(setAgentRunSidebarTab(value))
                  }
                  className="flex h-full min-h-0 flex-col"
                >
                  <TabsList className="grid h-8 w-full shrink-0 grid-cols-2">
                    <TabsTrigger value="agent" className="text-xs">
                      Summary
                    </TabsTrigger>
                    <TabsTrigger value="chat" className="text-xs">
                      Chat
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="agent" className="mt-0 min-h-0 flex-1">
                    <ScrollArea className="h-full pt-2">
                      <AgentSummary agentRunId={curAgentRunId} />
                    </ScrollArea>
                  </TabsContent>

                  <TabsContent value="chat" className="mt-0 min-h-0 flex-1">
                    <div className="flex h-full min-h-0 flex-col pt-2">
                      <TranscriptChat
                        runId={curAgentRunId}
                        collectionId={collectionId}
                        title="Transcript Chat"
                        className="flex min-h-0 min-w-0 flex-1 flex-col"
                      />
                    </div>
                  </TabsContent>
                </Tabs>
              </Card>
            </ResizablePanel>
          </React.Fragment>
        )}
      </ResizablePanelGroup>
    </Suspense>
  );
}
