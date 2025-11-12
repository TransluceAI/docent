'use client';

import React, { Suspense } from 'react';

import ExperimentViewer from '../../components/ExperimentViewer';

export default function DocentDashboard() {
  return (
    <Suspense>
      <div className="flex-1 flex bg-card min-h-0 shrink-0 border rounded-lg p-3">
        <div className="size-full min-w-0 overflow-auto">
          <ExperimentViewer />
        </div>
      </div>
    </Suspense>
  );
}
