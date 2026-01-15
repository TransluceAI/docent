'use client';

import React from 'react';
import posthog from 'posthog-js';
import { NavigateToCitation } from '@/components/CitationRenderer';
import { CitationTarget } from '@/app/types/citationTypes';
import { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime';

export interface CitationNavigationContextValue {
  registerHandler: (handler: NavigateToCitation | null) => void;
  navigateToCitation: NavigateToCitation;
  prepareForNavigation: () => void;
  setPendingCitation: (target: CitationTarget, source?: string) => void;
  selectedCitation: CitationTarget | null;
}

export const CitationNavigationContext =
  React.createContext<CitationNavigationContextValue | null>(null);

export function useCitationNavigation(): CitationNavigationContextValue | null {
  return React.useContext(CitationNavigationContext);
}

export const CitationNavigationProvider: React.FC<{
  children: React.ReactNode;
}> = ({ children }) => {
  const [selectedCitation, setSelectedCitation] =
    React.useState<CitationTarget | null>(null);
  const handlerRef = React.useRef<NavigateToCitation | null>(null);
  const pendingRef = React.useRef<{
    args: Parameters<NavigateToCitation>[0];
  } | null>(null);

  const registerHandler = React.useCallback(
    (handler: NavigateToCitation | null) => {
      handlerRef.current = handler;
      if (handler && pendingRef.current) {
        const { args } = pendingRef.current;
        pendingRef.current = null;
        requestAnimationFrame(() => handler(args));
      }
    },
    []
  );

  const prepareForNavigation = React.useCallback(() => {
    handlerRef.current = null;
  }, []);

  const setPendingCitation = React.useCallback(
    (target: CitationTarget, source?: string) => {
      pendingRef.current = { args: { target, source } };
    },
    []
  );

  const navigateToCitation = React.useCallback<NavigateToCitation>(
    ({ target: citation, source }) => {
      setSelectedCitation(citation);

      posthog.capture('citation_clicked', {
        source: source || 'generic',
        item_type: citation.item.item_type,
        has_text_range: citation.text_range !== null,
      });

      const handler = handlerRef.current;
      if (handler) {
        handler({ target: citation, source });
        return;
      }

      pendingRef.current = { args: { target: citation, source } };
    },
    []
  );

  const value = React.useMemo(
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

  return (
    <CitationNavigationContext.Provider value={value}>
      {children}
    </CitationNavigationContext.Provider>
  );
};

interface RouteContext {
  collectionId: string;
  currentAgentRunId: string;
  rubricId?: string;
}

/**
 * Wraps a citation navigation handler with cross-agent-run navigation logic.
 *
 * When a citation references a different agent run than the currently displayed one,
 * this wrapper navigates to that agent run's page first, then lets the
 * CitationNavigationProvider's pending mechanism deliver the citation to the new page.
 */
export function wrapCitationHandlerWithRouting(
  handler: NavigateToCitation,
  router: AppRouterInstance,
  context: RouteContext,
  setPendingCitation?: (target: CitationTarget, source?: string) => void
): NavigateToCitation {
  return ({ target, source }) => {
    // Analysis result citations don't have agent_run_id - let the handler deal with them directly
    if (target.item.item_type === 'analysis_result') {
      handler({ target, source });
      return;
    }

    const citedAgentRunId = target.item.agent_run_id;

    if (citedAgentRunId === context.currentAgentRunId) {
      handler({ target, source });
    } else {
      // If citation references a different agent run, navigate there first
      // Store citation as pending so new page can deliver it
      setPendingCitation?.(target, source);

      // Construct URL based on whether we're in rubric context
      const url = context.rubricId
        ? `/dashboard/${context.collectionId}/rubric/${context.rubricId}/agent_run/${citedAgentRunId}`
        : `/dashboard/${context.collectionId}/agent_run/${citedAgentRunId}`;

      // Navigate to the new agent run page
      router.push(url, { scroll: false } as any);

      // When the new page loads and registers its handler, the provider
      // will deliver the pending citation via requestAnimationFrame.
      // The old handler is cleared automatically when this page unmounts.
    }
  };
}
