'use client';

import React, { Suspense } from 'react';
import { useParams } from 'next/navigation';
import SingleRubricArea from '../../components/SingleRubricArea';
import {
  CitationNavigationProvider,
  useCitationNavigation,
} from './NavigateToCitationContext';
import { Card } from '@/components/ui/card';

export default function RubricLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const rubricId = params.rubric_id as string;
  const selectedResultId = params.result_id as string | undefined;

  return (
    <Suspense>
      <CitationNavigationProvider>
        <div className="flex-1 flex space-x-3 min-h-0 shrink-0">
          <Card className="flex min-w-0 basis-1/3 max-w-1/3 grow-0 shrink-0">
            <RubricLeftColumn
              rubricId={rubricId}
              selectedResultId={selectedResultId}
            />
          </Card>
          {children}
        </div>
      </CitationNavigationProvider>
    </Suspense>
  );
}

// Keep `RubricLeftColumn` separate so it can call `useCitationNavigation`.
// The hook consumes context from `CitationNavigationProvider`, which only applies to descendants.
function RubricLeftColumn({
  rubricId,
  selectedResultId,
}: {
  rubricId: string;
  selectedResultId?: string;
}) {
  const citationNav = useCitationNavigation();
  return (
    <SingleRubricArea
      rubricId={rubricId}
      selectedResultId={selectedResultId}
      onNavigateToCitation={citationNav?.navigateToCitation}
    />
  );
}
