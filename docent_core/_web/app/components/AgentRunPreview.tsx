import React, { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '../../components/ui/button';
import { X, Maximize2 } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { clearDashboardAgentRunView } from '../store/transcriptSlice';
import { navToAgentRun } from '../../lib/nav';
import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../dashboard/[collection_id]/agent_run/components/AgentRunViewer';

export default function AgentRunPreview() {
  const dispatch = useAppDispatch();
  const router = useRouter();
  const dashboardHasRunPreview = useAppSelector(
    (state) => state.transcript.dashboardHasRunPreview
  );
  const dashboardScrollToBlockIdx = useAppSelector(
    (state) => state.transcript.dashboardScrollToBlockIdx
  );
  const dashboardScrollToTranscriptIdx = useAppSelector(
    (state) => state.transcript.dashboardScrollToTranscriptIdx
  );
  const curAgentRun = useAppSelector((state) => state.transcript.curAgentRun);
  const collectionId = useAppSelector((state) => state.collection.collectionId);

  const agentRunViewerRef = useRef<AgentRunViewerHandle>(null);

  // Handle scrolling to the block when the agent run view is opened
  useEffect(() => {
    if (
      dashboardHasRunPreview &&
      agentRunViewerRef.current &&
      curAgentRun &&
      dashboardScrollToBlockIdx !== undefined
    ) {
      const timeoutId = setTimeout(() => {
        agentRunViewerRef.current?.scrollToBlock(
          dashboardScrollToBlockIdx,
          dashboardScrollToTranscriptIdx || 0,
          0
        );
      }, 100); // Small delay to allow for DOM rendering

      return () => {
        clearTimeout(timeoutId);
      };
    }
  }, [
    dashboardHasRunPreview,
    curAgentRun,
    dashboardScrollToBlockIdx,
    dashboardScrollToTranscriptIdx,
  ]);

  const handleCloseDashboardAgentRunView = () => {
    dispatch(clearDashboardAgentRunView());
  };

  const handleOpenInNewTab = () => {
    if (curAgentRun && collectionId) {
      navToAgentRun(
        router,
        window,
        curAgentRun.id,
        dashboardScrollToTranscriptIdx,
        dashboardScrollToBlockIdx,
        collectionId,
        undefined,
        false
      );
    }
  };

  if (!dashboardHasRunPreview) {
    return null;
  }

  return (
    <div className="flex-1 flex flex-col space-y-3 min-h-0 max-h-screen overflow-hidden">
      {/* Header with close button */}
      <div className="flex px-3 py-2 border bg-muted rounded-lg items-center justify-between flex-shrink-0">
        <div className="text-sm font-medium text-muted-foreground">
          Agent Run Preview
        </div>

        <div className="flex items-center gap-1">
          {/* <Button size="sm">
              Add to query
          </Button> */}
          <Button
            variant="ghost"
            size="sm"
            onClick={handleOpenInNewTab}
            className="h-8 w-8 p-0 hover:bg-primary/10"
            title="Open in new tab"
          >
            <Maximize2 className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCloseDashboardAgentRunView}
            className="h-8 w-8 p-0 hover:bg-primary/10"
            title="Close preview"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        <AgentRunViewer ref={agentRunViewerRef} secondary={false} />
      </div>
    </div>
  );
}
