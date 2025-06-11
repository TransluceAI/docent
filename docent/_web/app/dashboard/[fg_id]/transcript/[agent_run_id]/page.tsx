'use client';

import { useParams, useSearchParams } from 'next/navigation';
import React, { Suspense, useEffect, useRef } from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { getCurAgentRun } from '@/app/store/transcriptSlice';
import { Card } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import AgentSummary from '../components/AgentSummary';
import TaPanel from '../components/TaPanel';
import TaskSummary from '../components/TaskSummary';
import TranscriptViewer, {
  TranscriptViewerHandle,
} from '../components/TranscriptViewer';

const SCROLL_DELAY = 250;

export default function AgentRunPage() {
  const dispatch = useAppDispatch();

  const frameGridId = useAppSelector((state) => state.frame.frameGridId);
  const curAgentRun = useAppSelector((state) => state.transcript.curAgentRun);

  const params = useParams();
  const searchParams = useSearchParams();
  const agentRunIdRaw = params.agent_run_id;
  const blockIdParam = searchParams.get('block_id');
  const blockId = blockIdParam ? parseInt(blockIdParam, 10) : undefined;

  const agentRunId = React.useMemo(() => {
    return Array.isArray(agentRunIdRaw) ? agentRunIdRaw[0] : agentRunIdRaw;
  }, [agentRunIdRaw]);

  /**
   * Handle scrolling to the block
   */

  const transcriptViewerRef = useRef<TranscriptViewerHandle>(null);

  const alreadyScrolledRef = useRef(false);
  const hasInitSearchQuery = useAppSelector(
    (state) => state.frame.hasInitSearchQuery
  );
  const searchResultMap = useAppSelector(
    (state) => state.search.searchResultMap
  );
  useEffect(() => {
    if (alreadyScrolledRef.current) return;

    // We wait until hasInitSearchQuery is known before continuing
    if (hasInitSearchQuery === undefined) return;
    // If there is an initial search query, then we wait until the search has populated
    if (hasInitSearchQuery === true && !searchResultMap) return;
    // Else, if it's false, then we don't need to wait

    if (
      transcriptViewerRef.current &&
      curAgentRun?.id === agentRunId &&
      blockId
    ) {
      alreadyScrolledRef.current = true;
      setTimeout(() => {
        console.log('Scrolling to block', blockId);
        transcriptViewerRef.current?.scrollToBlock(blockId);
      }, 100); // Small delay to allow for DOM rendering
    }
  }, [curAgentRun, blockId, agentRunId, hasInitSearchQuery, searchResultMap]);

  /**
   * Fetch agent run once
   */

  const fetchRef = useRef(false);
  useEffect(() => {
    if (fetchRef.current || frameGridId === undefined) return;
    if (curAgentRun?.id !== agentRunId) {
      dispatch(getCurAgentRun(agentRunId));
      fetchRef.current = true;
    }
  }, [frameGridId, agentRunId, blockId, dispatch, curAgentRun?.id]);

  const onShowAgentRun = (agentRunId: string, blockId?: number) => {
    if (agentRunId !== curAgentRun?.id) {
      dispatch(getCurAgentRun(agentRunId));
    }

    if (blockId) {
      setTimeout(() => {
        transcriptViewerRef.current?.scrollToBlock(blockId);
      }, SCROLL_DELAY); // Small delay to allow the transcript to load before scrolling
    }
  };

  return (
    <Suspense>
      <div className="flex-1 flex space-x-3 min-h-0">
        <TranscriptViewer ref={transcriptViewerRef} secondary={false} />

        <Card className="h-full overflow-y-auto flex-1 p-3">
          <Tabs defaultValue="agent" className="h-full flex flex-col">
            <TabsList className="grid w-full grid-cols-3 h-8">
              <TabsTrigger value="agent" className="text-xs">
                Agent Summary
              </TabsTrigger>
              <TabsTrigger value="task" className="text-xs">
                Task Summary
              </TabsTrigger>
              <TabsTrigger value="chat" className="text-xs">
                Chat
              </TabsTrigger>
            </TabsList>

            <TabsContent value="task" className="flex-1 mt-0">
              <ScrollArea className="h-full px-1 py-2">
                <TaskSummary />
              </ScrollArea>
            </TabsContent>

            <TabsContent value="agent" className="flex-1 mt-0">
              <ScrollArea className="h-full px-1 py-2">
                <AgentSummary onCitationClick={onShowAgentRun} />
              </ScrollArea>
            </TabsContent>

            <TabsContent value="chat" className="flex-1 mt-0">
              <div className="h-full px-1 py-2">
                <TaPanel onShowAgentRun={onShowAgentRun} />
              </div>
            </TabsContent>
          </Tabs>
        </Card>
      </div>
    </Suspense>
  );
}
