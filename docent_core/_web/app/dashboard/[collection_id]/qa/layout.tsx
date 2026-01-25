'use client';

import React, { Suspense, useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import type { ImperativePanelHandle } from 'react-resizable-panels';

import {
  CitationNavigationProvider,
  useCitationNavigation,
} from '@/providers/CitationNavigationProvider';
import { CitationTarget } from '@/app/types/citationTypes';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import QaRubricElicitationPanel from './components/QaRubricElicitationPanel';
import { cn } from '@/lib/utils';

interface QaLayoutBodyProps {
  collectionId: string;
  children: React.ReactNode;
}

function QaLayoutBody({ collectionId, children }: QaLayoutBodyProps) {
  const { agent_run_id: agentRunId } = useParams<{
    agent_run_id?: string;
  }>();
  const isOnAgentRunRoute = !!agentRunId;
  const router = useRouter();
  const citationNav = useCitationNavigation();

  const leftPanelRef = useRef<ImperativePanelHandle>(null);
  const rightPanelRef = useRef<ImperativePanelHandle>(null);

  useEffect(() => {
    const leftPanelSize = isOnAgentRunRoute ? 55 : 100;
    const rightPanelSize = isOnAgentRunRoute ? 45 : 0;

    leftPanelRef.current?.resize(leftPanelSize);
    rightPanelRef.current?.resize(rightPanelSize);
  }, [isOnAgentRunRoute]);

  useEffect(() => {
    if (!citationNav || isOnAgentRunRoute) return;

    const handler = ({
      target,
    }: {
      target: CitationTarget;
      source?: string;
    }) => {
      if (target.item.item_type === 'analysis_result') return;
      citationNav.setPendingCitation(target);
      router.push(
        `/dashboard/${collectionId}/qa/agent_run/${target.item.agent_run_id}`,
        { scroll: false } as any
      );
    };

    citationNav.registerHandler(handler);
    return () => citationNav.registerHandler(null);
  }, [citationNav, router, collectionId, isOnAgentRunRoute]);

  return (
    <ResizablePanelGroup
      direction="horizontal"
      className="flex-1 flex bg-card space-x-3 min-h-0 shrink-0 border rounded-lg"
    >
      <ResizablePanel
        ref={leftPanelRef}
        defaultSize={isOnAgentRunRoute ? 55 : 100}
        minSize={30}
        maxSize={75}
        className="flex min-w-0 min-h-0 p-3"
      >
        <QaRubricElicitationPanel />
      </ResizablePanel>

      <ResizableHandle
        className={cn('!mx-0 !px-0', !isOnAgentRunRoute && 'hidden')}
      />

      <ResizablePanel
        ref={rightPanelRef}
        defaultSize={isOnAgentRunRoute ? 45 : 0}
        minSize={isOnAgentRunRoute ? 25 : 0}
        maxSize={70}
        className={cn(
          'flex min-w-0 min-h-0 p-3 !mx-0',
          !isOnAgentRunRoute && 'hidden'
        )}
      >
        {children}
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}

export default function QaLayout({ children }: { children: React.ReactNode }) {
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();

  return (
    <Suspense>
      <CitationNavigationProvider>
        <QaLayoutBody collectionId={collectionId}>{children}</QaLayoutBody>
      </CitationNavigationProvider>
    </Suspense>
  );
}
