'use client';

import React, { Suspense } from 'react';
import { useParams } from 'next/navigation';

import ExperimentViewer from '../../components/ExperimentViewer';
import RubricArea from '@/app/dashboard/[collection_id]/components/RubricArea';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';

export default function DocentDashboard() {
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();

  return (
    <Suspense>
      <div className="flex-1 min-h-0 min-w-0 overflow-hidden">
        <ResizablePanelGroup
          autoSaveId={`docent-dashboard-workspace-v1-${collectionId}`}
          direction="horizontal"
          id="dashboard-workspace"
        >
          <ResizablePanel
            className="min-w-0 overflow-hidden"
            defaultSize={64}
            id="experiment"
            minSize={40}
            order={1}
          >
            <div className="h-full min-h-0 min-w-0 overflow-hidden">
              <ExperimentViewer collectionId={collectionId} />
            </div>
          </ResizablePanel>
          <ResizableHandle
            aria-label="Resize experiment and rubric panels"
            id="dashboard-workspace-handle"
            withHandle
          />
          <ResizablePanel
            className="min-w-0 overflow-hidden"
            defaultSize={36}
            id="rubrics"
            maxSize={60}
            minSize={24}
            order={2}
          >
            <div className="h-full min-h-0 min-w-0 overflow-hidden">
              <RubricArea />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </Suspense>
  );
}
