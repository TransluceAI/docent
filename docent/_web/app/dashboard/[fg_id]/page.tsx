'use client';

import React, { Suspense } from 'react';

import SearchArea from '../../components/SearchArea';
import ExperimentViewer from '../../components/ExperimentViewer';

function DocentDashboardContent() {
  return (
    <div className="flex-1 flex space-x-3 min-h-0">
      <ExperimentViewer />
      <SearchArea />
    </div>
  );
}

export default function DocentDashboard() {
  return (
    <Suspense>
      <DocentDashboardContent />
    </Suspense>
  );
}
