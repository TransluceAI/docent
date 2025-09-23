'use client';

import { Loader2, Upload } from 'lucide-react';
import React, {
  useMemo,
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react';
import { skipToken } from '@reduxjs/toolkit/query';

import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

import { useAppDispatch, useAppSelector } from '../store/hooks';

import { ChartsArea } from './ChartsArea';
import { AgentRunTable } from './AgentRunTable';
import UploadRunsButton from './UploadRunsButton';
import UploadRunsDialog from './UploadRunsDialog';

import { TranscriptFilterControls } from './TranscriptFilterControls';

import { setExperimentViewerScrollPosition } from '../store/experimentViewerSlice';
import {
  setSorting,
  selectSortField,
  selectSortDirection,
} from '../store/collectionSlice';
import { useDebounce } from '@/hooks/use-debounce';
import { useDragAndDrop } from '@/hooks/use-drag-drop';
import {
  useGetAgentRunIdsQuery,
  useGetAgentRunMetadataFieldsQuery,
  useGetAgentRunSortableFieldsQuery,
  collectionApi,
} from '../api/collectionApi';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import { INTERNAL_BASE_URL } from '@/app/constants';

import { navToAgentRun } from '@/lib/nav';
import { useRouter } from 'next/navigation';
import posthog from 'posthog-js';

const processAgentRunMetadata = (
  structuredMetadata: Record<string, unknown> | null | undefined
): Record<string, unknown> => {
  const result: Record<string, unknown> = {};
  if (!structuredMetadata) {
    return result;
  }

  // Include the original structured metadata for direct access
  result._structured = structuredMetadata;

  Object.entries(structuredMetadata).forEach(([key, value]) => {
    if (key === 'metadata') {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        // Add top-level keys
        Object.entries(value as Record<string, unknown>).forEach(
          ([metaKey, metaValue]) => {
            const metadataKey = `metadata.${metaKey}`;
            result[metadataKey] = Array.isArray(metaValue)
              ? [...metaValue]
              : metaValue;
          }
        );
      }
    } else {
      // Direct keys like agent_run_id, created_at go directly to result
      result[key] = Array.isArray(value) ? [...value] : value;
    }
  });

  return result;
};

const METADATA_FETCH_BATCH_SIZE = 200;

export default function ExperimentViewer({
  activeRunId,
}: {
  activeRunId?: string;
}) {
  const dispatch = useAppDispatch();

  // Get all state at the top level
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const hasWritePermission = useHasCollectionWritePermission();

  const experimentViewerScrollPosition = useAppSelector(
    (state) => state.experimentViewer.experimentViewerScrollPosition
  );

  const sortField = useAppSelector(selectSortField);
  const sortDirection = useAppSelector(selectSortDirection);

  const router = useRouter();

  const [metadataData, setMetadataData] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [loadingMetadataIds, setLoadingMetadataIds] = useState<Set<string>>(
    new Set()
  );
  const [requestedMetadataIds, setRequestedMetadataIds] = useState<Set<string>>(
    new Set()
  );

  // Helper function to get localStorage key for selected columns
  const getColumnsStorageKey = (collectionId: string | undefined) => {
    return collectionId ? `agent-run-table-columns-${collectionId}` : null;
  };

  // Stores per-collection sort settings so sorting persists across reloads.
  const getSortStorageKey = (collectionId: string | undefined) => {
    return collectionId ? `agent-run-table-sort-${collectionId}` : null;
  };

  const [selectedColumns, setSelectedColumns] = useState<string[]>([]);
  const [hasLoadedFromStorage, setHasLoadedFromStorage] = useState(false);
  const [discoveredColumns, setDiscoveredColumns] = useState<Set<string>>(
    new Set()
  );
  const hasAutoSelectedColumnsRef = useRef(false);
  const [hasLoadedSortFromStorage, setHasLoadedSortFromStorage] =
    useState(false);

  // Load persisted column selection on mount and when collectionId changes
  useEffect(() => {
    // Clear discovered columns when collection changes
    setDiscoveredColumns(new Set());
    hasAutoSelectedColumnsRef.current = false;

    const key = getColumnsStorageKey(collectionId);
    if (key) {
      try {
        const persisted = localStorage.getItem(key);
        if (persisted) {
          const parsedColumns = JSON.parse(persisted);
          if (Array.isArray(parsedColumns)) {
            setSelectedColumns(parsedColumns);
            hasAutoSelectedColumnsRef.current = true;
            setHasLoadedFromStorage(true);
            return;
          }
        }
      } catch (error) {
        console.warn(
          `Failed to load persisted columns for collection ${collectionId}:`,
          error
        );
      }
    }

    // If no persisted selection or failed to load, mark as loaded so we can set defaults
    setHasLoadedFromStorage(true);
  }, [collectionId]);

  // Persist state changes
  useEffect(() => {
    const key = getColumnsStorageKey(collectionId);
    if (key && hasLoadedFromStorage) {
      try {
        localStorage.setItem(key, JSON.stringify(selectedColumns));
      } catch (error) {
        console.warn(
          `Failed to persist columns for collection ${collectionId}:`,
          error
        );
      }
    }
  }, [selectedColumns, collectionId, hasLoadedFromStorage]);

  useEffect(() => {
    setHasLoadedSortFromStorage(false);

    if (!collectionId) {
      setHasLoadedSortFromStorage(true);
      return;
    }

    const key = getSortStorageKey(collectionId);
    if (!key) {
      setHasLoadedSortFromStorage(true);
      return;
    }

    try {
      const persisted = localStorage.getItem(key);
      if (persisted) {
        const storedValue = JSON.parse(persisted);
        if (storedValue && typeof storedValue === 'object') {
          const rawField = (storedValue as { sortField?: unknown }).sortField;
          const rawDirection = (storedValue as { sortDirection?: unknown })
            .sortDirection;
          const parsedField = typeof rawField === 'string' ? rawField : null;
          const parsedDirection = rawDirection === 'desc' ? 'desc' : 'asc';
          dispatch(
            setSorting({ field: parsedField, direction: parsedDirection })
          );
        }
      }
    } catch (error) {
      console.warn(
        `Failed to load persisted sort for collection ${collectionId}:`,
        error
      );
    } finally {
      setHasLoadedSortFromStorage(true);
    }
  }, [collectionId, dispatch]);

  useEffect(() => {
    if (!hasLoadedSortFromStorage || !collectionId) {
      return;
    }

    const key = getSortStorageKey(collectionId);
    if (!key) {
      return;
    }

    try {
      localStorage.setItem(key, JSON.stringify({ sortField, sortDirection }));
    } catch (error) {
      console.warn(
        `Failed to persist sort for collection ${collectionId}:`,
        error
      );
    }
  }, [collectionId, sortField, sortDirection, hasLoadedSortFromStorage]);
  const [scrollContainer, setScrollContainer] = useState<HTMLDivElement | null>(
    null
  );

  const [fetchAgentRunMetadata] =
    collectionApi.useLazyGetAgentRunMetadataQuery();

  const { data: metadataFieldsData } = useGetAgentRunMetadataFieldsQuery(
    collectionId!,
    { skip: !collectionId }
  );

  const { data: sortableFieldsData } = useGetAgentRunSortableFieldsQuery(
    collectionId!,
    { skip: !collectionId }
  );

  // Fetch agent run IDs using RTK skipToken
  const { data: agentRunIds } = useGetAgentRunIdsQuery(
    collectionId
      ? {
          collectionId,
          sortField: sortField || undefined,
          sortDirection,
        }
      : skipToken
  );

  const derivedColumns = useMemo(() => {
    const sortableFieldNames = new Set(
      sortableFieldsData?.fields?.map((field) => field.name) ?? []
    );
    const keys = new Set<string>();

    // Only add top-level metadata keys that aren't already in sortable fields
    Object.values(metadataData).forEach((record) => {
      Object.keys(record).forEach((key) => {
        // Only add if it's a metadata.* key and not already in sortable fields
        if (key.startsWith('metadata.') && !sortableFieldNames.has(key)) {
          keys.add(key);
        }
      });
    });

    return Array.from(keys).sort();
  }, [metadataData, sortableFieldsData]);

  // Update discovered columns when new metadata is loaded
  useEffect(() => {
    const sortableFieldNames = new Set(
      sortableFieldsData?.fields?.map((field) => field.name) ?? []
    );
    const newDiscoveredColumns = new Set(discoveredColumns);

    // Add any new metadata columns that aren't already in sortable fields
    Object.values(metadataData).forEach((record) => {
      Object.keys(record).forEach((key) => {
        if (key.startsWith('metadata.') && !sortableFieldNames.has(key)) {
          newDiscoveredColumns.add(key);
        }
      });
    });

    // Only update if we found new columns
    if (newDiscoveredColumns.size !== discoveredColumns.size) {
      setDiscoveredColumns(newDiscoveredColumns);
    }
  }, [metadataData, sortableFieldsData, discoveredColumns]);

  const availableColumns = useMemo(() => {
    // Start with sortable fields from backend
    const sortableFieldNames =
      sortableFieldsData?.fields?.map((field) => field.name) ?? [];

    // Filter out agent_run_id since it's a hardcoded column that's always visible
    const filteredSortableFields = sortableFieldNames.filter(
      (key) => key !== 'agent_run_id'
    );

    // Combine sortable fields with both current derived columns and persisted discovered columns
    const allDiscoveredColumns = Array.from(discoveredColumns).sort();
    const allColumns = [
      ...filteredSortableFields,
      ...derivedColumns,
      ...allDiscoveredColumns,
    ];

    // Remove duplicates while preserving order
    const uniqueColumns = Array.from(new Set(allColumns));

    // Sort all columns alphabetically, but keep created_at at the end
    return uniqueColumns.sort((a, b) => {
      if (a === 'created_at') return 1;
      if (b === 'created_at') return -1;
      return a.localeCompare(b);
    });
  }, [derivedColumns, sortableFieldsData, discoveredColumns]);

  // Apply default columns exactly once per collection when no user preference exists.
  useEffect(() => {
    if (
      !hasLoadedFromStorage ||
      hasAutoSelectedColumnsRef.current ||
      availableColumns.length === 0 ||
      selectedColumns.length > 0
    ) {
      return;
    }

    hasAutoSelectedColumnsRef.current = true;
    setSelectedColumns(availableColumns);
  }, [
    availableColumns,
    hasLoadedFromStorage,
    selectedColumns.length,
    setSelectedColumns,
  ]);

  const sortableColumns = useMemo(
    () =>
      new Set<string>(
        (sortableFieldsData?.fields ?? []).map((field) => field.name)
      ),
    [sortableFieldsData]
  );

  useEffect(() => {
    setMetadataData({});
    setLoadingMetadataIds(new Set<string>());
  }, [collectionId]);

  /**
   * Scrolling
   */
  const scrolledOnceRef = useRef(false);
  const [scrollPosition, setScrollPosition] = useState<number | undefined>(
    undefined
  );
  const debouncedScrollPosition = useDebounce(scrollPosition, 100);

  // Upload state
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [draggedFile, setDraggedFile] = useState<File | null>(null);

  // Drag and drop functionality
  const handleFileDropped = useCallback((file: File) => {
    setDraggedFile(file);
    setUploadDialogOpen(true);
  }, []);

  const { isDragActive, isOverDropZone, dropZoneHandlers } =
    useDragAndDrop(handleFileDropped);

  const handleUploadDialogClose = useCallback(() => {
    setUploadDialogOpen(false);
    setDraggedFile(null);
  }, []);

  const handleUploadSuccess = useCallback(() => {
    setMetadataData({});
    setLoadingMetadataIds(new Set<string>());
    dispatch(
      collectionApi.util.invalidateTags([
        'AgentRunIds',
        'AgentRunMetadataFields',
      ])
    );
  }, [dispatch]);

  // Use debouncing to prevent too many updates
  useEffect(() => {
    if (debouncedScrollPosition) {
      dispatch(setExperimentViewerScrollPosition(debouncedScrollPosition));
    }
  }, [debouncedScrollPosition, dispatch]);

  useEffect(() => {
    const node = scrollContainer;
    if (!node) {
      return;
    }

    if (experimentViewerScrollPosition && !scrolledOnceRef.current) {
      node.scrollTop = experimentViewerScrollPosition;
      scrolledOnceRef.current = true;
    }

    const handleScroll = () => setScrollPosition(node.scrollTop);
    node.addEventListener('scroll', handleScroll);
    return () => {
      node.removeEventListener('scroll', handleScroll);
    };
  }, [experimentViewerScrollPosition, scrollContainer]);

  useEffect(() => {
    if (!collectionId) return;

    const ensureTelemetryProcessing = async () => {
      try {
        const telemetryUrl = `${INTERNAL_BASE_URL}/rest/telemetry/${collectionId}/ensure-telemetry-processing`;

        fetch(telemetryUrl, {
          method: 'POST',
          credentials: 'include',
        });
      } catch (error) {
        console.error(error);
      }
    };

    ensureTelemetryProcessing();
  }, [collectionId]);

  const requestMetadataForIds = useCallback(
    async (ids: string[]) => {
      if (!collectionId || !ids.length) {
        return;
      }

      const uniqueIds = Array.from(new Set(ids));
      const idsToFetch = uniqueIds.filter(
        (id) =>
          !metadataData[id] &&
          !loadingMetadataIds.has(id) &&
          !requestedMetadataIds.has(id)
      );

      if (!idsToFetch.length) {
        return;
      }

      // Mark these IDs as requested immediately to prevent duplicate requests
      setRequestedMetadataIds((prev) => {
        const next = new Set(prev);
        idsToFetch.forEach((id) => next.add(id));
        return next;
      });

      setLoadingMetadataIds((prev) => {
        const next = new Set(prev);
        idsToFetch.forEach((id) => next.add(id));
        return next;
      });

      try {
        for (let i = 0; i < idsToFetch.length; i += METADATA_FETCH_BATCH_SIZE) {
          const chunk = idsToFetch.slice(i, i + METADATA_FETCH_BATCH_SIZE);
          const response = await fetchAgentRunMetadata({
            collectionId,
            agent_run_ids: chunk,
          }).unwrap();

          setMetadataData((prev) => {
            const next = { ...prev };
            Object.entries(response).forEach(([runId, structuredMetadata]) => {
              next[runId] = processAgentRunMetadata(structuredMetadata);
            });
            return next;
          });
        }
      } catch (error) {
        console.error('Failed to fetch agent run metadata', error);
        // On error, remove from requested set so we can retry later
        setRequestedMetadataIds((prev) => {
          const next = new Set(prev);
          idsToFetch.forEach((id) => next.delete(id));
          return next;
        });
      } finally {
        setLoadingMetadataIds((prev) => {
          const next = new Set(prev);
          idsToFetch.forEach((id) => next.delete(id));
          return next;
        });
      }
    },
    [
      collectionId,
      fetchAgentRunMetadata,
      metadataData,
      loadingMetadataIds,
      requestedMetadataIds,
    ]
  );

  const handleSortingChange = useCallback(
    (field: string | null, direction: 'asc' | 'desc') => {
      dispatch(setSorting({ field, direction }));
    },
    [dispatch]
  );

  const handleRowMouseDown = useCallback(
    (runId: string, event: React.MouseEvent<HTMLTableRowElement>) => {
      event.stopPropagation();
      const openInNewTab = event.button === 1 || event.metaKey || event.ctrlKey;

      posthog.capture('agent_run_clicked', {
        agent_run_id: runId,
      });

      navToAgentRun(
        router,
        window,
        runId,
        undefined,
        undefined,
        collectionId,
        undefined,
        openInNewTab
      );
    },
    [collectionId, router]
  );

  const emptyStateContent =
    agentRunIds === undefined ? (
      <Loader2 size={16} className="animate-spin text-muted-foreground" />
    ) : (
      <div className="flex flex-col items-center space-y-3">
        <Upload className="h-12 w-12 text-muted-foreground" />
        <div className="text-muted-foreground">No agent runs found</div>
        <Button asChild variant="outline" size="sm">
          <a
            href="https://docs.transluce.org/en/latest/quickstart/"
            target="_blank"
            rel="noopener noreferrer"
          >
            See quickstart guide
          </a>
        </Button>
      </div>
    );

  return (
    <Card className="flex-1 flex flex-col h-full min-w-0">
      {/* Header with organization dropdown - always visible */}
      <div className="flex justify-between items-center shrink-0">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Chart Visualization</div>
          <div className="text-xs text-muted-foreground">
            Plot trends in your data
          </div>
        </div>
      </div>

      <ChartsArea />

      {/* Agent run list */}
      <div className="flex flex-row items-center justify-between">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Agent Run List</div>
          <div className="text-xs text-muted-foreground">
            {agentRunIds?.length || 0} agent runs matching the current view
          </div>
        </div>

        <UploadRunsButton
          onImportSuccess={handleUploadSuccess}
          disabled={!hasWritePermission}
        />
      </div>

      {/* Filtering controls */}
      <TranscriptFilterControls metadataData={metadataData} />

      {/* Agent run table */}
      <div className="flex-1 min-w-0 min-h-0 flex">
        <AgentRunTable
          agentRunIds={agentRunIds}
          metadataData={metadataData}
          loadingMetadataIds={loadingMetadataIds}
          requestedMetadataIds={requestedMetadataIds}
          availableColumns={availableColumns}
          selectedColumns={selectedColumns}
          onSelectedColumnsChange={setSelectedColumns}
          sortableColumns={sortableColumns}
          sortField={sortField}
          sortDirection={sortDirection}
          onSortChange={handleSortingChange}
          activeRunId={activeRunId}
          requestMetadataForIds={requestMetadataForIds}
          dropZoneHandlers={dropZoneHandlers}
          isDragActive={isDragActive}
          isOverDropZone={isOverDropZone}
          scrollContainerRef={setScrollContainer}
          onRowMouseDown={handleRowMouseDown}
          emptyState={emptyStateContent}
        />
      </div>

      <UploadRunsDialog
        isOpen={uploadDialogOpen}
        onClose={handleUploadDialogClose}
        file={draggedFile}
        onImportSuccess={handleUploadSuccess}
      />
    </Card>
  );
}
