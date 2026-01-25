'use client';

import React, { Suspense, useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';

import AgentRunViewer, {
  AgentRunViewerHandle,
} from '../../../agent_run/components/AgentRunViewer';
import { CitationTarget } from '@/app/types/citationTypes';
import { useCitationNavigation } from '@/providers/CitationNavigationProvider';

export default function QaAgentRunLayout() {
  const { collection_id: collectionId, agent_run_id: agentRunId } = useParams<{
    collection_id: string;
    agent_run_id: string;
  }>();
  const router = useRouter();
  const citationNav = useCitationNavigation();
  const agentRunViewerRef = useRef<AgentRunViewerHandle>(null);

  useEffect(() => {
    if (!citationNav || !collectionId || !agentRunId) return;

    const handler = ({
      target,
      source,
    }: {
      target: CitationTarget;
      source?: string;
    }) => {
      if (
        target.item.item_type === 'analysis_result' ||
        target.item.agent_run_id === agentRunId
      ) {
        agentRunViewerRef.current?.focusCitationTarget(target);
        return;
      }

      citationNav.setPendingCitation(target, source);
      router.push(
        `/dashboard/${collectionId}/qa/agent_run/${target.item.agent_run_id}`,
        { scroll: false } as any
      );
    };

    citationNav.registerHandler(handler);
    return () => citationNav.registerHandler(null);
  }, [citationNav, router, collectionId, agentRunId]);

  return (
    <Suspense>
      <div className="h-full overflow-hidden flex flex-col space-y-2">
        <AgentRunViewer
          ref={agentRunViewerRef}
          agentRunId={agentRunId}
          collectionId={collectionId}
        />
      </div>
    </Suspense>
  );
}
