'use client';

import { useParams, useSearchParams } from 'next/navigation';
import React, { Suspense, useEffect, useRef } from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  getCurAgentRun,
  setAgentRunSidebarTab,
} from '@/app/store/transcriptSlice';
import { Card } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import AgentSummary from '../components/AgentSummary';
import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../components/AgentRunViewer';
import TranscriptChat from '@/components/TranscriptChat';

export default function AgentRunPage() {
  const dispatch = useAppDispatch();

  const collectionId = useAppSelector(
    (state) => state.collection?.collectionId
  );
  const curAgentRun = useAppSelector((state) => state.transcript?.curAgentRun);
  const hasInitSearchQuery = useAppSelector(
    (state) => state.collection?.hasInitSearchQuery
  );
  const rightSidebarOpen = useAppSelector(
    (state) => state.transcript?.rightSidebarOpen ?? true
  );
  const selectedTab = useAppSelector(
    (state) => state.transcript?.agentRunSidebarTab ?? 'chat'
  );

  const params = useParams();
  const searchParams = useSearchParams();
  const agentRunIdRaw = params.agent_run_id;
  const blockIdxParam = searchParams.get('block_idx');
  const blockIdx = blockIdxParam ? parseInt(blockIdxParam, 10) : undefined;
  const transcriptIdxParam = searchParams.get('transcript_idx');
  const transcriptIdx = transcriptIdxParam
    ? parseInt(transcriptIdxParam, 10)
    : undefined;

  const agentRunId = React.useMemo(() => {
    return Array.isArray(agentRunIdRaw) ? agentRunIdRaw[0] : agentRunIdRaw;
  }, [agentRunIdRaw]);

  const agentRunViewerRef = useRef<AgentRunViewerHandle>(null);

  useEffect(() => {
    if (!collectionId || !agentRunId) {
      return;
    }

    if (curAgentRun?.id === agentRunId) {
      return;
    }

    dispatch(getCurAgentRun(agentRunId));
  }, [collectionId, agentRunId, dispatch]);

  const alreadyScrolledRef = useRef(false);

  useEffect(() => {
    alreadyScrolledRef.current = false;
  }, [agentRunId]);

  useEffect(() => {
    if (alreadyScrolledRef.current) return;

    if (!curAgentRun || curAgentRun.id !== agentRunId) {
      return;
    }

    if (hasInitSearchQuery === undefined) return;
    if (hasInitSearchQuery === true) return;

    if (blockIdx !== undefined && agentRunViewerRef.current) {
      alreadyScrolledRef.current = true;
      setTimeout(() => {
        agentRunViewerRef.current?.scrollToBlock(
          blockIdx,
          transcriptIdx || 0,
          0,
          undefined
        );
      }, 100);
    }
  }, [curAgentRun, agentRunId, blockIdx, transcriptIdx, hasInitSearchQuery]);

  const onShowAgentRun = (
    agentRunId: string,
    blockIdx?: number,
    transcriptIdx?: number,
    highlightDuration?: number
  ) => {
    if (agentRunId !== curAgentRun?.id) {
      dispatch(getCurAgentRun(agentRunId));
    }

    if (blockIdx !== undefined) {
      agentRunViewerRef.current?.scrollToBlock(
        blockIdx,
        transcriptIdx || 0,
        0,
        highlightDuration
      );
    }
  };

  return (
    <Suspense>
      {/* Transcript */}
      <AgentRunViewer ref={agentRunViewerRef} secondary={false} />

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
                <AgentSummary onCitationClick={onShowAgentRun} />
              </ScrollArea>
            </TabsContent>

            <TabsContent value="chat" className="flex-1 mt-0 min-h-0">
              <div className="h-full pt-2 flex flex-col min-h-0">
                <TranscriptChat
                  runId={agentRunId}
                  collectionId={collectionId}
                  title="Transcript Chat"
                  className="flex-1 flex flex-col min-w-0 min-h-0"
                  onNavigateToCitation={({ citation }) => {
                    if (onShowAgentRun && citation.block_idx !== undefined) {
                      onShowAgentRun(
                        agentRunId,
                        citation.block_idx,
                        citation.transcript_idx || 0,
                        500
                      );
                    }
                  }}
                />
              </div>
            </TabsContent>
          </Tabs>
        </Card>
      )}
    </Suspense>
  );
}
