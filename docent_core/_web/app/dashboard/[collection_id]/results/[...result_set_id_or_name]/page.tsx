'use client';

import React, { useState, useMemo, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';

import { BASE_URL } from '@/app/constants';
import UuidPill from '@/components/UuidPill';
import { type ResultFilter } from '@/app/utils/resultFilters';

import {
  useGetResultSetQuery,
  useGetResultsQuery,
  ResultResponse,
} from '@/app/api/resultSetApi';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import { SlidingPanelStack, SlidingPanel } from '@/components/sliding-panels';
import {
  ResultsTablePanelContent,
  AgentRunSlidingPanel,
  ResultDetailPanelContent,
  ResultDetailPanelContentById,
  type AgentRunPanelState,
} from './panels';

function isPending(result: ResultResponse): boolean {
  return result.output === null && result.error_json === null;
}

function isError(result: ResultResponse): boolean {
  return result.output === null && result.error_json !== null;
}

function isJobActive(jobStatus: string | null | undefined): boolean {
  return jobStatus === 'pending' || jobStatus === 'running';
}

const getColumnsStorageKey = (resultSetId: string) =>
  `result-set-table-columns-${resultSetId}`;

const getSortStorageKey = (resultSetId: string) =>
  `result-set-table-sort-${resultSetId}`;

export default function ResultSetDetailPage() {
  const params = useParams();
  const collectionId = params.collection_id as string;
  let resultSetIdOrNameParam = params.result_set_id_or_name;
  if (Array.isArray(resultSetIdOrNameParam)) {
    resultSetIdOrNameParam = resultSetIdOrNameParam.join('/');
  }
  const resultSetIdOrName = decodeURIComponent(
    resultSetIdOrNameParam as string
  );
  const hasWritePermission = useHasCollectionWritePermission();

  const {
    data: resultSet,
    isLoading: isLoadingResultSet,
    error: resultSetError,
    refetch: refetchResultSet,
  } = useGetResultSetQuery(
    { collectionId, resultSetIdOrName },
    { skip: !collectionId || !resultSetIdOrName }
  );

  const {
    data: fetchedResults = [],
    isLoading: isLoadingResults,
    error: resultsError,
  } = useGetResultsQuery(
    { collectionId, resultSetIdOrName, limit: 500 },
    { skip: !collectionId || !resultSetIdOrName }
  );

  const [localResults, setLocalResults] = useState<ResultResponse[]>([]);
  const [hasActiveJob, setHasActiveJob] = useState(false);

  const [selectedColumns, setSelectedColumns] = useState<string[]>([]);
  const [hasLoadedFromStorage, setHasLoadedFromStorage] = useState(false);

  const [sortField, setSortField] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  const [filters, setFilters] = useState<ResultFilter[]>([]);

  const handleSortChange = (
    field: string | null,
    direction: 'asc' | 'desc'
  ) => {
    setSortField(field);
    setSortDirection(direction);
  };

  useEffect(() => {
    setLocalResults(fetchedResults);
  }, [fetchedResults]);

  useEffect(() => {
    setHasActiveJob(isJobActive(resultSet?.job_status));
  }, [resultSet?.job_status]);

  useEffect(() => {
    if (!resultSet?.id || !hasActiveJob) return;

    const eventSource = new EventSource(
      `${BASE_URL}/rest/results/${collectionId}/stream/${encodeURIComponent(resultSetIdOrName)}`,
      { withCredentials: true }
    );

    eventSource.onmessage = (event) => {
      if (event.data === '[DONE]') {
        eventSource.close();
        setHasActiveJob(false);
        refetchResultSet();
        return;
      }

      try {
        const data = JSON.parse(event.data);

        if (data.type === 'result_completed') {
          setLocalResults((prev) =>
            prev.map((r) =>
              r.id === data.result_id
                ? {
                    ...r,
                    output: data.output ?? r.output,
                    error_json: data.error_json ?? r.error_json,
                    model: data.model ?? r.model,
                    input_tokens: data.input_tokens ?? r.input_tokens,
                    output_tokens: data.output_tokens ?? r.output_tokens,
                    cost_cents: data.cost_cents ?? r.cost_cents,
                  }
                : r
            )
          );
        } else if (data.type === 'job_completed') {
          setHasActiveJob(false);
          refetchResultSet();
        }
      } catch (e) {
        console.error('Error parsing SSE message:', e);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      setHasActiveJob(false);
      refetchResultSet();
    };

    return () => {
      eventSource.close();
    };
  }, [
    resultSet?.id,
    hasActiveJob,
    collectionId,
    resultSetIdOrName,
    refetchResultSet,
  ]);

  const results = localResults;

  const pendingCount = useMemo(() => {
    if (!hasActiveJob) return 0;
    return results.filter(isPending).length;
  }, [results, hasActiveJob]);
  const errorCount = useMemo(() => results.filter(isError).length, [results]);
  const completedCount = useMemo(
    () => results.filter((r) => r.output !== null).length,
    [results]
  );

  const columns = useMemo(() => {
    const flattenedColumns = new Set<string>();
    const autoJoinColumns = new Set<string>();

    // Output columns from schema
    const schemaProperties = resultSet?.output_schema?.properties;
    if (schemaProperties && typeof schemaProperties === 'object') {
      for (const outputKey of Object.keys(schemaProperties)) {
        flattenedColumns.add(`output.${outputKey}`);
      }
    }

    // user_metadata and joined columns from results
    for (const result of results) {
      if (result.user_metadata) {
        for (const metaKey of Object.keys(result.user_metadata)) {
          flattenedColumns.add(`user_metadata.${metaKey}`);
        }
      }
      if (result.joined) {
        for (const [joinKey, joinData] of Object.entries(result.joined)) {
          for (const field of Object.keys(joinData)) {
            autoJoinColumns.add(`joined.${joinKey}.${field}`);
          }
        }
      }
    }

    return {
      base: Array.from(flattenedColumns).sort(),
      autoJoin: Array.from(autoJoinColumns).sort(),
    };
  }, [results, resultSet?.output_schema]);

  const availableColumns = useMemo(
    () => [...columns.base, ...columns.autoJoin],
    [columns]
  );

  const autoJoinColumnsSet = useMemo(
    () => new Set(columns.autoJoin),
    [columns.autoJoin]
  );

  useEffect(() => {
    if (!resultSet?.id) return;

    const key = getColumnsStorageKey(resultSet.id);
    try {
      const persisted = localStorage.getItem(key);
      if (persisted) {
        const parsed = JSON.parse(persisted);
        if (Array.isArray(parsed)) {
          setSelectedColumns(parsed);
          setHasLoadedFromStorage(true);
          return;
        }
      }
    } catch {
      // Ignore localStorage errors
    }
    setHasLoadedFromStorage(true);
  }, [resultSet?.id]);

  useEffect(() => {
    if (
      hasLoadedFromStorage &&
      selectedColumns.length === 0 &&
      availableColumns.length > 0
    ) {
      setSelectedColumns(
        columns.base.length > 0 ? columns.base : columns.autoJoin
      );
    }
  }, [
    hasLoadedFromStorage,
    selectedColumns.length,
    availableColumns.length,
    columns.base,
    columns.autoJoin,
  ]);

  useEffect(() => {
    if (!resultSet?.id || !hasLoadedFromStorage) return;

    const key = getColumnsStorageKey(resultSet.id);
    try {
      localStorage.setItem(key, JSON.stringify(selectedColumns));
    } catch {
      // Ignore localStorage errors
    }
  }, [selectedColumns, resultSet?.id, hasLoadedFromStorage]);

  useEffect(() => {
    if (!resultSet?.id) return;

    const key = getSortStorageKey(resultSet.id);
    try {
      const persisted = localStorage.getItem(key);
      if (persisted) {
        const parsed = JSON.parse(persisted);
        if (parsed && typeof parsed === 'object') {
          if (parsed.field !== undefined) setSortField(parsed.field);
          if (parsed.direction === 'asc' || parsed.direction === 'desc') {
            setSortDirection(parsed.direction);
          }
        }
      }
    } catch {
      // Ignore localStorage errors
    }
  }, [resultSet?.id]);

  useEffect(() => {
    if (!resultSet?.id) return;

    const key = getSortStorageKey(resultSet.id);
    try {
      localStorage.setItem(
        key,
        JSON.stringify({ field: sortField, direction: sortDirection })
      );
    } catch {
      // Ignore localStorage errors
    }
  }, [sortField, sortDirection, resultSet?.id]);

  const isLoading = isLoadingResultSet || isLoadingResults;
  const error = resultSetError || resultsError;

  if (isLoading) {
    return (
      <div className="flex-1 flex bg-card min-h-0 shrink-0 border rounded-lg p-3">
        <div className="flex items-center justify-center w-full py-8">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error || !resultSet) {
    return (
      <div className="flex-1 flex bg-card min-h-0 shrink-0 border rounded-lg p-3">
        <div className="text-red-500 text-sm p-3 bg-red-50 rounded">
          Failed to load result set
        </div>
      </div>
    );
  }

  const isSingleResult = results.length === 1;
  const singleResult = isSingleResult ? results[0] : null;

  const initialPanels =
    isSingleResult && singleResult
      ? [
          {
            id: `result-${singleResult.id}`,
            type: 'result' as const,
            title: 'Result',
            resultId: singleResult.id,
            result: singleResult,
          },
        ]
      : [
          {
            id: 'table',
            type: 'table' as const,
            title: 'Results',
          },
        ];

  return (
    <div className="flex-1 flex min-h-0 shrink-0 border rounded-lg overflow-hidden bg-card">
      <SlidingPanelStack initialPanels={initialPanels}>
        {({ panelStack }) => (
          <>
            {panelStack.map((panel, index) => {
              const isRoot = index === 0;
              const isAlone = panelStack.length === 1;

              if (panel.type === 'table') {
                return (
                  <SlidingPanel
                    key={panel.id}
                    id={panel.id}
                    title={panel.title}
                    isRoot={isRoot}
                    isAlone={isAlone}
                    index={index}
                  >
                    <ResultsTablePanelContent
                      results={results}
                      hasActiveJob={hasActiveJob}
                      resultSet={resultSet}
                      completedCount={completedCount}
                      errorCount={errorCount}
                      pendingCount={pendingCount}
                      collectionId={collectionId}
                      resultSetIdOrName={resultSetIdOrName}
                      hasWritePermission={hasWritePermission}
                      availableColumns={availableColumns}
                      selectedColumns={selectedColumns}
                      onSelectedColumnsChange={setSelectedColumns}
                      autoJoinColumns={autoJoinColumnsSet}
                      sortField={sortField}
                      sortDirection={sortDirection}
                      onSortChange={handleSortChange}
                      filters={filters}
                      onFiltersChange={setFilters}
                    />
                  </SlidingPanel>
                );
              }

              if (panel.type === 'result' && panel.resultId) {
                return (
                  <SlidingPanel
                    key={panel.id}
                    id={panel.id}
                    title={panel.title}
                    isRoot={isRoot}
                    isAlone={isAlone}
                    index={index}
                    renderHeader={({ closeButton, title }) => (
                      <>
                        {closeButton}
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <h2 className="text-sm font-medium truncate min-w-0">
                            {title}
                          </h2>
                          <UuidPill uuid={panel.resultId} stopPropagation />
                        </div>
                      </>
                    )}
                  >
                    {(() => {
                      const liveResult = results.find(
                        (r) => r.id === panel.resultId
                      );
                      if (liveResult) {
                        return (
                          <ResultDetailPanelContent
                            result={liveResult}
                            hasActiveJob={hasActiveJob}
                            panelId={panel.id}
                          />
                        );
                      }
                      if (panel.collectionId) {
                        return (
                          <ResultDetailPanelContentById
                            resultId={panel.resultId}
                            collectionId={panel.collectionId}
                            hasActiveJob={hasActiveJob}
                            panelId={panel.id}
                          />
                        );
                      }
                      return null;
                    })()}
                  </SlidingPanel>
                );
              }

              if (
                panel.type === 'agent_run' &&
                panel.agentRunId &&
                panel.collectionId
              ) {
                return (
                  <AgentRunSlidingPanel
                    key={panel.id}
                    panel={panel as AgentRunPanelState}
                    index={index}
                    isRoot={isRoot}
                    isAlone={isAlone}
                  />
                );
              }

              return null;
            })}
          </>
        )}
      </SlidingPanelStack>
    </div>
  );
}
