'use client';

import React, { Suspense, useEffect, useRef } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import TranscriptView from '../components/TranscriptView';
import { useFrameGrid } from '../../../contexts/FrameGridContext';

const SCROLL_DELAY = 250;

function DatapointPageContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const datapointId = params.datapoint_id;
  const blockIdParam = searchParams.get('block_id');
  const blockId = blockIdParam ? parseInt(blockIdParam, 10) : undefined;

  const {
    sendMessage,
    curDatapoint,
    onClearDatapoint,
    actionsSummary,
    solutionSummary,
    socketReady,
  } = useFrameGrid();

  const transcriptViewerRef = useRef<{
    scrollToBlock: (blockIndex: number) => void;
  }>(null);

  // Scroll to block once datapoint is loaded
  const alreadyScrolledRef = useRef(false);
  useEffect(() => {
    if (alreadyScrolledRef.current) return;
    if (
      transcriptViewerRef.current &&
      curDatapoint?.id === datapointId &&
      blockId
    ) {
      setTimeout(() => {
        console.log('Scrolling to block', blockId);
        transcriptViewerRef.current?.scrollToBlock(blockId);
        alreadyScrolledRef.current = true;
      }, 100); // Small delay to allow for DOM rendering
    }
  }, [
    transcriptViewerRef.current,
    alreadyScrolledRef.current,
    curDatapoint,
    blockId,
  ]);

  // Get datapoint once
  const fetchRef = useRef(false);

  useEffect(() => {
    if (fetchRef.current) return;

    if (curDatapoint?.id !== datapointId && socketReady) {
      fetchRef.current = true;
      onClearDatapoint();
      sendMessage('get_datapoint', {
        datapoint_id: datapointId,
      });
    }
  }, [datapointId, blockId, socketReady]);

  const handleShowDatapoint = (datapointId: string, blockId?: number) => {
    if (datapointId !== curDatapoint?.id) {
      onClearDatapoint();
      sendMessage('get_datapoint', {
        datapoint_id: datapointId,
      });
    }

    if (blockId) {
      setTimeout(() => {
        transcriptViewerRef.current?.scrollToBlock(blockId);
      }, SCROLL_DELAY); // Small delay to allow the transcript to load before scrolling
    }
  };

  return (
    <div className="flex-1 flex space-x-4 min-h-0">
      <TranscriptView
        datapoint={curDatapoint}
        actionsSummary={actionsSummary}
        solutionSummary={solutionSummary}
        transcriptViewerRef={transcriptViewerRef}
        onShowDatapoint={handleShowDatapoint}
      />
    </div>
  );
}

export default function DatapointPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <DatapointPageContent />
    </Suspense>
  );
}
