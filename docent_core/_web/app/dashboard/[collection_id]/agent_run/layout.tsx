'use client';

import React from 'react';

import ExperimentViewer from '../../../components/ExperimentViewer';
import { useParams } from 'next/navigation';
import { useAppSelector } from '@/app/store/hooks';

export default function AgentRunLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const agentRunId = params.agent_run_id as string;

  const leftSidebarOpen = useAppSelector(
    (state) => state.transcript.leftSidebarOpen ?? false
  );

  return (
    <div className="flex-1 flex space-x-3 min-h-0">
      {leftSidebarOpen && (
        <div
          className="basis-96 shrink-0 min-w-0 overflow-hidden"
          style={{ flexGrow: '1' }}
        >
          <ExperimentViewer activeRunId={agentRunId} />
        </div>
      )}
      {children}
    </div>
  );
}
