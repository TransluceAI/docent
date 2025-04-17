'use client';
import React, { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import TranscriptDiffer from './components/TranscriptDiffer';

// Create a client component that uses useSearchParams
function DiffPageContent() {
  const searchParams = useSearchParams();
  const datapointId1 = searchParams.get('datapoint1');
  const datapointId2 = searchParams.get('datapoint2');

  if (!datapointId1 || !datapointId2) {
    return (
      <div className="flex-1 flex items-center justify-center">
        404: missing datapoint IDs
      </div>
    );
  }

  return (
    <div className="flex-1 flex min-h-0 min-w-0 space-x-4">
      <TranscriptDiffer
        datapointId1={datapointId1}
        datapointId2={datapointId2}
      />
    </div>
  );
}

export default function ExperimentPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <DiffPageContent />
    </Suspense>
  );
}
