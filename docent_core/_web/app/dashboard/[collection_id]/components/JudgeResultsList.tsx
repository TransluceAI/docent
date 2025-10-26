'use client';

import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { useMemo, useState } from 'react';
import { Loader2, ChevronRight, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { RubricCentroid } from '@/app/api/rubricApi';
import VirtualResultsList from './VirtualResultsList';
import { SchemaDefinition } from '@/app/types/schema';
import { Label } from '@/app/api/labelApi';

interface JudgeResultsListProps {
  centroids: RubricCentroid[];
  assignments: Record<string, string[]>;
  filteredJudgeResultsList: JudgeResultWithCitations[];
  labels: Label[];
  isClusteringActive?: boolean;
  activeResultId?: string;
  schema: SchemaDefinition;
  activeLabelSet: any;
}

export const JudgeResultsList = ({
  centroids,
  assignments,
  filteredJudgeResultsList,
  labels,
  isClusteringActive,
  activeResultId,
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
        schema={schema}
        filteredJudgeResultsList={filteredJudgeResultsList}
        labels={labels}
        activeLabelSet={activeLabelSet}
      />
    );
  }

  // Default: flat list grouped by agent run
  return (
    <VirtualResultsList
      filteredJudgeResultsList={filteredJudgeResultsList}
      activeResultId={activeResultId}
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
  schema: SchemaDefinition;
  filteredJudgeResultsList: JudgeResultWithCitations[];
  labels: Label[];
  activeLabelSet: any;
}

const CentroidsList = ({
  assignments,
  centroids,
  isClusteringActive,
  activeResultId,
  schema,
  filteredJudgeResultsList,
  labels,
  activeLabelSet,
}: CentroidsListProps) => {
  // 1. Compute a result_id -> result map to quickly assign results to centroids
  const judgeResultsMap = useMemo(() => {
    const map = new Map<string, JudgeResultWithCitations>();
    for (const result of filteredJudgeResultsList) {
      map.set(result.id, result);
    }
    return map;
  }, [filteredJudgeResultsList]);

  // 2. Create the centroid sections by assigning results to centroids
  const centroidSections = useMemo(() => {
    return centroids.map((centroid) => {
      const resultIds = assignments[centroid.id] || [];
      const results = resultIds
        .map((rid) => judgeResultsMap.get(rid))
        .filter(Boolean) as JudgeResultWithCitations[];
      return {
        id: centroid.id,
        title: centroid.centroid || `Cluster ${centroid.id.slice(0, 8)}`,
        resultsByAgentRun: results,
      };
    });
  }, [centroids, assignments, judgeResultsMap]);

  // 3. Compute residuals by filtering out assigned results
  const residualSection = useMemo(() => {
    const allAssigned = Object.values(assignments).flat();
    const assignedResultIdsSet = new Set(allAssigned);
    const residualResults = filteredJudgeResultsList.filter(
      (r) => !assignedResultIdsSet.has(r.id)
    );
    return {
      id: 'residuals',
      title: centroids.length > 0 ? 'Residuals' : 'Results',
      resultsByAgentRun: residualResults,
    };
  }, [filteredJudgeResultsList, centroids.length, assignments]);

  // Keep track of the currently viewed centroid
  const [selectedCentroidId, setSelectedCentroidId] = useState<string | null>(
    null
  );

  // Display the centroid section if one is selected
  if (selectedCentroidId) {
    const selected = centroidSections.find((s) => s.id === selectedCentroidId);
    if (!selected) return null; // This should never happen

    return (
      <div className="flex flex-col min-h-0 grow gap-2">
        <button
          onClick={() => setSelectedCentroidId(null)}
          className="flex border items-center p-1.5 text-left gap-1.5 rounded hover:bg-muted"
          title="Back to clusters"
        >
          <div className="flex-1 text-xs text-primary ml-1 break-words">
            <span className="text-xs mr-2 px-1 inline-flex rounded-sm bg-secondary border text-muted-foreground flex">
              {`${selected.resultsByAgentRun.length} matches`}
              {isClusteringActive && (
                <Loader2 className="size-3 animate-spin ml-1" />
              )}
            </span>
            {selected.title}
          </div>
          <X className="size-3" />
        </button>

        <VirtualResultsList
          filteredJudgeResultsList={selected.resultsByAgentRun}
          activeResultId={activeResultId}
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
        const isDisabled = section.resultsByAgentRun.length === 0;
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
                {`${section.resultsByAgentRun.length} matches`}
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
