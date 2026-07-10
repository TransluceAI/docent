'use client';

import React from 'react';

import ExperimentViewer from '../../../components/ExperimentViewer';
import { useParams } from 'next/navigation';
import { useAppSelector } from '@/app/store/hooks';
import { CitationNavigationProvider } from '../rubric/[rubric_id]/NavigateToCitationContext';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';

export default function AgentRunLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const agentRunId = params.agent_run_id as string;
  const collectionId = params.collection_id as string;

  const leftSidebarOpen = useAppSelector(
    (state) => state.transcript.agentRunLeftSidebarOpen
  );

  return (
    <CitationNavigationProvider>
      <div className="flex-1 min-h-0 min-w-0 overflow-hidden">
        <ResizablePanelGroup
          autoSaveId={`docent-agent-run-workspace-v1-${collectionId}`}
          direction="horizontal"
          id="agent-run-workspace"
        >
          {leftSidebarOpen && (
            <React.Fragment key="collection-rail">
              <ResizablePanel
                className="min-w-0 overflow-hidden"
                defaultSize={34}
                id="collection-rail"
                maxSize={48}
                minSize={28}
                order={1}
              >
                <div className="h-full min-h-0 min-w-0 overflow-hidden">
                  <ExperimentViewer
                    activeRunId={agentRunId}
                    collectionId={collectionId}
                  />
                </div>
              </ResizablePanel>
              <ResizableHandle
                aria-label="Resize collection rail and agent run"
                id="agent-run-workspace-handle"
                withHandle
              />
            </React.Fragment>
          )}
          <ResizablePanel
            key="agent-run-content"
            className="min-w-0 overflow-hidden"
            defaultSize={leftSidebarOpen ? 66 : 100}
            id="agent-run-content"
            minSize={42}
            order={2}
          >
            <div className="flex h-full min-h-0 min-w-0 overflow-hidden">
              {children}
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </CitationNavigationProvider>
  );
}
