'use client';

import React, { useCallback, useState } from 'react';
import { AnalysisResultItem, CitationTarget } from '@/app/types/citationTypes';
import { useSlidingPanelContext } from './SlidingPanelContext';
import { AgentRunViewerHandle } from '@/app/dashboard/[collection_id]/agent_run/components/AgentRunViewer';
import {
  CitationNavigationContext,
  CitationNavigationContextValue,
} from '@/providers/CitationNavigationProvider';
import { NavigateToCitation } from '@/components/CitationRenderer';

interface PanelCitationProviderProps {
  children: React.ReactNode;
  panelId: string;
  currentAgentRunId?: string;
  viewerRef?: React.RefObject<AgentRunViewerHandle | null>;
  initialCitationTarget?: CitationTarget;
  citationRequestId?: number;
}

/**
 * Provides local citation navigation context for a panel.
 *
 * When a citation is clicked within this panel:
 * - If it references the same agent run, focus within the panel
 * - If it references a different agent run, push a new panel to the stack
 */
export function PanelCitationProvider({
  children,
  panelId,
  currentAgentRunId,
  viewerRef,
  initialCitationTarget,
  citationRequestId,
}: PanelCitationProviderProps) {
  const { replacePanelsAfter } = useSlidingPanelContext();
  const [selectedCitation, setSelectedCitation] =
    useState<CitationTarget | null>(null);

  // Set selectedCitation when initialCitationTarget changes (identified by citationRequestId)
  // This handles highlighting; scrolling is handled separately in AgentRunPanelContent
  React.useEffect(() => {
    if (initialCitationTarget) {
      setSelectedCitation(initialCitationTarget);
    }
  }, [initialCitationTarget, citationRequestId]);

  // These are required by CitationNavigationContextValue interface but unused in panel context
  const registerHandler = useCallback(
    (_handler: NavigateToCitation | null) => {},
    []
  );
  const prepareForNavigation = useCallback(() => {}, []);
  const setPendingCitation = useCallback(
    (_target: CitationTarget, _source?: string) => {},
    []
  );

  const navigateToCitation = useCallback<NavigateToCitation>(
    ({ target, source }) => {
      setSelectedCitation(target);

      // Handle analysis_result citations
      if (target.item.item_type === 'analysis_result') {
        const item = target.item as AnalysisResultItem;
        replacePanelsAfter(panelId, {
          type: 'result',
          title: 'Result',
          resultId: item.result_id,
          resultSetId: item.result_set_id,
          collectionId: item.collection_id,
        });
        return;
      }

      // For other citation types (agent_run_metadata, transcript_metadata, block_metadata, block_content)
      const citedAgentRunId = target.item.agent_run_id;
      const citedCollectionId = target.item.collection_id;

      // If same agent run and we have a viewer ref, focus within the panel
      if (currentAgentRunId && citedAgentRunId === currentAgentRunId) {
        viewerRef?.current?.focusCitationTarget(target);
        return;
      }

      // Different agent run - atomically close panels after this one and push a new panel
      replacePanelsAfter(panelId, {
        type: 'agent_run',
        title: 'Run',
        agentRunId: citedAgentRunId,
        collectionId: citedCollectionId,
        citationTarget: target,
        citationRequestId: Date.now(),
      });
    },
    [currentAgentRunId, panelId, replacePanelsAfter, viewerRef]
  );

  const value: CitationNavigationContextValue = React.useMemo(
    () => ({
      registerHandler,
      navigateToCitation,
      prepareForNavigation,
      setPendingCitation,
      selectedCitation,
    }),
    [
      registerHandler,
      navigateToCitation,
      prepareForNavigation,
      setPendingCitation,
      selectedCitation,
    ]
  );

  // Use the same context as the global CitationNavigationProvider
  // This allows us to override citation handling for this panel's subtree
  return (
    <CitationNavigationContext.Provider value={value}>
      {children}
    </CitationNavigationContext.Provider>
  );
}
