'use client';

import {
  JudgeRunLabel,
  JudgeResultWithCitations,
} from '@/app/store/rubricSlice';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { JudgeResultCard } from './JudgeResultCard';
import { Loader2, ChevronDown, ChevronRight, Tag } from 'lucide-react';
import { useResultFilterControls } from '@/providers/use-result-filters';
import { cn } from '@/lib/utils';
import { RubricCentroid } from '@/app/api/rubricApi';
import AutoSizer from 'react-virtualized-auto-sizer';
import { VariableSizeList as List } from 'react-window';
import type { VariableSizeList as RVList } from 'react-window';
import { useRefinementTab } from '@/providers/use-refinement-tab';
import { useParams, useRouter } from 'next/navigation';

interface JudgeResultsListProps {
  centroids: RubricCentroid[];
  assignments: Record<string, string[]>;
  judgeResults: JudgeResultWithCitations[];
  judgeRunLabels: JudgeRunLabel[];
  isClusteringActive?: boolean;
  activeResultId?: string;
}

export const JudgeResultsList = ({
  centroids,
  assignments,
  judgeResults,
  judgeRunLabels,
  isClusteringActive,
  activeResultId,
}: JudgeResultsListProps) => {
  const { applyFilters, labeled } = useResultFilterControls();
  const filteredJudgeResultsList = useMemo(
    () => applyFilters(judgeResults, judgeRunLabels),
    [applyFilters, judgeResults, judgeRunLabels]
  );

  // Create result_id -> result map
  const judgeResultsMap = useMemo(() => {
    const map = new Map<string, JudgeResultWithCitations>();
    for (const result of filteredJudgeResultsList) {
      map.set(result.id, result);
    }
    return map;
  }, [filteredJudgeResultsList]);

  // Create agent_run_id -> label map
  const judgeRunLabelsMap = useMemo(() => {
    const map = new Map<string, JudgeRunLabel>();
    if (judgeRunLabels) {
      for (const label of judgeRunLabels) {
        map.set(label.agent_run_id, label);
      }
    }
    return map;
  }, [judgeRunLabels]);

  // Helper to group results by agent run
  const groupByAgentRun = useCallback((results: JudgeResultWithCitations[]) => {
    const grouped: Record<string, JudgeResultWithCitations[]> = {};
    for (const result of results) {
      if (!grouped[result.agent_run_id]) {
        grouped[result.agent_run_id] = [];
      }
      grouped[result.agent_run_id].push(result);
    }
    return grouped;
  }, []);

  // Keep track of which IDs have been assigned (to later compute resids)
  const assignedResultIdsSet = useMemo(() => {
    const allAssigned = Object.values(assignments).flat();
    return new Set(allAssigned);
  }, [assignments]);

  // Create centroid sections
  const centroidSections = useMemo(() => {
    return centroids.map((centroid) => {
      const resultIds = assignments[centroid.id] || [];
      const results = resultIds
        .map((rid) => judgeResultsMap.get(rid))
        .filter(Boolean) as JudgeResultWithCitations[];
      return {
        id: centroid.id,
        title: centroid.centroid || `Cluster ${centroid.id.slice(0, 8)}`,
        resultsByAgentRun: groupByAgentRun(results),
      };
    });
  }, [centroids, assignments, judgeResultsMap, groupByAgentRun]);

  // Create residual section
  const residualSection = useMemo(() => {
    const residualResults = filteredJudgeResultsList.filter(
      (r) => !assignedResultIdsSet.has(r.id)
    );
    if (residualResults.length === 0) return null;
    return {
      id: 'residuals',
      title: centroids.length > 0 ? 'Residuals' : 'Results',
      resultsByAgentRun: groupByAgentRun(residualResults),
    } as {
      id: string;
      title: string;
      resultsByAgentRun: Record<string, JudgeResultWithCitations[]>;
    } | null;
  }, [
    filteredJudgeResultsList,
    assignedResultIdsSet,
    centroids.length,
    groupByAgentRun,
  ]);

  // Create a map of labeled agent run ids
  // This is for the specific case of, no results but we want to display agent run id headers
  const getLabeledAgentRunsAsMap = useCallback(
    (existingMap: Record<string, JudgeResultWithCitations[]>) => {
      if (Object.keys(existingMap).length !== 0) {
        return existingMap;
      } else if (labeled) {
        return (
          judgeRunLabels?.reduce(
            (acc, label) => {
              acc[label.agent_run_id] = [];
              return acc;
            },
            {} as Record<string, JudgeResultWithCitations[]>
          ) || existingMap
        );
      }

      return existingMap;
    },
    [judgeRunLabels, labeled]
  );

  // If dropdowns are enabled and there are centroids, render clustered collapsible sections
  if (centroidSections.length > 0) {
    return (
      <div className="space-y-2 grow overflow-y-auto">
        {centroidSections.map((section) => (
          <ResultsSection
            key={section.id}
            sectionTitle={section.title}
            resultsByAgentRun={getLabeledAgentRunsAsMap(
              section.resultsByAgentRun
            )}
            isClusteringActive={isClusteringActive}
            judgeRunLabelsMap={judgeRunLabelsMap}
            activeResultId={activeResultId}
          />
        ))}
        {residualSection && (
          <ResultsSection
            key={residualSection.id}
            sectionTitle={residualSection.title}
            resultsByAgentRun={getLabeledAgentRunsAsMap(
              residualSection.resultsByAgentRun
            )}
            isClusteringActive={isClusteringActive}
            judgeRunLabelsMap={judgeRunLabelsMap}
            activeResultId={activeResultId}
          />
        )}
      </div>
    );
  }

  // Default: flat list grouped by agent run
  return (
    <ResultsSection
      resultsByAgentRun={getLabeledAgentRunsAsMap(
        groupByAgentRun(filteredJudgeResultsList)
      )}
      judgeRunLabelsMap={judgeRunLabelsMap}
      activeResultId={activeResultId}
    />
  );
};

interface ResultsSectionProps {
  resultsByAgentRun: Record<string, JudgeResultWithCitations[]>;
  judgeRunLabelsMap?: Map<string, JudgeRunLabel>;
  sectionTitle?: string;
  isClusteringActive?: boolean;
  navToTranscriptOnClick?: boolean;
  activeResultId?: string;
  fixHeight?: boolean;
}

export const ResultsSection = ({
  resultsByAgentRun,
  judgeRunLabelsMap = new Map(),
  sectionTitle,
  isClusteringActive = false,
  navToTranscriptOnClick = true,
  activeResultId,
}: ResultsSectionProps) => {
  const [expanded, setExpanded] = useState<boolean>(false);
  const uniqueRuns = Object.keys(resultsByAgentRun).length;

  // Flatten into a stable row model: one row per agent run
  const rows = useMemo(
    () => Object.entries(resultsByAgentRun),
    [resultsByAgentRun]
  );

  // react-window: keep per-row sizes with a light measurement
  const listRef = useRef<RVList>(null);
  const sizeMapRef = useRef<Map<number, number>>(new Map());
  const ESTIMATE = 160; // conservative average row height

  const getSize = useCallback(
    (index: number) => sizeMapRef.current.get(index) ?? ESTIMATE,
    []
  );

  const setSize = useCallback((index: number, size: number) => {
    const current = sizeMapRef.current.get(index);
    if (current !== size) {
      sizeMapRef.current.set(index, size);
      // Force react-window to re-render immediately so the new
      // measured height applies without waiting for a scroll event.
      listRef.current?.resetAfterIndex(index, true);
    }
  }, []);

  // Row renderer with inline measurement via ResizeObserver
  const Row = ({
    index,
    style,
  }: {
    index: number;
    style: React.CSSProperties;
  }) => {
    const [agentRunId, results] = rows[index];

    // Measure an inner wrapper (not the element with the react-window style)
    const measureRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
      const el = measureRef.current;
      if (!el) return;
      const measure = () => {
        const h = Math.ceil(el.getBoundingClientRect().height);
        setSize(index, h);
      };
      measure();
      const ro = new ResizeObserver(measure);
      ro.observe(el);
      return () => ro.disconnect();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [measureRef.current, index]);

    // Navigate to labeling area when clicking the tag
    const { setActiveTab } = useRefinementTab();
    const { collection_id: collectionId } = useParams<{
      collection_id: string;
    }>();
    const router = useRouter();

    const handleNavigateToLabeling = useCallback(
      (result: JudgeResultWithCitations) => {
        router.push(
          `/dashboard/${collectionId}/rubric/${result.rubric_id}/result/${result.id}`
        );
        setActiveTab('label');
      },
      [router]
    );

    return (
      <div style={style} className="group px-0">
        <div ref={measureRef} className="space-y-2 pb-2">
          <div className="text-xs px-2 bg-secondary text-muted-foreground justify-between py-1 font-medium rounded-sm flex items-center">
            <span>Agent Run {agentRunId.slice(0, 8)}</span>
            {results.length > 0 && navToTranscriptOnClick && (
              <button
                className="opacity-0 group-hover:opacity-100 transition-opacity duration-200 hover:text-primary"
                onClick={(e) => {
                  e.stopPropagation();
                  handleNavigateToLabeling(results[0]);
                }}
                title="Open labeling area"
              >
                <Tag size={14} />
              </button>
            )}
          </div>
          <div className="space-y-2">
            {results.map((judgeResult, idx) => (
              <div key={`${agentRunId}-${idx}`} id={`result-${judgeResult.id}`}>
                <JudgeResultCard
                  judgeResult={judgeResult}
                  judgeRunLabel={judgeRunLabelsMap.get(
                    judgeResult.agent_run_id
                  )}
                  navToTranscriptOnClick={navToTranscriptOnClick}
                  active={judgeResult.id === activeResultId}
                />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className={cn('space-y-2 grow', expanded && '!h-[500px]')}>
      {sectionTitle && (
        <div
          className="text-xs p-1.5 bg-background hover:bg-muted rounded border border-border flex cursor-pointer items-center gap-1.5"
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? (
            <ChevronDown className="h-3 w-3 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          )}
          <div className="flex-shrink-0 flex items-center">
            <span className="text-xs px-1.5 py-0.5 rounded-sm bg-secondary text-muted-foreground flex items-center min-w-[2rem] justify-center">
              {`${uniqueRuns} runs`}
              {isClusteringActive && (
                <Loader2 className="h-3 w-3 animate-spin ml-1" />
              )}
            </span>
          </div>
          <div className="flex-1 text-xs text-primary ml-1">
            <div className="flex items-center gap-2">{sectionTitle}</div>
          </div>
        </div>
      )}

      {((expanded && sectionTitle) || !sectionTitle) && (
        <AutoSizer className={sectionTitle && 'pl-4'}>
          {({ height, width }) => (
            <List
              ref={listRef}
              height={sectionTitle ? 400 : height}
              width={width}
              itemCount={rows.length}
              itemSize={getSize}
              estimatedItemSize={ESTIMATE}
              itemKey={(index: number) => rows[index]?.[0] ?? index}
            >
              {Row}
            </List>
          )}
        </AutoSizer>
      )}
    </div>
  );
};
