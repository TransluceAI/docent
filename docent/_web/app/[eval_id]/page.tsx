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
    (agentRunId: string, blockIdx?: number, blockIdx2?: number, paired?: boolean) => {
      console.log('PARAMS', agentRunId, blockIdx, blockIdx2, paired);
      let prefix = `${BASE_DOCENT_PATH}/${evalId}/` + (paired ? 'paired_transcript' : 'transcript') + `/${agentRunId}`;
      if (blockIdx != undefined) {
        prefix += `?block_id_1=${blockIdx}`;
        if (blockIdx2 != undefined) {
          prefix += `&block_id_2=${blockIdx2}`;
        }
      }
      router.push(prefix);
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
