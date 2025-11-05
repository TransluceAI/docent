'use client';

import { useMemo, useRef, useEffect, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import JudgeResultCard from './JudgeResultCard';
import { SchemaDefinition } from '@/app/types/schema';
import { Label } from '@/app/api/labelApi';
import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import { applyViewModeResults } from '../utils/viewModeResults';
import {
  useResultFilterControls,
  ViewMode,
} from '@/providers/use-result-filters';
import { cn } from '@/lib/utils';

interface ViewSnapshot {
  viewMode: ViewMode;
  visibilitySet?: Set<string>;
  sortOrder?: string[];
}

interface VirtualResultsListProps {
  agentRunResults: AgentRunJudgeResults[];
  activeResultId?: string;
  schema: SchemaDefinition;
  labels?: Label[];
  activeLabelSet: any;
}

const VirtualResultsList = ({
  agentRunResults,
  activeResultId,
  schema,
  labels,
  activeLabelSet,
}: VirtualResultsListProps) => {
  const { filters, viewMode } = useResultFilterControls();

  const [viewSnapshot, setViewSnapshot] = useState<ViewSnapshot | null>(null);

  // Snapshot Management
  // Purpose: Stabilize the view during label editing to prevent:
  //   1. Items disappearing when labeled (missing_labels view)
  //   2. Items reordering when labels change scores (labeled_disagreement, incomplete_labels)
  //
  // Behavior:
  // - On view/filter change: Create new snapshot for current view
  // - During editing: Use snapshot to maintain stable visibility/ordering
  // - On data changes: Merge newly-appeared items (missing_labels only)
  // - On view exit: Clear snapshot
  //
  // Why two effects: Separating reset logic (view/filter) from merge logic (data)
  // keeps the behavior predictable and prevents infinite update loops.

  // Effect 1: Create/reset snapshot on view entry or filter changes
  useEffect(() => {
    const baseFiltered = applyViewModeResults(
      agentRunResults,
      labels ?? [],
      viewMode,
      filters,
      null
    );

    if (viewMode === 'missing_labels') {
      setViewSnapshot({
        viewMode,
        visibilitySet: new Set(baseFiltered.map((run) => run.agent_run_id)),
      });
    } else if (
      viewMode === 'labeled_disagreement' ||
      viewMode === 'incomplete_labels'
    ) {
      setViewSnapshot({
        viewMode,
        sortOrder: baseFiltered.map((run) => run.agent_run_id),
      });
    } else {
      setViewSnapshot(null);
    }
    // Intentionally exclude agentRunResults/labels - we want a stable snapshot
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode, filters]);

  // Effect 2: Merge newly-appeared unlabeled runs into existing snapshot
  useEffect(() => {
    if (
      viewMode === 'missing_labels' &&
      viewSnapshot?.viewMode === 'missing_labels' &&
      viewSnapshot.visibilitySet
    ) {
      const baseFiltered = applyViewModeResults(
        agentRunResults,
        labels ?? [],
        viewMode,
        filters,
        null
      );
      const currentUnlabeledIds = new Set(
        baseFiltered.map((run) => run.agent_run_id)
      );

      const hasNewIds = Array.from(currentUnlabeledIds).some(
        (id) => !viewSnapshot.visibilitySet!.has(id)
      );

      if (hasNewIds) {
        const mergedVisibilitySet = new Set([
          ...Array.from(viewSnapshot.visibilitySet),
          ...Array.from(currentUnlabeledIds),
        ]);
        setViewSnapshot({
          ...viewSnapshot,
          visibilitySet: mergedVisibilitySet,
        });
      }
    }
    // React to data changes to detect newly-appeared runs
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentRunResults, labels]);

  const sortedJudgeResultsList: AgentRunJudgeResults[] = useMemo(() => {
    const filtered = applyViewModeResults(
      agentRunResults,
      labels ?? [],
      viewMode,
      filters,
      viewSnapshot?.visibilitySet ?? null
    );

    // If we have a sort order snapshot, apply it to maintain stable ordering
    if (viewSnapshot?.sortOrder && viewSnapshot.sortOrder.length > 0) {
      const orderMap = new Map(
        viewSnapshot.sortOrder.map((id, index) => [id, index])
      );

      // Separate items in snapshot from new items not in snapshot
      const inSnapshot: AgentRunJudgeResults[] = [];
      const notInSnapshot: AgentRunJudgeResults[] = [];

      filtered.forEach((run) => {
        if (orderMap.has(run.agent_run_id)) {
          inSnapshot.push(run);
        } else {
          notInSnapshot.push(run);
        }
      });

      // Sort items that are in the snapshot according to the snapshot order
      inSnapshot.sort(
        (a, b) =>
          (orderMap.get(a.agent_run_id) ?? 0) -
          (orderMap.get(b.agent_run_id) ?? 0)
      );

      // Append new items at the end (they keep their relative order from filtering)
      return [...inSnapshot, ...notInSnapshot];
    }

    return filtered;
  }, [agentRunResults, labels, viewMode, filters, viewSnapshot]);
  const parentRef = useRef<HTMLDivElement>(null);

  // Create agent_run_id -> label map
  const labelsMap = useMemo(() => {
    const map = new Map<string, Label[]>();
    if (labels) {
      for (const label of labels) {
        const existing = map.get(label.agent_run_id) || [];
        map.set(label.agent_run_id, [...existing, label]);
      }
    }
    return map;
  }, [labels]);

  // Create the virtualizer
  const virtualizer = useVirtualizer({
    count: sortedJudgeResultsList.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      // Estimate size based on number of results in the group
      // Each result is roughly 100px, plus header of ~40px
      const resultsCount = sortedJudgeResultsList[index].results.length;
      return 40 + resultsCount * 200;
    },
    paddingStart: 0,
    paddingEnd: 50,
  });
  const items = virtualizer.getVirtualItems();

  // Scroll to the active result group if it exists on load
  useEffect(() => {
    const activeResultResultIdx = agentRunResults.findIndex((group) =>
      group.results.some((result) => result.id === activeResultId)
    );
    if (activeResultResultIdx !== -1) {
      virtualizer.scrollToIndex(activeResultResultIdx, { align: 'start' });
    }
  }, []);

  return (
    <div
      ref={parentRef}
      style={{
        // height: 450,
        width: '100%',
        overflowY: 'auto',
        contain: 'strict',
      }}
      className="grow custom-scrollbar"
    >
      <div
        style={{
          height: virtualizer.getTotalSize(),
          width: '100%',
          position: 'relative',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            transform: `translateY(${items[0]?.start ?? 0}px)`,
          }}
        >
          {items.map((virtualRow) => {
            const group = sortedJudgeResultsList[virtualRow.index];
            const hasActiveResult = group.results.some(
              (result) => result.id === activeResultId
            );
            return (
              <div
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
              >
                <div
                  className={cn(
                    'text-xs px-2 my-2 bg-secondary text-muted-foreground justify-between py-1 font-medium rounded-sm flex items-center',
                    hasActiveResult && 'bg-indigo-bg',
                    virtualRow.index === 0 && 'mt-0'
                  )}
                >
                  <span>Agent Run {group.agent_run_id.slice(0, 8)}</span>
                </div>
                <JudgeResultCard
                  key={group.agent_run_id}
                  agentRunResult={group}
                  schema={schema}
                  labels={labelsMap?.get(group.agent_run_id) || []}
                  activeLabelSetId={activeLabelSet?.id || null}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default VirtualResultsList;
