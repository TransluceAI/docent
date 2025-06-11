'use client';

import DebugReduxState from '@/app/debug/DebugReduxState';
import { useSearchParams } from 'next/navigation';
import { TranscriptDiffExplorer } from '@/app/components/TranscriptDiffExplorer';
import { requestDiffsReport } from '@/app/store/diffSlice';
import { useDispatch } from 'react-redux';
import React from 'react';
import { useAppSelector } from '@/app/store/hooks';
import { AppDispatch } from '@/app/store/store';
import { NewDiffsReport } from '@/app/components/NewDiffsReport';

export default function DiffReportPage() {
  const searchParams = useSearchParams();
  const diffsReportId = searchParams.get('diffsReportId');
  const dispatch = useDispatch<AppDispatch>();
  const frameGridId = useAppSelector((state) => state.frame.frameGridId);
  React.useEffect(() => {
    if (diffsReportId) {
      dispatch(requestDiffsReport({ diffsReportId }));
    }
  }, [diffsReportId, frameGridId, dispatch]);
  const diffReport = useAppSelector((state) => state.diff.diffsReport);

  return (
    <div className="p-4">
      <DebugReduxState sliceName="diff" />
      {diffReport ? (
        <TranscriptDiffExplorer />
      ) : (
        <div>
          Click an existing diff report, or create a new one below.
          <NewDiffsReport />
        </div>
      )}
    </div>
  );
}
