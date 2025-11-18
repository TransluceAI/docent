'use client';

import React, { Suspense, useEffect, useState, useRef } from 'react';
import { useParams } from 'next/navigation';
import SingleRubricArea from '../../components/SingleRubricArea';
import { ResultFilterControlsProvider } from '@/providers/use-result-filters';
import { RubricVersionProvider } from '@/providers/use-rubric-version';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import RefinementChat from './components/RefinementChat';
import TranscriptChat from '@/components/TranscriptChat';
import { CitationNavigationProvider } from '@/providers/CitationNavigationProvider';
import { useGetRubricRunStateQuery } from '@/app/api/rubricApi';
import { useCreateOrGetRefinementSessionMutation } from '@/app/api/refinementApi';
import { useRubricVersion } from '@/providers/use-rubric-version';
import {
  RefinementTabProvider,
  useRefinementTab,
} from '@/providers/use-refinement-tab';
import { TextSelectionProvider } from '@/providers/use-text-selection';
import { useAppSelector } from '@/app/store/hooks';
import { useLabelSets } from '@/providers/use-label-sets';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import type { ImperativePanelHandle } from 'react-resizable-panels';
import { cn } from '@/lib/utils';

interface RubricLayoutBodyProps {
  collectionId: string;
  rubricId: string;
  children: React.ReactNode;
}

function RubricLayoutBody({
  collectionId,
  rubricId,
  children,
}: RubricLayoutBodyProps) {
  const { agent_run_id: agentRunId, result_id: resultId } = useParams<{
    agent_run_id?: string;
    result_id?: string;
  }>();
  const isOnResultRoute = !!resultId || !!agentRunId;

  const { version } = useRubricVersion();
  const { activeLabelSet } = useLabelSets(rubricId);
  const { data: rubricRunState } = useGetRubricRunStateQuery(
    {
      collectionId,
      rubricId,
      version: version ?? null,
      labelSetId: activeLabelSet?.id ?? null,
    },
    { skip: !isOnResultRoute }
  );

  // Find the agent_run group that contains the current result
  const currentAgentRunGroup = isOnResultRoute
    ? rubricRunState?.results?.find((arr) => arr.agent_run_id === agentRunId)
    : null;

  const { activeTab, setActiveTab } = useRefinementTab();

  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [createOrGetRefinementSession] =
    useCreateOrGetRefinementSessionMutation();

  useEffect(() => {
    let mounted = true;
    if (!collectionId || !rubricId) return;
    // Default to a 'guided' session when landing on a rubric page
    // so the refinement panel can read initial data.
    createOrGetRefinementSession({
      collectionId,
      rubricId,
      sessionType: 'guided',
    })
      .unwrap()
      .then((res) => {
        if (mounted) setSessionId(res.id);
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, [collectionId, rubricId, createOrGetRefinementSession]);

  // Set the active tab based on the route
  useEffect(() => {
    if (isOnResultRoute) {
      setActiveTab('analyze');
    } else {
      setActiveTab('refine');
    }
  }, [isOnResultRoute]);

  // Keyboard shortcuts:
  // - Cmd/Ctrl + U to open Refine tab and focus input
  // - Cmd/Ctrl + J to open Analyze tab (when available)
  useEffect(() => {
    const focusChatInput = () => {
      try {
        window.dispatchEvent(new CustomEvent('focus-chat-input'));
      } catch {
        console.error('Failed to focus refinement input');
      }
    };

    const handler = (e: KeyboardEvent) => {
      const isModifier = e.metaKey || e.ctrlKey;
      if (isModifier && (e.key === 'j' || e.key === 'J')) {
        e.preventDefault();
        setActiveTab('refine');
        focusChatInput();
      } else if (isModifier && (e.key === 'k' || e.key === 'K')) {
        // Open the Analyze tab if a result is available
        if (isOnResultRoute) {
          e.preventDefault();
          setActiveTab('analyze');
          focusChatInput();
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [setActiveTab, isOnResultRoute]);

  const leftSidebarOpen = useAppSelector(
    (state) => state.transcript.judgeLeftSidebarOpen
  );
  const rightSidebarOpen = useAppSelector(
    (state) => state.transcript.judgeRightSidebarOpen
  );

  const rightSizePanelRef = useRef<ImperativePanelHandle>(null);
  const leftPanelRef = useRef<ImperativePanelHandle>(null);
  const middlePanelRef = useRef<ImperativePanelHandle>(null);

  // Resize the panels when changing from the rubric --> a result route and back
  useEffect(() => {
    const leftPanelSize = 35;
    const middlePanelSize = isOnResultRoute ? 40 : 0;
    const rightPanelSize = isOnResultRoute ? 25 : 65;

    leftPanelRef.current?.resize(leftPanelSize);
    rightSizePanelRef.current?.resize(rightPanelSize);
    middlePanelRef.current?.resize(middlePanelSize);
  }, [isOnResultRoute]);

  return (
    <ResizablePanelGroup
      direction="horizontal"
      className="flex-1 flex bg-card space-x-3 min-h-0 shrink-0 border rounded-lg"
    >
      {/* Left: SingleRubricArea (collapsible) */}
      <ResizablePanel
        ref={leftPanelRef}
        defaultSize={35}
        minSize={20}
        maxSize={50}
        className={cn(
          'flex p-3',
          !leftSidebarOpen && isOnResultRoute && 'hidden'
        )}
      >
        <ResultFilterControlsProvider
          collectionId={collectionId}
          rubricId={rubricId}
        >
          <SingleRubricArea rubricId={rubricId} sessionId={sessionId} />
        </ResultFilterControlsProvider>
      </ResizablePanel>

      <ResizableHandle
        className={cn(
          '!mx-0 !px-0',
          !leftSidebarOpen && isOnResultRoute && 'hidden'
        )}
      />

      {/* Middle area: only when on a result */}
      {
        <ResizablePanel
          ref={middlePanelRef}
          defaultSize={isOnResultRoute ? 40 : 0}
          minSize={isOnResultRoute ? 30 : 0}
          maxSize={70}
          // NOTE(cadentj): ResizablePanel has some weird default margin-x that we need to override
          className="flex-1 min-w-0 min-h-0 p-3 !mx-0"
        >
          {children}
        </ResizablePanel>
      }

      <ResizableHandle
        className={cn(
          (!isOnResultRoute || !rightSidebarOpen) && 'hidden',
          '!mx-0 !px-0'
        )}
      />

      {/* Right tabs area (collapsible via AgentRunViewer toggle) */}
      <ResizablePanel
        ref={rightSizePanelRef}
        defaultSize={isOnResultRoute ? 25 : 65}
        minSize={isOnResultRoute ? 20 : 30}
        maxSize={isOnResultRoute ? 40 : 70}
        className={cn(
          'p-3 flex !mx-0 min-w-0',
          !rightSidebarOpen && isOnResultRoute && 'hidden'
        )}
      >
        <Tabs
          defaultValue={activeTab}
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as 'refine' | 'analyze')}
          className="flex flex-col size-full"
        >
          {isOnResultRoute && (
            <TabsList className="grid grid-cols-2 w-full mb-2">
              <TabsTrigger value="refine">Refine</TabsTrigger>
              <TabsTrigger value="analyze" disabled={!isOnResultRoute}>
                Analyze
              </TabsTrigger>
            </TabsList>
          )}

          <TabsContent value="refine" className="flex-1 min-h-0">
            <RefinementChat
              sessionId={sessionId}
              isOnResultRoute={isOnResultRoute}
            />
          </TabsContent>

          <TabsContent value="analyze" className="flex-1 min-h-0">
            {isOnResultRoute && agentRunId && (
              <TranscriptChat
                agentRunId={agentRunId}
                rubricId={rubricId}
                collectionId={collectionId}
                agentRunResults={currentAgentRunGroup}
                selectedResultId={resultId}
                showEmptyResultMessage={!currentAgentRunGroup}
                className="flex flex-col min-w-0 h-full"
              />
            )}
          </TabsContent>
        </Tabs>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}

export default function RubricLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { collection_id: collectionId, rubric_id: rubricId } = useParams<{
    collection_id: string;
    rubric_id: string;
  }>();

  return (
    <Suspense>
      <CitationNavigationProvider>
        <RubricVersionProvider rubricId={rubricId} collectionId={collectionId}>
          <RefinementTabProvider
            collectionId={collectionId}
            rubricId={rubricId}
          >
            <TextSelectionProvider>
              <RubricLayoutBody collectionId={collectionId} rubricId={rubricId}>
                {children}
              </RubricLayoutBody>
            </TextSelectionProvider>
          </RefinementTabProvider>
        </RubricVersionProvider>
      </CitationNavigationProvider>
    </Suspense>
  );
}
