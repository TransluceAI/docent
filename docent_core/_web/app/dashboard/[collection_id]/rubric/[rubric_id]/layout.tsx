'use client';

import React, { Suspense, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import SingleRubricArea from '../../components/SingleRubricArea';
import { CitationNavigationProvider } from './NavigateToCitationContext';
import { Card } from '@/components/ui/card';
import { ResultFilterControlsProvider } from '@/providers/use-result-filters';
import { RubricVersionProvider } from '@/providers/use-rubric-version';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import RefinementChat from './components/RefinementChat';
import TranscriptChat from '@/components/TranscriptChat';
import LabelArea from './result/[result_id]/components/LabelArea';
import { useGetRubricRunStateQuery } from '@/app/api/rubricApi';
import { useCreateOrGetRefinementSessionMutation } from '@/app/api/refinementApi';
import { useRubricVersion } from '@/providers/use-rubric-version';
import {
  RefinementTabProvider,
  useRefinementTab,
} from '@/providers/use-refinement-tab';
import { TextSelectionProvider } from '@/providers/use-text-selection';
import { useAppSelector } from '@/app/store/hooks';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';

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
  const { result_id: resultId } = useParams<{ result_id?: string }>();
  const isOnResultRoute = !!resultId;

  const { version } = useRubricVersion();
  const { data: rubricRunState } = useGetRubricRunStateQuery(
    {
      collectionId,
      rubricId,
      version: version ?? null,
    },
    { skip: !isOnResultRoute }
  );
  const currentResult = isOnResultRoute
    ? rubricRunState?.results?.find((r) => r.id === resultId)
    : null;

  const { activeTab, setActiveTab } = useRefinementTab();

  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [createOrGetRefinementSession] =
    useCreateOrGetRefinementSessionMutation();

  useEffect(() => {
    let mounted = true;
    if (!collectionId || !rubricId) return;
    // Default to an 'explore' session when landing on a rubric page
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
    (state) => state.transcript.rightSidebarOpen
  );
  const showLeftPanel = leftSidebarOpen;
  const showResultPanel = isOnResultRoute;
  const showRightPanel = rightSidebarOpen;
  const leftDefaultSize = showResultPanel
    ? showRightPanel
      ? 28
      : 34
    : showRightPanel
      ? 40
      : 100;
  const resultDefaultSize =
    showLeftPanel && showRightPanel
      ? 44
      : showLeftPanel || showRightPanel
        ? 66
        : 100;
  const rightDefaultSize = showResultPanel
    ? showLeftPanel
      ? 28
      : 34
    : showLeftPanel
      ? 60
      : 100;
  if (!showLeftPanel && !showResultPanel && !showRightPanel) {
    return <div className="flex-1 min-h-0 min-w-0" />;
  }

  return (
    <div className="flex-1 min-h-0 min-w-0 shrink-0 overflow-hidden">
      <ResizablePanelGroup
        autoSaveId={`docent-rubric-workspace-v1-${collectionId}`}
        direction="horizontal"
        id="rubric-workspace"
      >
        {showLeftPanel && (
          <React.Fragment key="rubric-definition">
            <ResizablePanel
              className="min-w-0 overflow-hidden"
              defaultSize={leftDefaultSize}
              id="rubric-definition"
              minSize={20}
              order={1}
            >
              <Card className="flex h-full min-h-0 min-w-0 overflow-hidden">
                <SingleRubricArea rubricId={rubricId} sessionId={sessionId} />
              </Card>
            </ResizablePanel>
            {(showResultPanel || showRightPanel) && (
              <ResizableHandle
                aria-label="Resize rubric definition panel"
                id="rubric-definition-handle"
                withHandle
              />
            )}
          </React.Fragment>
        )}

        {showResultPanel && (
          <React.Fragment key="rubric-result">
            <ResizablePanel
              className="min-w-0 overflow-hidden"
              defaultSize={resultDefaultSize}
              id="rubric-result"
              minSize={32}
              order={2}
            >
              <div className="h-full min-h-0 min-w-0 overflow-hidden">
                {children}
              </div>
            </ResizablePanel>
            {showRightPanel && (
              <ResizableHandle
                aria-label="Resize rubric result and assistant panels"
                id="rubric-result-handle"
                withHandle
              />
            )}
          </React.Fragment>
        )}

        {showRightPanel && (
          <ResizablePanel
            key="rubric-assistant"
            className="min-w-0 overflow-hidden"
            defaultSize={rightDefaultSize}
            id="rubric-assistant"
            minSize={22}
            order={3}
          >
            <Card className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden p-2">
              <Tabs
                defaultValue={activeTab}
                value={activeTab}
                onValueChange={(value) =>
                  setActiveTab(value as 'refine' | 'analyze' | 'label')
                }
                className="flex h-full min-h-0 flex-col"
              >
                {isOnResultRoute && (
                  <TabsList className="mb-2 grid w-full shrink-0 grid-cols-3 justify-start">
                    <TabsTrigger value="refine">Refine</TabsTrigger>
                    <TabsTrigger value="analyze" disabled={!isOnResultRoute}>
                      Analyze
                    </TabsTrigger>
                    <TabsTrigger value="label" disabled={!isOnResultRoute}>
                      Label
                    </TabsTrigger>
                  </TabsList>
                )}

                <TabsContent value="refine" className="min-h-0 flex-1">
                  <RefinementChat
                    collectionId={collectionId}
                    sessionId={sessionId}
                    rubricId={rubricId}
                    isOnResultRoute={isOnResultRoute}
                  />
                </TabsContent>

                <TabsContent value="analyze" className="min-h-0 flex-1">
                  {isOnResultRoute && currentResult && (
                    <TranscriptChat
                      runId={currentResult.agent_run_id}
                      collectionId={collectionId}
                      judgeResult={currentResult}
                      resultContext={{ rubricId, resultId: currentResult.id }}
                      className="flex h-full min-w-0 flex-col"
                    />
                  )}
                </TabsContent>
                <TabsContent value="label" className="min-h-0 flex-1">
                  {isOnResultRoute && currentResult ? (
                    <LabelArea
                      result={currentResult}
                      collectionId={collectionId}
                      rubricId={rubricId}
                    />
                  ) : (
                    <div className="p-2 text-xs text-muted-foreground">
                      Open a result to edit labels.
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            </Card>
          </ResizablePanel>
        )}
      </ResizablePanelGroup>
    </div>
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
        <ResultFilterControlsProvider
          rubricId={rubricId}
          collectionId={collectionId}
        >
          <RubricVersionProvider
            rubricId={rubricId}
            collectionId={collectionId}
          >
            <RefinementTabProvider
              collectionId={collectionId}
              rubricId={rubricId}
            >
              <TextSelectionProvider>
                <RubricLayoutBody
                  collectionId={collectionId}
                  rubricId={rubricId}
                >
                  {children}
                </RubricLayoutBody>
              </TextSelectionProvider>
            </RefinementTabProvider>
          </RubricVersionProvider>
        </ResultFilterControlsProvider>
      </CitationNavigationProvider>
    </Suspense>
  );
}
