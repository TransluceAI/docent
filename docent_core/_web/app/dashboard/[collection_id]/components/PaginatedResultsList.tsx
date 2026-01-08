'use client';

import { useMemo, useEffect, useRef, useState, useCallback } from 'react';
import JudgeResultCard from './JudgeResultCard';
import FailedResultCard from './FailedResultCard';
import { SchemaDefinition } from '@/app/types/schema';
import { Label } from '@/app/api/labelApi';
import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import { applyViewModeResults, ViewMode } from '../utils/viewModeResults';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface ViewSnapshot {
  viewMode: ViewMode;
  visibilitySet?: Set<string>;
  sortOrder?: string[];
}

interface PaginatedResultsListProps {
  agentRunResults: AgentRunJudgeResults[];
  activeResultId?: string;
  activeAgentRunId?: string;
  schema: SchemaDefinition;
  labels?: Label[];
  activeLabelSet: any;
  showLabels?: boolean;
  viewMode: ViewMode;
  pageSize?: number;
}

const DEFAULT_PAGE_SIZE = 25;

const PaginatedResultsList = ({
  agentRunResults,
  activeResultId,
  activeAgentRunId,
  schema,
  labels,
  activeLabelSet,
  showLabels = true,
  viewMode,
  pageSize,
}: PaginatedResultsListProps) => {
  const [viewSnapshot, setViewSnapshot] = useState<ViewSnapshot | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const normalizedPageSize = Math.max(1, pageSize ?? DEFAULT_PAGE_SIZE);
  const hasInitialScrolledRef = useRef(false);

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
  }, [viewMode]);

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
  }, [agentRunResults, labels, viewMode, viewSnapshot]);

  const totalResults = sortedJudgeResultsList.length;
  const totalPages = Math.max(1, Math.ceil(totalResults / normalizedPageSize));

  useEffect(() => {
    setCurrentPage((prev) => Math.min(Math.max(prev, 1), totalPages));
  }, [totalPages]);

  const activeIndex = useMemo(() => {
    if (!activeAgentRunId) {
      return -1;
    }
    return sortedJudgeResultsList.findIndex(
      (run) => run.agent_run_id === activeAgentRunId
    );
  }, [activeAgentRunId, sortedJudgeResultsList]);

  useEffect(() => {
    if (activeIndex < 0) {
      return;
    }
    const targetPage = Math.floor(activeIndex / normalizedPageSize) + 1;
    setCurrentPage((prev) => (prev === targetPage ? prev : targetPage));
  }, [activeIndex, normalizedPageSize]);

  const pageStartIndex = (currentPage - 1) * normalizedPageSize;
  const paginatedResults = sortedJudgeResultsList.slice(
    pageStartIndex,
    pageStartIndex + normalizedPageSize
  );
  const pageStart = totalResults === 0 ? 0 : pageStartIndex + 1;
  const pageEnd = Math.min(pageStartIndex + normalizedPageSize, totalResults);
  const isFirstPage = currentPage <= 1;
  const isLastPage = currentPage >= totalPages;

  const handleActiveItemRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) {
      return;
    }
    // Only scroll on initial mount
    if (hasInitialScrolledRef.current) {
      return;
    }
    hasInitialScrolledRef.current = true;
    node.scrollIntoView({ block: 'start' });
  }, []);

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

  return (
    <div className="flex min-h-0 grow flex-col space-y-1">
      <div className="grow custom-scrollbar w-full overflow-y-auto space-y-2">
        {paginatedResults.map((group, index) => {
          const hasActiveResult = group.agent_run_id === activeAgentRunId;
          const directResults = group.results.filter(
            (result) => result.result_type === 'DIRECT_RESULT'
          );
          const failedResults = group.results.filter(
            (result) => result.result_type === 'FAILURE'
          );
          const hasDirectResults = directResults.length > 0;
          const directResultGroup = hasDirectResults
            ? { ...group, results: directResults }
            : null;

          return (
            <div
              key={group.agent_run_id}
              data-index={pageStartIndex + index}
              data-agent-run-id={group.agent_run_id}
              className="space-y-1"
              ref={
                activeAgentRunId === group.agent_run_id
                  ? handleActiveItemRef
                  : undefined
              }
            >
              <div
                className={cn(
                  'text-xs px-2 bg-secondary text-muted-foreground justify-between py-1 font-medium rounded-sm flex items-center',
                  hasActiveResult && 'bg-indigo-bg'
                )}
              >
                <span>Agent Run {group.agent_run_id.slice(0, 8)}</span>
              </div>
              <div
                className={cn(
                  'ml-0.5 border-l-2 pl-2 space-y-2',
                  hasActiveResult ? 'border-indigo-border' : 'border-border'
                )}
              >
                {hasDirectResults && directResultGroup && (
                  <JudgeResultCard
                    key={group.agent_run_id}
                    agentRunResult={directResultGroup}
                    schema={schema}
                    labels={labelsMap?.get(group.agent_run_id) || []}
                    activeLabelSetId={activeLabelSet?.id || null}
                    showLabels={showLabels}
                  />
                )}
                {failedResults.length > 0 && (
                  <>
                    {failedResults.map((result) => (
                      <FailedResultCard key={result.id} result={result} />
                    ))}
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-end">
          <div className="flex items-center space-x-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 text-muted-foreground hover:text-foreground"
              onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
              disabled={isFirstPage}
            >
              <ChevronLeft className="h-3 w-3" />
            </Button>
            <span className="text-xs text-muted-foreground">
              Page {currentPage} / {totalPages}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 text-muted-foreground hover:text-foreground"
              onClick={() =>
                setCurrentPage((prev) => Math.min(totalPages, prev + 1))
              }
              disabled={isLastPage}
            >
              <ChevronRight className="h-3 w-3" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export default PaginatedResultsList;
