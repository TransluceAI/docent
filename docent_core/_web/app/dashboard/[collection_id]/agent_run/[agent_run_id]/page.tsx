'use client';

import React, { useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { PanelLeft, PanelRightClose, PanelRightOpen } from 'lucide-react';

import { useAppDispatch, useAppSelector } from '../../../../store/hooks';
import { Button } from '@/components/ui/button';
import {
  useCitationNavigation,
  wrapCitationHandlerWithRouting,
} from '@/providers/CitationNavigationProvider';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import {
  setAgentRunSidebarTab,
  toggleAgentRunLeftSidebar,
  toggleAgentRunRightSidebar,
} from '@/app/store/transcriptSlice';

import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../components/AgentRunViewer';
import TranscriptChat from '@/components/TranscriptChat';
import AgentRunLabels from '../components/AgentRunLabels';
import AgentRunJudgeOutputs from '../components/AgentRunJudgeOutputs';

export default function AgentRunPage() {
  const params = useParams();
  const collectionId = params.collection_id as string;
  const agentRunId = params.agent_run_id as string;

  const dispatch = useAppDispatch();
  const router = useRouter();

  const rightSidebarOpen = useAppSelector(
    (state) => state.transcript.agentRunRightSidebarOpen
  );
  const selectedTab = useAppSelector(
    (state) => state.transcript?.agentRunSidebarTab ?? 'chat'
  );

  // Restore sidebar tab from localStorage on mount
  useEffect(() => {
    const storageKey = 'docent-agent-run-sidebar-tab';
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (
        stored === 'chat' ||
        stored === 'labels' ||
        stored === 'judge_outputs'
      ) {
        dispatch(setAgentRunSidebarTab(stored));
      }
    } catch (error) {
      console.warn('Failed to restore agent run sidebar tab state', error);
    }
  }, [dispatch]);

  const agentRunViewerRef = useRef<AgentRunViewerHandle | null>(null);

  const citationNav = useCitationNavigation();
  useEffect(() => {
    if (citationNav) {
      const baseHandler = ({ target }: { target: any }) => {
        agentRunViewerRef.current?.focusCitationTarget(target);
      };

      const wrappedHandler = wrapCitationHandlerWithRouting(
        baseHandler,
        router,
        {
          collectionId,
          currentAgentRunId: agentRunId,
        },
        citationNav.setPendingCitation
      );

      citationNav.registerHandler(wrappedHandler);

      return () => {
        citationNav.registerHandler(null);
      };
    }
  }, [citationNav, router, collectionId, agentRunId]);

  return (
    <ResizablePanelGroup
      direction="horizontal"
      autoSaveId="agent-run-content"
      className="size-full"
    >
      {/* Middle: AgentRunViewer */}
      <ResizablePanel
        defaultSize={60}
        minSize={40}
        className="flex-1 min-w-0 min-h-0 p-3"
      >
        <div className="h-full space-y-2 flex flex-col min-h-0">
          <AgentRunViewer
            agentRunId={agentRunId}
            ref={agentRunViewerRef}
            headerLeftActions={
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 cursor-default"
                onClick={() => dispatch(toggleAgentRunLeftSidebar())}
              >
                <PanelLeft className="h-4 w-4" />
              </Button>
            }
            headerRightActions={
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 cursor-default"
                onClick={() => dispatch(toggleAgentRunRightSidebar())}
              >
                {rightSidebarOpen ? (
                  <PanelRightClose className="h-4 w-4" />
                ) : (
                  <PanelRightOpen className="h-4 w-4" />
                )}
              </Button>
            }
          />
        </div>
      </ResizablePanel>

      <ResizableHandle className={cn(!rightSidebarOpen && 'hidden')} />

      {/* Right: Tabs (Chat/Labels/Judge outputs) (collapsible) */}
      <ResizablePanel
        defaultSize={40}
        minSize={20}
        maxSize={50}
        className={cn('p-3 flex', !rightSidebarOpen && 'hidden')}
      >
        <Tabs
          value={selectedTab}
          onValueChange={(value) => {
            dispatch(setAgentRunSidebarTab(value));
            try {
              window.localStorage.setItem(
                'docent-agent-run-sidebar-tab',
                value
              );
            } catch (error) {
              console.warn(
                'Failed to persist agent run sidebar tab state',
                error
              );
            }
          }}
          className="size-full flex flex-col"
        >
          <TabsList className="grid w-full grid-cols-3 h-8">
            <TabsTrigger value="chat" className="text-xs">
              Chat
            </TabsTrigger>
            <TabsTrigger value="labels" className="text-xs">
              Labels
            </TabsTrigger>
            <TabsTrigger value="judge_outputs" className="text-xs">
              Judge outputs
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

          <TabsContent value="judge_outputs" className="flex-1 mt-0 min-h-0">
            <div className="h-full pt-2 flex flex-col min-h-0">
              <AgentRunJudgeOutputs
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
