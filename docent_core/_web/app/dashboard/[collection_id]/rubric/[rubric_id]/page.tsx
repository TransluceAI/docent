'use client';

import React, { Suspense } from 'react';

export default function RubricPage() {
  return (
    <Suspense>
      <div className="flex flex-1 flex-col items-center justify-center">
        <div className="text-xs text-muted-foreground">
          Select a result to view details
        </div>
      </div>
    </Suspense>
  );
}
