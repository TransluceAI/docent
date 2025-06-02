'use client';

import { useParams, useSearchParams } from 'next/navigation';
import React, { Suspense, useEffect, useRef, useCallback } from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { getCurAgentRun, getAltAgentRun } from '@/app/store/transcriptSlice';

import TranscriptViewer, {
  TranscriptViewerHandle,
} from '@/app/dashboard/[eval_id]/transcript/components/TranscriptViewer';
import DiffPanel from './components/DiffPanel';

const SCROLL_DELAY = 250;

export default function AgentRunPage2() {
  const dispatch = useAppDispatch();

  const frameGridId = useAppSelector((state) => state.frame.frameGridId);
  const curAgentRun = useAppSelector((state) => state.transcript.curAgentRun);
  const altAgentRun = useAppSelector((state) => state.transcript.altAgentRun);

  const params = useParams();
  const searchParams = useSearchParams();
  const agentRunIdRaw = params.concat_run_id;
  const blockIdParam1 = searchParams.get('block_id');
  const blockIdParam2 = searchParams.get('block_id_2');
  const blockId1 = blockIdParam1 ? parseInt(blockIdParam1, 10) : undefined;
  const blockId2 = blockIdParam2 ? parseInt(blockIdParam2, 10) : undefined;

  const agentRunIds = React.useMemo(() => {
    return (Array.isArray(agentRunIdRaw) ? agentRunIdRaw[0] : agentRunIdRaw).split('___');
  }, [agentRunIdRaw]);

  /**
   * Handle scrolling to the block
   */

  const transcriptViewerRef = useRef<TranscriptViewerHandle>(null);
  const altTranscriptViewerRef = useRef<TranscriptViewerHandle>(null);

  const alreadyScrolledRef1 = useRef(false);
  const alreadyScrolledRef2 = useRef(false);
  const hasInitAttributeDimId = useAppSelector(
    (state) => state.frame.hasInitSearchQuery
  );
  const attributeMap = useAppSelector(
    (state) => state.search.searchResultMap
  );
  useEffect(() => {
    if (alreadyScrolledRef1.current) return;

    // We wait until hasInitAttributeDimId is known before continuing
    if (hasInitAttributeDimId === undefined) return;
    // If there is an initial attributeDimId, then we wait until the attributes have populated
    if (hasInitAttributeDimId === true && !attributeMap) return;
    // Else, if it's false, then we don't need to wait

    if (
      transcriptViewerRef.current &&
      curAgentRun?.id === agentRunIds[0] &&
      blockId1
    ) {
      alreadyScrolledRef1.current = true;
      setTimeout(() => {
        console.log('Scrolling to block', blockId1);
        transcriptViewerRef.current?.scrollToBlock(blockId1);
      }, 100); // Small delay to allow for DOM rendering
    }
  }, [curAgentRun, blockId1, agentRunIds, hasInitAttributeDimId, attributeMap]);

  useEffect(() => {
    if (alreadyScrolledRef2.current) return;

    // We wait until hasInitAttributeDimId is known before continuing
    if (hasInitAttributeDimId === undefined) return;
    // If there is an initial attributeDimId, then we wait until the attributes have populated
    if (hasInitAttributeDimId === true && !attributeMap) return;
    // Else, if it's false, then we don't need to wait

    if (
      altTranscriptViewerRef.current &&
      altAgentRun?.id === agentRunIds[1] &&
      blockId2
    ) {
      alreadyScrolledRef2.current = true;
      setTimeout(() => {
        console.log('Scrolling to block', blockId2);
        altTranscriptViewerRef.current?.scrollToBlock(blockId2);
      }, 100); // Small delay to allow for DOM rendering
    }
  }, [curAgentRun, blockId2, agentRunIds, hasInitAttributeDimId, attributeMap]);

  /**
   * Fetch agent run once
   */

  const fetchRef = useRef(false);
  useEffect(() => {
    if (fetchRef.current || frameGridId === undefined) return;
    if (curAgentRun?.id !== agentRunIds[0] || altAgentRun?.id !== agentRunIds[1]) {
      dispatch(getCurAgentRun(agentRunIds[0]));
      dispatch(getAltAgentRun(agentRunIds[1]));
      fetchRef.current = true;
    }
  }, [frameGridId, agentRunIds, blockId1, blockId2, dispatch, curAgentRun?.id, altAgentRun?.id]);

  const handleShowAgentRun = (agentRunId: string, blockId?: number) => {
    if (agentRunId !== curAgentRun?.id) {
      dispatch(getCurAgentRun(agentRunId));
    }

    if (blockId) {
      setTimeout(() => {
        transcriptViewerRef.current?.scrollToBlock(blockId);
      }, SCROLL_DELAY); // Small delay to allow the transcript to load before scrolling
    }
  };

  // Create a unified scroll function for the DiffPanel that can handle both transcripts
  const handleDiffScrollToBlock = useCallback((blockIndex: number, transcriptIdx?: number) => {
    if (transcriptIdx === 0 && transcriptViewerRef.current) {
      transcriptViewerRef.current.scrollToBlock(blockIndex);
    } else if (transcriptIdx === 1 && altTranscriptViewerRef.current) {
      altTranscriptViewerRef.current.scrollToBlock(blockIndex);
    } else {
      // If no transcriptIdx provided, try to scroll the first transcript
      transcriptViewerRef.current?.scrollToBlock(blockIndex);
    }
  }, []);

  return (
    <Suspense fallback={<div>Loading...</div>}>
      <div className="flex-1 flex space-x-3 min-h-0">
        <TranscriptViewer 
          ref={transcriptViewerRef} 
          secondary={false} 
          otherTranscriptRef={altTranscriptViewerRef}
        />
        <TranscriptViewer 
          ref={altTranscriptViewerRef} 
          secondary={true} 
          otherTranscriptRef={transcriptViewerRef}
        />
        <DiffPanel 
          agentRunIds={[agentRunIds[0], agentRunIds[1]]}
          scrollToBlock={handleDiffScrollToBlock}
        />
      </div>
    </Suspense>
  );
}
