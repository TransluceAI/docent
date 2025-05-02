'use client';

import { useEffect, useState } from 'react';
import { useAppDispatch, useAppSelector } from './store/hooks';
import {
  fetchEvalIds,
  fetchFrameGrids,
  resetFrameSlice,
  setEvalId,
} from './store/frameSlice';
import { FrameGridsTable } from './components/FrameGridsTable';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Loader2, PlusIcon } from 'lucide-react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { resetExperimentViewerSlice } from './store/experimentViewerSlice';
import { resetAttributeFinderSlice } from './store/attributeFinderSlice';
import { resetTranscriptSlice } from './store/transcriptSlice';
import socketService from './services/socketService';

const DocentDashboard = () => {
  const evalId = useAppSelector((state) => state.frame.evalId);
  const frameGrids = useAppSelector((state) => state.frame.frameGrids);
  const isLoadingFrameGrids = useAppSelector(
    (state) => state.frame.isLoadingFrameGrids
  );
  const dispatch = useAppDispatch();

  useEffect(() => {
    // Fetch data when component mounts
    dispatch(fetchFrameGrids());
    dispatch(fetchEvalIds());

    // Clear out old state
    socketService.closeSocket();
    dispatch(resetFrameSlice());
    dispatch(resetExperimentViewerSlice());
    dispatch(resetAttributeFinderSlice());
    dispatch(resetTranscriptSlice());
  }, [dispatch, evalId]);

  return (
    <ScrollArea className="h-screen">
      <div className="container mx-auto py-4 px-3 max-w-screen-xl">
        {/* Header Section */}
        <div className="space-y-1 mb-4">
          <div className="flex justify-between items-center">
            <div>
              <div className="text-lg font-semibold tracking-tight">
                Docent Dashboard
              </div>
              <div className="text-xs text-gray-500">
                Create a new FrameGrid for each benchmark or set of experiments.
              </div>
            </div>
            <Button className="flex items-center gap-1" size="sm">
              <PlusIcon className="h-3.5 w-3.5" />
              Create New Frame Grid
            </Button>
          </div>
        </div>

        <Separator className="my-4" />

        {/* Table area */}
        <FrameGridsTable
          frameGrids={frameGrids || []}
          isLoading={isLoadingFrameGrids}
        />
      </div>
    </ScrollArea>
  );
};

export default DocentDashboard;
