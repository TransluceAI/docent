'use client';

import React, { Suspense } from 'react';
import GlobalView from '../components/GlobalView';
import { useRouter } from 'next/navigation';
import { BASE_DOCENT_PATH } from '@/app/constants';
import { useAppSelector } from '@/app/store/hooks';

function DocentDashboardContent() {
  const router = useRouter();
  const evalId = useAppSelector((state) => state.frame.evalId);

  const handleShowDatapoint = React.useCallback(
    (datapointId: string, blockIdx?: number) => {
      if (blockIdx !== undefined) {
        router.push(
          `${BASE_DOCENT_PATH}/${evalId}/transcript/${datapointId}?block_id=${blockIdx}`
        );
      } else {
        router.push(`${BASE_DOCENT_PATH}/${evalId}/transcript/${datapointId}`);
      }
    },
    [router, evalId]
  );

  return (
    <div className="flex-1 flex space-x-3 min-h-0">
      <GlobalView onShowDatapoint={handleShowDatapoint} />
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
