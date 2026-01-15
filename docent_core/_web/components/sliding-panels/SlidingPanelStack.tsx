'use client';

import React, { useCallback, useRef, useState, useEffect } from 'react';
import { AnimatePresence } from 'framer-motion';
import { SlidingPanelContext, PanelState } from './SlidingPanelContext';

let panelIdCounter = 0;
function generatePanelId(): string {
  return `panel-${++panelIdCounter}-${Date.now()}`;
}

interface SlidingPanelStackProps {
  initialPanels?: PanelState[];
  children: (context: {
    panelStack: PanelState[];
    pushPanel: (panel: Omit<PanelState, 'id'>) => void;
  }) => React.ReactNode;
}

export function SlidingPanelStack({
  initialPanels = [],
  children,
}: SlidingPanelStackProps) {
  const [panelStack, setPanelStack] = useState<PanelState[]>(initialPanels);
  const containerRef = useRef<HTMLDivElement>(null);
  const prevStackLengthRef = useRef(initialPanels.length);

  const pushPanel = useCallback((panel: Omit<PanelState, 'id'>) => {
    const newPanel: PanelState = {
      ...panel,
      id: generatePanelId(),
    };
    setPanelStack((prev) => [...prev, newPanel]);
  }, []);

  const closePanel = useCallback((id: string) => {
    setPanelStack((prev) => {
      const index = prev.findIndex((p) => p.id === id);
      if (index === -1) return prev;
      // Close this panel and all panels after it
      return prev.slice(0, index);
    });
  }, []);

  const closePanelsAfter = useCallback((id: string) => {
    setPanelStack((prev) => {
      const index = prev.findIndex((p) => p.id === id);
      if (index === -1) return prev;
      // Keep this panel, close all after it
      return prev.slice(0, index + 1);
    });
  }, []);

  const replacePanelsAfter = useCallback(
    (id: string, panel: Omit<PanelState, 'id'>) => {
      setPanelStack((prev) => {
        const index = prev.findIndex((p) => p.id === id);
        if (index === -1) {
          return [
            ...prev,
            {
              ...panel,
              id: generatePanelId(),
            },
          ];
        }

        const replaceIndex = index + 1;
        const idToReuse =
          replaceIndex < prev.length
            ? prev[replaceIndex].id
            : generatePanelId();

        // Keep panels up to and including this one, then replace the next panel in-place.
        // Reusing the id makes this a true "replace" (no unmount/mount animation).
        return [
          ...prev.slice(0, index + 1),
          {
            ...panel,
            id: idToReuse,
          },
        ];
      });
    },
    []
  );

  // Auto-scroll to the rightmost panel only when stack grows (not when replacing)
  useEffect(() => {
    const prevLength = prevStackLengthRef.current;
    prevStackLengthRef.current = panelStack.length;

    // Only scroll if we added panels (stack grew), not if we replaced
    if (panelStack.length > prevLength && containerRef.current) {
      const lastPanelId = panelStack[panelStack.length - 1].id;
      const lastPanel = containerRef.current.querySelector(
        `[data-panel-id="${lastPanelId}"]`
      );
      if (lastPanel) {
        lastPanel.scrollIntoView({
          behavior: 'smooth',
          inline: 'end',
        });
      }
    }
  }, [panelStack]);

  const contextValue = {
    panelStack,
    pushPanel,
    closePanel,
    closePanelsAfter,
    replacePanelsAfter,
  };

  return (
    <SlidingPanelContext.Provider value={contextValue}>
      <div
        ref={containerRef}
        className="flex h-full overflow-x-auto"
        style={{ scrollBehavior: 'smooth' }}
      >
        <AnimatePresence mode="popLayout">
          {React.Children.toArray(children({ panelStack, pushPanel }))}
        </AnimatePresence>
      </div>
    </SlidingPanelContext.Provider>
  );
}

// Re-export for convenience
export { SlidingPanel } from './SlidingPanel';
export type { PanelState } from './SlidingPanelContext';
