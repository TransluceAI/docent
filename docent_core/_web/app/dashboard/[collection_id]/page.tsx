'use client';

import React, { Suspense } from 'react';

import ExperimentViewer from '../../components/ExperimentViewer';
import AgentRunPreview from '../../components/AgentRunPreview';
import { useAppSelector } from '../../store/hooks';
import RubricArea from '@/app/components/RubricArea';

export default function DocentDashboard() {
  const dashboardHasRunPreview = useAppSelector(
    (state) => state.transcript.dashboardHasRunPreview
  );

  return (
    <Suspense>
      <div className="flex-1 flex space-x-3 min-h-0">
        {dashboardHasRunPreview ? (
          <AgentRunPreview />
        ) : (
          <div className="flex-1 min-h-0 overflow-hidden">
            <ExperimentViewer />
          </div>
        )}
        <RubricArea />
        {/* <SearchArea /> */}
      </div>
      {/* <Dashboard /> */}
    </Suspense>
  );
}
