'use client';

import { useMemo, useState } from 'react';
import { Loader2, ChevronRight, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { AgentRunJudgeResults, RubricCentroid } from '@/app/api/rubricApi';
import VirtualResultsList from './VirtualResultsList';
import { SchemaDefinition } from '@/app/types/schema';
import { Label } from '@/app/api/labelApi';

interface JudgeResultsListProps {
  centroids: RubricCentroid[];
  assignments: Record<string, string[]>;
  agentRunResults: AgentRunJudgeResults[];
  labels: Label[];
  isClusteringActive?: boolean;
  activeResultId?: string;
  activeAgentRunId?: string;
  schema: SchemaDefinition;
  activeLabelSet: any;
}

export const JudgeResultsList = ({
  centroids,
  assignments,
  agentRunResults,
  labels,
  isClusteringActive,
  activeResultId,
  activeAgentRunId,
  schema,
  activeLabelSet,
}: JudgeResultsListProps) => {
  if (centroids.length > 0) {
    return (
      <CentroidsList
        assignments={assignments}
        centroids={centroids}
        isClusteringActive={isClusteringActive}
        activeResultId={activeResultId}
        activeAgentRunId={activeAgentRunId}
        schema={schema}
        agentRunResults={agentRunResults}
        labels={labels}
        activeLabelSet={activeLabelSet}
      />
    );
  }

  // Default: flat list grouped by agent run
  return (
    <VirtualResultsList
      agentRunResults={agentRunResults}
      activeResultId={activeResultId}
      activeAgentRunId={activeAgentRunId}
      schema={schema}
      labels={labels}
      activeLabelSet={activeLabelSet}
    />
  );
};

interface CentroidsListProps {
  assignments: Record<string, string[]>;
  centroids: RubricCentroid[];
  isClusteringActive?: boolean;
  activeResultId?: string;
  activeAgentRunId?: string;
  schema: SchemaDefinition;
  agentRunResults: AgentRunJudgeResults[];
  labels: Label[];
  activeLabelSet: any;
}

const CentroidsList = ({
  assignments,
  centroids,
  isClusteringActive,
  activeResultId,
  activeAgentRunId,
  schema,
  agentRunResults,
  labels,
  activeLabelSet,
}: CentroidsListProps) => {
  // Keep track of which IDs have been assigned (to later compute resids)
  const assignedResultIdsSet = useMemo(() => {
    const allAssigned = Object.values(assignments).flat();
    return new Set(allAssigned);
  }, [assignments]);

  // Create centroid sections
  // Only show the first result per agent run (matching what was clustered)
  const centroidSections = useMemo(() => {
    return centroids.map((centroid) => {
      const resultIds = assignments[centroid.id] || [];
      // Filter to only agent runs with results in this centroid, and take only the first result
      const agentRunsInCentroid = agentRunResults
        .map((arr) => ({
          ...arr,
          results: arr.results
            .filter((r) => resultIds.includes(r.id))
            .slice(0, 1),
        }))
        .filter((arr) => arr.results.length > 0);

      return {
        id: centroid.id,
        title: centroid.centroid || `Cluster ${centroid.id.slice(0, 8)}`,
        agentRunResults: agentRunsInCentroid,
      };
    });
  }, [centroids, assignments, agentRunResults]);

  // Compute residuals by filtering out assigned results
  // Only show the first result per agent run (matching what was clustered)
  const residualSection = useMemo(() => {
    const residualAgentRuns = agentRunResults
      .map((arr) => ({
        ...arr,
        results: arr.results
          .filter((r) => !assignedResultIdsSet.has(r.id))
          .slice(0, 1),
      }))
      .filter((arr) => arr.results.length > 0);

    return {
      id: 'residuals',
      title: centroids.length > 0 ? 'Residuals' : 'Results',
      agentRunResults: residualAgentRuns,
    };
  }, [agentRunResults, centroids.length, assignedResultIdsSet]);

  // Keep track of the currently viewed centroid
  const [selectedCentroidId, setSelectedCentroidId] = useState<string | null>(
    null
  );

  // Display the centroid section if one is selected
  if (selectedCentroidId) {
    const selected =
      selectedCentroidId === 'residuals'
        ? residualSection
        : centroidSections.find((s) => s.id === selectedCentroidId);
    if (!selected) {
      return null; // This should never happen
    }

    return (
      <div className="flex flex-col min-h-0 grow gap-2">
        <button
          onClick={() => setSelectedCentroidId(null)}
          className="flex border items-center p-1.5 text-left gap-1.5 rounded hover:bg-muted"
          title="Back to clusters"
        >
          <div className="flex-1 text-xs text-primary ml-1 break-words">
            <span className="text-xs mr-2 px-1 inline-flex rounded-sm bg-secondary border text-muted-foreground flex">
              {`${selected.agentRunResults.length} matches`}
              {isClusteringActive && (
                <Loader2 className="size-3 animate-spin ml-1" />
              )}
            </span>
            {selected.title}
          </div>
          <X className="size-3" />
        </button>

        <VirtualResultsList
          agentRunResults={selected.agentRunResults}
          activeResultId={activeResultId}
          activeAgentRunId={activeAgentRunId}
          schema={schema}
          labels={labels}
          activeLabelSet={activeLabelSet}
        />
      </div>
    );
  }

  // Else, display the list of centroids
  return (
    <div className="space-y-2 grow overflow-y-auto custom-scrollbar min-h-0">
      {[...centroidSections, residualSection].map((section) => {
        const isDisabled = section.agentRunResults.length === 0;
        return (
          <button
            key={section.id}
            type="button"
            className={cn(
              'text-left text-xs p-1.5 rounded border flex items-center gap-1.5 w-full bg-background text-primary border-border',
              isDisabled
                ? 'opacity-60 cursor-not-allowed'
                : 'hover:bg-muted cursor-pointer'
            )}
            onClick={() => {
              if (!isDisabled) setSelectedCentroidId(section.id);
            }}
            disabled={isDisabled}
          >
            <div className="flex-1 text-xs text-primary ml-1 break-words">
              <span className="text-xs mr-2 px-1 inline-flex rounded-sm bg-secondary border text-muted-foreground flex">
                {`${section.agentRunResults.length} matches`}
                {isClusteringActive && (
                  <Loader2 className="size-3 animate-spin ml-1" />
                )}
              </span>
              {section.title}
            </div>
            {!isDisabled && <ChevronRight className="size-3" />}
          </button>
        );
      })}
    </div>
  );
};
