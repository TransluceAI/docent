'use client';

import React, { Suspense } from 'react';
import { useAppSelector } from '@/app/store/hooks';
import { useParams } from 'next/navigation';
import SingleRubricArea from '../../components/SingleRubricArea';
import { CitationNavigationProvider } from './NavigateToCitationContext';
import { Card } from '@/components/ui/card';
import { ResultFilterControlsProvider } from '@/providers/use-result-filters';
import { RubricVersionProvider } from '@/providers/use-rubric-version';

export default function RubricLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { collection_id: collectionId, rubric_id: rubricId } = useParams<{
    collection_id: string;
    rubric_id: string;
  }>();

  // If no result selected, always show sidebar
  const judgeLeftSidebarOpen = useAppSelector(
    (state) => state.transcript.judgeLeftSidebarOpen
  );

  return (
    <Suspense>
      <CitationNavigationProvider>
        <ResultFilterControlsProvider
          rubricId={rubricId}
          collectionId={collectionId}
        >
          <RubricVersionProvider
            rubricId={rubricId}
            collectionId={collectionId}
          >
            <div className="flex-1 flex space-x-3 min-h-0 shrink-0">
              {judgeLeftSidebarOpen && (
                <Card className="flex min-w-0 basis-1/3 max-w-1/3 grow-0 shrink-0">
                  <SingleRubricArea rubricId={rubricId} />
                </Card>
              )}
              {children}
            </div>
          </RubricVersionProvider>
        </ResultFilterControlsProvider>
      </CitationNavigationProvider>
    </Suspense>
  );
}
