'use client';

import { useRouter } from 'next/navigation';
import React, { Suspense } from 'react';

import { BASE_DOCENT_PATH } from '@/app/constants';
import { useAppSelector } from '@/app/store/hooks';

import AttributeFinder from '../components/AttributeFinder';
import ExperimentViewer from '../components/ExperimentViewer';

function DocentDashboardContent() {
  const router = useRouter();
  const evalId = useAppSelector((state) => state.frame.evalId);

  const handleShowAgentRun = React.useCallback(
    (agentRunId: string, blockIdx?: number) => {
      if (blockIdx !== undefined) {
        router.push(
          `${BASE_DOCENT_PATH}/${evalId}/transcript/${agentRunId}?block_id=${blockIdx}`
        );
      } else {
        router.push(`${BASE_DOCENT_PATH}/${evalId}/transcript/${agentRunId}`);
      }
    },
    [router, evalId]
  );

  return (
    <div className="flex-1 flex space-x-3 min-h-0">
      <ExperimentViewer onShowAgentRun={handleShowAgentRun} />
      <AttributeFinder onShowAgentRun={handleShowAgentRun} />
    </div>
  );
}

export default function DocentDashboard() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <DocentDashboardContent />
    </Suspense>
  );
}
