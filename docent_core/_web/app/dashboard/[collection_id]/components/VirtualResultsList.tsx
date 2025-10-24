'use client';

import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { useMemo, useRef, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { useVirtualizer } from '@tanstack/react-virtual';
import JudgeResultCard from './JudgeResultCard';
import { SchemaDefinition } from '@/app/types/schema';
import { Label } from '@/app/api/labelApi';

interface VirtualResultsListProps {
  filteredJudgeResultsList: JudgeResultWithCitations[];
  activeResultId?: string;
  schema: SchemaDefinition;
  labels?: Label[];
}

const VirtualResultsList = ({
  filteredJudgeResultsList,
  activeResultId,
  schema,
  labels,
}: VirtualResultsListProps) => {
  // Group the results by agent run id
  const agentRunGroups = useMemo(() => {
    const grouped: Record<string, JudgeResultWithCitations[]> = {};
    for (const result of filteredJudgeResultsList) {
      if (!grouped[result.agent_run_id]) {
        grouped[result.agent_run_id] = [];
      }
      grouped[result.agent_run_id].push(result);
    }
    return Object.entries(grouped).map(([agentRunId, results]) => ({
      agentRunId,
      results,
    }));
  }, [filteredJudgeResultsList]);

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
    count: agentRunGroups.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      // Estimate size based on number of results in the group
      // Each result is roughly 100px, plus header of ~40px
      const resultsCount = agentRunGroups[index]?.results.length || 1;
      return 40 + resultsCount * 100;
    },
    paddingStart: 0,
    paddingEnd: 30,
  });
  const items = virtualizer.getVirtualItems();

  // Scroll to the active result group if it exists on load
  useEffect(() => {
    const activeResultGroupIdx = agentRunGroups.findIndex((group) =>
      group.results.some((result) => result.id === activeResultId)
    );
    if (activeResultGroupIdx !== -1) {
      virtualizer.scrollToIndex(activeResultGroupIdx, { align: 'start' });
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
      className="grow"
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
            const group = agentRunGroups[virtualRow.index];
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
                  <span>Agent Run {group.agentRunId.slice(0, 8)}</span>
                </div>
                {group.results.map((result) => (
                  <JudgeResultCard
                    key={result.id}
                    agentRunId={group.agentRunId}
                    judgeResult={result}
                    schema={schema}
                    labels={labelsMap?.get(group.agentRunId) || []}
                  />
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default VirtualResultsList;
