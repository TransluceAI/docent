'use client';

import { createContext, useContext } from 'react';
import { CitationTarget } from '@/app/types/citationTypes';
import { ResultResponse } from '@/app/api/resultSetApi';

export interface PanelState {
  id: string;
  type: 'table' | 'result' | 'agent_run';
  title: string;
  // Type-specific data
  resultId?: string;
  result?: ResultResponse;
  resultSetId?: string;
  agentRunId?: string;
  collectionId?: string;
  citationTarget?: CitationTarget;
  citationRequestId?: number;
}

export interface SlidingPanelContextValue {
  panelStack: PanelState[];
  pushPanel: (panel: Omit<PanelState, 'id'>) => void;
  closePanel: (id: string) => void;
  closePanelsAfter: (id: string) => void;
  replacePanelsAfter: (id: string, panel: Omit<PanelState, 'id'>) => void;
}

export const SlidingPanelContext =
  createContext<SlidingPanelContextValue | null>(null);

export function useSlidingPanelContext(): SlidingPanelContextValue {
  const context = useContext(SlidingPanelContext);
  if (!context) {
    throw new Error(
      'useSlidingPanelContext must be used within a SlidingPanelStack'
    );
  }
  return context;
}
