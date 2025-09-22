'use client';

import React, { Suspense, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
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

  return (
    <div className="flex-1 flex space-x-3 min-h-0 shrink-0">
      {/* Left: SingleRubricArea (collapsible) */}
      {leftSidebarOpen && (
        <Card className="flex min-w-0 basis-1/3 max-w-1/3 grow-0 shrink-0">
          <SingleRubricArea rubricId={rubricId} sessionId={sessionId} />
        </Card>
      )}

      {/* Middle area: only when on a result */}
      {isOnResultRoute && (
        <div className="flex-1 min-w-0 min-h-0">{children}</div>
      )}

      {/* Right tabs area (collapsible via AgentRunViewer toggle) */}
      {rightSidebarOpen && (
        <motion.div
          layout
          transition={{ type: 'tween', duration: 0.25 }}
          className={
            isOnResultRoute
              ? 'flex min-w-[260px] max-w-sm basis-1/4 grow-0 shrink-0'
              : 'flex flex-1 min-w-0 min-h-0'
          }
        >
          <Card className="flex-1 min-w-0 min-h-0 p-2">
            <Tabs
              defaultValue={activeTab}
              value={activeTab}
              onValueChange={(value) =>
                setActiveTab(value as 'refine' | 'analyze' | 'label')
              }
              className={`flex flex-col h-full `}
            >
              {isOnResultRoute && (
                <TabsList className="grid grid-cols-3 justify-start w-full mb-2">
                  <TabsTrigger value="refine">Refine</TabsTrigger>
                  <TabsTrigger value="analyze" disabled={!isOnResultRoute}>
                    Analyze
                  </TabsTrigger>
                  <TabsTrigger value="label" disabled={!isOnResultRoute}>
                    Label
                  </TabsTrigger>
                </TabsList>
              )}

              <TabsContent value="refine" className="flex-1 min-h-0">
                <RefinementChat
                  collectionId={collectionId}
                  sessionId={sessionId}
                  rubricId={rubricId}
                  isOnResultRoute={isOnResultRoute}
                />
              </TabsContent>

              <TabsContent value="analyze" className="flex-1 min-h-0">
                {isOnResultRoute && currentResult && (
                  <TranscriptChat
                    runId={currentResult.agent_run_id}
                    collectionId={collectionId}
                    judgeResult={currentResult}
                    resultContext={{ rubricId, resultId: currentResult.id }}
                    className="flex flex-col min-w-0 h-full"
                  />
                )}
              </TabsContent>
              <TabsContent value="label" className="flex-1 min-h-0">
                {isOnResultRoute && currentResult ? (
                  <LabelArea
                    result={currentResult}
                    collectionId={collectionId}
                    rubricId={rubricId}
                  />
                ) : (
                  <div className="text-xs text-muted-foreground p-2">
                    Open a result to edit labels.
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </Card>
        </motion.div>
      )}
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
