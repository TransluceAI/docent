'use client';
import { cn } from '@/lib/utils';
import {
  JudgeResultWithCitations,
  RubricCentroid,
} from '@/app/store/rubricSlice';
import { useCallback, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { JudgeResultCard } from './JudgeResultCard';

interface CollapsibleResultsSectionProps {
  title: string;
  judgeResultIds: string[];
  judgeResultsMap: Record<string, JudgeResultWithCitations>;
  clickable: boolean;
  isPollingAssignments: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
  selectedResultId?: string;
}

const CollapsibleResultsSection = ({
  title,
  judgeResultIds,
  judgeResultsMap,
  clickable,
  isPollingAssignments,
  isExpanded = true,
  onToggle,
  selectedResultId,
}: CollapsibleResultsSectionProps) => {
  // Count only judge results with non-null values (what actually gets displayed)
  const resultHits = useMemo(() => {
    return judgeResultIds
      .map((id) => judgeResultsMap[id])
      .filter((result) => result !== null);
  }, [judgeResultIds, judgeResultsMap]);

  // Group results by agent run ID
  const groupedResults = useMemo(() => {
    const groups: { [agentRunId: string]: typeof resultHits } = {};
    resultHits.forEach((result) => {
      if (!groups[result.agent_run_id]) {
        groups[result.agent_run_id] = [];
      }
      groups[result.agent_run_id].push(result);
    });
    return groups;
  }, [resultHits]);

  const uniqueAgentRunCount = Object.keys(groupedResults).length;

  const AgentRunGroupHeader = ({ agentRunId }: { agentRunId: string }) => {
    return (
      <div className="text-[10px] text-muted-foreground font-medium px-2 py-1 bg-secondary/50 rounded-sm mb-1 flex items-center justify-between">
        <span>Agent Run {agentRunId.slice(0, 8)}</span>
      </div>
    );
  };

  return (
    <div className="space-y-2">
      <div
        onClick={onToggle}
        className="text-xs p-1.5 bg-background rounded border border-border flex  cursor-pointer items-center gap-1.5"
      >
        {/* Expand/collapse button on the left */}
        {isExpanded ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground" />
        )}

        {/* Count */}
        <div className="flex-shrink-0 flex items-center">
          <span className="text-xs px-1.5 py-0.5 rounded-sm bg-muted text-muted-foreground flex items-center min-w-[2rem] justify-center hover:bg-muted/80 transition-colors">
            {`${uniqueAgentRunCount} runs`}
            {isPollingAssignments && (
              <div className="animate-spin ml-1 rounded-full h-2 w-2 border-[1.5px] border-border border-t-gray-500 inline-block" />
            )}
          </span>
        </div>

        {/* Title */}
        <div className="flex-1 text-xs text-primary ml-1">
          <div className="flex items-center gap-2">{title}</div>
        </div>
      </div>

      {/* Expanded results grouped by agent run */}
      {isExpanded && resultHits.length > 0 && (
        <div className="pl-4 space-y-2">
          {Object.entries(groupedResults).map(([agentRunId, results]) => (
            <div key={agentRunId} className="space-y-1">
              <AgentRunGroupHeader agentRunId={agentRunId} />
              <div className="space-y-1">
                {results.map((judgeResult, idx) => (
                  <JudgeResultCard
                    clickable={clickable}
                    key={`${agentRunId}-${idx}`}
                    judgeResult={judgeResult}
                    isActive={selectedResultId === judgeResult.id}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

interface JudgeResultsListProps {
  clickable?: boolean;
  judgeResultsMap: Record<string, JudgeResultWithCitations>;
  labels?: string[];
  centroidsMap: Record<string, RubricCentroid> | null;
  centroidAssignments: Record<string, string[]>;
  isPollingAssignments: boolean;
  selectedResultId?: string;
}

export const JudgeResultsList = ({
  clickable = true,
  judgeResultsMap,
  labels,
  centroidsMap,
  centroidAssignments,
  isPollingAssignments,
  selectedResultId,
}: JudgeResultsListProps) => {
  // Lazy initialization - expand all sections by default
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(['residuals'])
  );

  const residualResultIds = useMemo(() => {
    // Get all judge result IDs from the judgeResultsMap
    const allResultIds = Object.keys(judgeResultsMap);

    // Get all judge result IDs that are assigned to any centroid as a Set for O(1) lookup
    const assignedResultIdsSet = new Set(
      Object.values(centroidAssignments).flat()
    );

    // Find result IDs that don't appear in any cluster assignment
    const residualIds = allResultIds.filter(
      (resultId) => !assignedResultIdsSet.has(resultId)
    );

    return residualIds;
  }, [judgeResultsMap, centroidAssignments]);

  const toggleSectionExpansion = useCallback(
    (sectionId: string) => {
      setExpandedSections((prev) => {
        const newExpanded = new Set(prev);
        if (newExpanded.has(sectionId)) {
          newExpanded.delete(sectionId);
        } else {
          newExpanded.add(sectionId);
        }
        return newExpanded;
      });
    },
    [centroidAssignments]
  );

  const labelAssignments = useMemo(() => {
    return labels?.map((label) => {
      return {
        label,
        judgeResultIds: Object.values(judgeResultsMap)
          .filter(
            (result: JudgeResultWithCitations) => result.output.label === label
          )
          .map((result) => result.id),
      };
    });
  }, [labels, judgeResultsMap]);

  const hasCentroids = centroidsMap && Object.keys(centroidsMap).length > 0;

  if (!hasCentroids && labelAssignments && labelAssignments.length > 0) {
    return (
      <div
        className={cn(
          'overflow-y-auto space-y-2 custom-scrollbar transition-all duration-200'
        )}
      >
        {/* Render results grouped by label */}
        {labelAssignments.map(({ label, judgeResultIds }) => {
          return (
            <CollapsibleResultsSection
              clickable={clickable}
              key={label}
              title={label}
              judgeResultIds={judgeResultIds}
              judgeResultsMap={judgeResultsMap}
              isPollingAssignments={isPollingAssignments}
              isExpanded={expandedSections.has(label)}
              onToggle={() => toggleSectionExpansion(label)}
              selectedResultId={selectedResultId}
            />
          );
        })}
      </div>
    );
  } else if (centroidsMap) {
    return (
      <div
        className={cn(
          'overflow-y-auto space-y-2 custom-scrollbar transition-all duration-200'
        )}
      >
        {/* Render centroid clusters */}
        {Object.keys(centroidsMap).map((centroidId) => {
          const judgeResultIds = centroidAssignments[centroidId] || [];
          const centroidTitle =
            centroidsMap[centroidId]?.centroid || `Cluster ${centroidId}`;

          return (
            <CollapsibleResultsSection
              clickable={clickable}
              key={centroidId}
              title={centroidTitle}
              judgeResultIds={judgeResultIds}
              judgeResultsMap={judgeResultsMap}
              isPollingAssignments={isPollingAssignments}
              isExpanded={expandedSections.has(centroidId)}
              onToggle={() => toggleSectionExpansion(centroidId)}
              selectedResultId={selectedResultId}
            />
          );
        })}

        {/* Render residuals */}
        {residualResultIds.length > 0 && (
          <CollapsibleResultsSection
            clickable={clickable}
            title={
              Object.keys(centroidsMap).length > 0 ? 'Residuals' : 'Results'
            }
            judgeResultIds={residualResultIds}
            judgeResultsMap={judgeResultsMap}
            isPollingAssignments={isPollingAssignments}
            isExpanded={expandedSections.has('residuals')}
            onToggle={() => toggleSectionExpansion('residuals')}
            selectedResultId={selectedResultId}
          />
        )}
      </div>
    );
  }
};
