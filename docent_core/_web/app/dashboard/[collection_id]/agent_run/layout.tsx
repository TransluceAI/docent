'use client';

import React from 'react';
import { useParams } from 'next/navigation';

import { useAppSelector } from '../../../store/hooks';
import { cn } from '@/lib/utils';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';

import ExperimentViewer from '../../../components/ExperimentViewer';

export default function AgentRunLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const agentRunId = params.agent_run_id as string | undefined;

  const leftSidebarOpen = useAppSelector(
    (state) => state.transcript.agentRunLeftSidebarOpen
  );

  // Always render the same component tree structure to prevent ExperimentViewer
  // from unmounting/remounting when navigating between routes. Use CSS to hide
  // panels instead of conditional rendering.
  return (
    <ResizablePanelGroup
      direction="horizontal"
      autoSaveId="agent-run-layout"
      className="flex-1 flex bg-card min-h-0 shrink-0 border rounded-lg"
    >
      {/* Left panel - ExperimentViewer */}
      <ResizablePanel
        defaultSize={25}
        minSize={15}
        maxSize={agentRunId ? 40 : 100}
        className={cn('flex p-3', agentRunId && !leftSidebarOpen && 'hidden')}
      >
        <ExperimentViewer activeRunId={agentRunId} />
      </ResizablePanel>

      <ResizableHandle
        className={cn(
          !agentRunId && 'hidden',
          agentRunId && !leftSidebarOpen && 'hidden'
        )}
      />

      {/* Right panel - always in DOM, hidden when no agent run */}
      <ResizablePanel
        defaultSize={75}
        minSize={50}
        className={cn('flex min-h-0', !agentRunId && 'hidden')}
      >
        {children}
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}
