'use client';

import React, { Suspense, useEffect, useRef } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import TranscriptView from '../components/TranscriptView';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { getCurDatapoint } from '@/app/store/transcriptSlice';

const SCROLL_DELAY = 250;

function DatapointPageContent() {
  const dispatch = useAppDispatch();

  const frameGridId = useAppSelector((state) => state.frame.frameGridId);
  const curDatapoint = useAppSelector((state) => state.transcript.curDatapoint);

  const params = useParams();
  const searchParams = useSearchParams();
  const datapointIdRaw = params.datapoint_id;
  const blockIdParam = searchParams.get('block_id');
  const blockId = blockIdParam ? parseInt(blockIdParam, 10) : undefined;

  const datapointId = React.useMemo(() => {
    return Array.isArray(datapointIdRaw) ? datapointIdRaw[0] : datapointIdRaw;
  }, [datapointIdRaw]);

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
  }, [curDatapoint, blockId, datapointId]);

  // Get datapoint once
  const fetchRef = useRef(false);

  useEffect(() => {
    if (fetchRef.current || frameGridId === undefined) return;

    if (curDatapoint?.id !== datapointId) {
      fetchRef.current = true;
      dispatch(getCurDatapoint(datapointId));
    }
  }, [frameGridId, datapointId, blockId, dispatch, curDatapoint?.id]);

  const handleShowDatapoint = (datapointId: string, blockId?: number) => {
    if (datapointId !== curDatapoint?.id) {
      dispatch(getCurDatapoint(datapointId));
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
        datapoint={curDatapoint || null}
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
