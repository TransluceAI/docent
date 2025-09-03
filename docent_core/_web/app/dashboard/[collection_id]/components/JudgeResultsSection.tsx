'use client';
import { useRouter } from 'next/navigation';
import { useAppSelector } from '@/app/store/hooks';
import {
  NavigateToCitation,
  TextWithCitations,
} from '@/components/CitationRenderer';
import { cn } from '@/lib/utils';
import {
  JudgeResultWithCitations,
  RubricCentroid,
} from '@/app/store/rubricSlice';
import { useCallback, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useCitationNavigation } from '../rubric/[rubric_id]/NavigateToCitationContext';
import posthog from 'posthog-js';
import { useCitationHighlight } from '@/lib/citationUtils';

interface CollapsibleResultsSectionProps {
  title: string;
  judgeResultIds: string[];
  judgeResultsMap: Record<string, JudgeResultWithCitations>;
  isPollingAssignments: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
  selectedResultId?: string;
}

const CollapsibleResultsSection = ({
  title,
  judgeResultIds,
  judgeResultsMap,
  isPollingAssignments,
  isExpanded = true,
  onToggle,
  selectedResultId,
}: CollapsibleResultsSectionProps) => {
  const [showUniqueAgentRuns, setShowUniqueAgentRuns] = useState(false);

  const toggleShowUniqueAgentRuns = () => {
    setShowUniqueAgentRuns(!showUniqueAgentRuns);
  };

  // Count only judge results with non-null values (what actually gets displayed)
  const resultHits = useMemo(() => {
    return judgeResultIds
      .map((id) => {
        const result = judgeResultsMap[id];
        return result && result.value ? result : null;
      })
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

  const AgentRunGroupHeader = ({
    agentRunId,
    resultCount,
  }: {
    agentRunId: string;
    resultCount: number;
  }) => {
    return (
      <div className="text-[10px] text-muted-foreground font-medium px-2 py-1 bg-secondary/50 rounded-sm mb-1 flex items-center justify-between">
        <span>Agent Run {agentRunId.slice(0, 8)}</span>
        <span className="text-[9px] bg-muted px-1.5 py-0.5 rounded">
          {resultCount}
        </span>
      </div>
    );
  };

  return (
    <div className="space-y-2">
      <div className="text-xs p-1.5 bg-background rounded border border-border flex items-center gap-1.5">
        {/* Expand/collapse button on the left */}
        <Button
          size="icon"
          variant="ghost"
          className="h-5 w-5 flex-shrink-0"
          onClick={onToggle}
        >
          {isExpanded ? (
            <ChevronDown className="h-3 w-3 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          )}
        </Button>

        {/* Count */}
        <div className="flex-shrink-0 flex items-center">
          <span
            className="text-xs px-1.5 py-0.5 rounded-sm bg-muted text-muted-foreground cursor-pointer flex items-center min-w-[2rem] justify-center hover:bg-muted/80 transition-colors"
            onClick={toggleShowUniqueAgentRuns}
          >
            {showUniqueAgentRuns
              ? `${uniqueAgentRunCount} runs`
              : `${resultHits.length} hits`}
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
              <AgentRunGroupHeader
                agentRunId={agentRunId}
                resultCount={results.length}
              />
              <div className="space-y-1">
                {results.map((judgeResult, idx) => (
                  <JudgeResultCard
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
  judgeResultsMap: Record<string, JudgeResultWithCitations>;
  centroidsMap: Record<string, RubricCentroid>;
  centroidAssignments: Record<string, string[]>;
  isPollingAssignments: boolean;
  selectedResultId?: string;
}

export const JudgeResultsList = ({
  judgeResultsMap,
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
          title={Object.keys(centroidsMap).length > 0 ? 'Residuals' : 'Results'}
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
};

interface JudgeResultCardProps {
  judgeResult: JudgeResultWithCitations;
  isActive: boolean;
}

export const JudgeResultCard = ({
  judgeResult,
  isActive,
}: JudgeResultCardProps) => {
  const router = useRouter();
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const { highlightCitation } = useCitationHighlight();
  const citationNav = useCitationNavigation();
  const resultText = judgeResult.value;
  if (!resultText) {
    return null;
  }
  const agentRunId = judgeResult.agent_run_id;
  const citations = judgeResult.citations || [];

  const handleNavigateToCitation: NavigateToCitation = ({
    citation,
    newTab,
  }) => {
    const url = `/dashboard/${collectionId}/rubric/${judgeResult.rubric_id}/result/${judgeResult.id}`;
    if (!isActive) {
      if (citationNav?.prepareForNavigation) {
        citationNav.prepareForNavigation(); // Clear current handler for proper timing
      }
      if (newTab) {
        window.open(url, '_blank');
      } else {
        router.push(url, { scroll: false } as any);
      }
    }
    if (citationNav?.navigateToCitation) {
      citationNav.navigateToCitation({ citation, newTab });
    }
    highlightCitation(citation);
  };

  return (
    <div
      className={cn(
        'group rounded-md p-1 border text-xs leading-snug mt-1 transition-colors cursor-pointer border',
        isActive
          ? 'border-indigo-border text-primary bg-indigo-bg'
          : 'bg-secondary/30 hover:bg-indigo-bg text-primary'
      )}
      onClick={(e) => {
        e.stopPropagation();
        const firstCitation = citations.length > 0 ? citations[0] : null;

        posthog.capture('rubric_result_clicked', {
          query: judgeResult.rubric_id,
          agent_run_id: agentRunId,
        });

        if (firstCitation) {
          handleNavigateToCitation({
            citation: firstCitation,
            newTab: e.metaKey || e.ctrlKey,
          });
        }
      }}
    >
      <div className="flex flex-col">
        <div className="flex items-start justify-between gap-2">
          <p
            className="mb-0.5 flex-1 wrap-anywhere"
            style={{ overflowWrap: 'anywhere' }}
          >
            <TextWithCitations
              text={resultText}
              citations={citations}
              onNavigate={handleNavigateToCitation}
            />
          </p>
        </div>
      </div>
    </div>
  );
};
