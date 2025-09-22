'use client';

import React from 'react';
import { useCitationHighlight } from '@/lib/citationUtils';
import posthog from 'posthog-js';
import { NavigateToCitation } from '@/components/CitationRenderer';

interface CitationNavigationContextValue {
  registerHandler: (handler: NavigateToCitation | null) => void;
  navigateToCitation: NavigateToCitation;
  prepareForNavigation: () => void;
}

export const CitationNavigationContext =
  React.createContext<CitationNavigationContextValue | null>(null);

export function useCitationNavigation(): CitationNavigationContextValue | null {
  const ctx = React.useContext(CitationNavigationContext);
  return ctx;
}

export const CitationNavigationProvider: React.FC<{
  children: React.ReactNode;
}> = ({ children }) => {
  const handlerRef = React.useRef<NavigateToCitation | null>(null);
  const pendingRef = React.useRef<{
    args: Parameters<NavigateToCitation>[0];
  } | null>(null);
  const { highlightCitation } = useCitationHighlight();

  const registerHandler = React.useCallback(
    (handler: NavigateToCitation | null) => {
      handlerRef.current = handler;
      if (handler && pendingRef.current) {
        const { args } = pendingRef.current;
        pendingRef.current = null;
        // Defer to let the viewer settle
        requestAnimationFrame(() => handler(args));
      }
    },
    []
  );

  const prepareForNavigation = React.useCallback(() => {
    handlerRef.current = null;
  }, []);

  const navigateToCitation = React.useCallback<NavigateToCitation>(
    ({ citation, source }) => {
      if (citation) {
        highlightCitation(citation);
        posthog.capture('citation_clicked', {
          source: source || 'generic',
          transcript_idx: citation.transcript_idx,
          block_idx: citation.block_idx,
          start_pattern: citation.start_pattern,
        });
      }
      const handler = handlerRef.current;
      if (handler) {
        handler({ citation, source });
        return;
      }
      // Store pending until a handler registers (e.g., after route change)
      pendingRef.current = { args: { citation, source } };
    },
    [highlightCitation]
  );

  const value = React.useMemo(
    () => ({ registerHandler, navigateToCitation, prepareForNavigation }),
    [registerHandler, navigateToCitation, prepareForNavigation]
  );

  return (
    <CitationNavigationContext.Provider value={value}>
      {children}
    </CitationNavigationContext.Provider>
  );
};
