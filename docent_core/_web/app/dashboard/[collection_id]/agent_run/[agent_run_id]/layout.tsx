'use client';

import React, { useCallback, useEffect, useRef } from 'react';

import ExperimentViewer from '../../../../components/ExperimentViewer';
import { useParams, useSearchParams } from 'next/navigation';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';

import { setAgentRunSidebarTab } from '@/app/store/transcriptSlice';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import { cn } from '@/lib/utils';

import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../components/AgentRunViewer';
import TranscriptChat from '@/components/TranscriptChat';
import AgentRunLabels from '../components/AgentRunLabels';
import { useCitationNavigation } from '../../rubric/[rubric_id]/NavigateToCitationContext';

export default function AgentRunLayout() {
  const { collection_id: collectionId, agent_run_id: agentRunId } = useParams<{
    collection_id: string;
    agent_run_id: string;
  }>();

  const leftSidebarOpen = useAppSelector(
    (state) => state.transcript.agentRunLeftSidebarOpen
  );

  const searchParams = useSearchParams();
  const disableAITools = searchParams.get('tools') === 'false';

  const dispatch = useAppDispatch();

  const rightSidebarOpen = useAppSelector(
    (state) => state.transcript.agentRunRightSidebarOpen
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
    <ResizablePanelGroup
      direction="horizontal"
      className="flex-1 flex bg-card space-x-3 min-h-0 shrink-0 border rounded-lg"
    >
      {/* Left: ExperimentViewer (collapsible) */}
      <ResizablePanel
        defaultSize={25}
        minSize={15}
        maxSize={40}
        className={cn('flex p-3', !leftSidebarOpen && 'hidden')}
      >
        <ExperimentViewer activeRunId={agentRunId} />
      </ResizablePanel>

      <ResizableHandle
        className={cn('!mx-0 !px-0', !leftSidebarOpen && 'hidden')}
      />

      {/* Middle: AgentRunViewer */}
      <ResizablePanel
        defaultSize={50}
        minSize={40}
        maxSize={70}
        className="flex-1 min-w-0 min-h-0 p-3 !mx-0"
      >
        <div className="h-full space-y-2 flex flex-col min-h-0">
          <AgentRunViewer agentRunId={agentRunId} ref={setViewerRef} />
        </div>
      </ResizablePanel>

      <ResizableHandle
        className={cn(!rightSidebarOpen && 'hidden', '!mx-0 !px-0')}
      />

      {/* Right: Tabs (Chat/Labels) (collapsible) */}
      <ResizablePanel
        defaultSize={25}
        minSize={20}
        maxSize={40}
        className={cn('p-3 flex !mx-0', !rightSidebarOpen && 'hidden')}
      >
        <Tabs
          value={selectedTab}
          onValueChange={(value) => dispatch(setAgentRunSidebarTab(value))}
          className="size-full flex flex-col"
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
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}
