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

import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { useAppDispatch, useAppSelector } from '../store/hooks';

import { AgentRunTable, MAX_SELECTED_COLUMNS } from './AgentRunTable';
import UploadRunsButton from './UploadRunsButton';
import UploadRunsDialog from './UploadRunsDialog';

import { TranscriptFilterControls } from './TranscriptFilterControls';
import DQLEditor, { DEFAULT_DQL_QUERY } from './DQLEditor';

import {
  setSorting,
  selectSortField,
  selectSortDirection,
} from '../store/collectionSlice';
import { useDebounce } from '@/hooks/use-debounce';
import { useDragAndDrop } from '@/hooks/use-drag-drop';
import {
  useGetAgentRunMetadataFieldsQuery,
  useGetAgentRunSortableFieldsQuery,
  collectionApi,
  useGetBaseFilterQuery,
} from '../api/collectionApi';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import { compareAgentRunColumnNames } from '@/lib/agentRunColumns';
import { INTERNAL_BASE_URL } from '@/app/constants';

import { navToAgentRun } from '@/lib/nav';
import { useRouter } from 'next/navigation';
import posthog from 'posthog-js';
import type { DqlExecuteResponse } from '@/app/types/dqlTypes';
import {
  type CollectionFilter,
  type ComplexFilter,
  type PrimitiveFilter,
} from '@/app/types/collectionTypes';
import { v4 as uuid4 } from 'uuid';

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
    if (key.startsWith('_')) {
      return;
    }
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

type CachedExperimentViewerState = {
  metadataData: Record<string, Record<string, unknown>>;
  scrollPosition?: number;
  dqlQuery?: string;
  dqlResult?: DqlExecuteResponse | null;
  dqlError?: string | null;
};

type MetadataFieldsById = Record<string, Set<string>>;

const experimentViewerCache = new Map<string, CachedExperimentViewerState>();

export default function ExperimentViewer({
  activeRunId,
}: {
  activeRunId?: string;
}) {
  const dispatch = useAppDispatch();

  // Get all state at the top level
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const hasWritePermission = useHasCollectionWritePermission();

  const cachedState = useMemo(() => {
    if (!collectionId) {
      return undefined;
    }
    return experimentViewerCache.get(collectionId);
  }, [collectionId]);

  const tabStorageKey = useMemo(() => {
    if (!collectionId) {
      return null;
    }
    return `experiment-viewer-tab-${collectionId}`;
  }, [collectionId]);

  const [activeTab, setActiveTab] = useState<'filters' | 'dql'>(() => {
    if (typeof window === 'undefined') {
      return 'filters';
    }
    const stored = tabStorageKey
      ? window.localStorage.getItem(tabStorageKey)
      : null;
    return stored === 'dql' ? 'dql' : 'filters';
  });

  useEffect(() => {
    if (!tabStorageKey) {
      setActiveTab('filters');
      return;
    }
    try {
      const stored = window.localStorage.getItem(tabStorageKey);
      setActiveTab(stored === 'dql' ? 'dql' : 'filters');
    } catch (error) {
      console.warn('Failed to restore experiment viewer tab state', error);
      setActiveTab('filters');
    }
  }, [tabStorageKey]);

  const handleTabChange = useCallback(
    (value: string) => {
      const nextValue: 'filters' | 'dql' = value === 'dql' ? 'dql' : 'filters';
      setActiveTab(nextValue);
      if (!tabStorageKey) {
        return;
      }
      try {
        window.localStorage.setItem(tabStorageKey, nextValue);
      } catch (error) {
        console.warn('Failed to persist experiment viewer tab state', error);
      }
    },
    [tabStorageKey]
  );

  const dqlStorageKey = useMemo(() => {
    if (!collectionId) {
      return null;
    }
    return `dql-editor-state-${collectionId}`;
  }, [collectionId]);

  const [dqlQuery, setDqlQuery] = useState<string>(
    () => cachedState?.dqlQuery ?? DEFAULT_DQL_QUERY
  );
  const [dqlResult, setDqlResult] = useState<DqlExecuteResponse | null>(
    () => cachedState?.dqlResult ?? null
  );
  const [dqlErrorMessage, setDqlErrorMessage] = useState<string | null>(
    () => cachedState?.dqlError ?? null
  );

  useEffect(() => {
    if (!dqlStorageKey) {
      return;
    }
    if (typeof window === 'undefined') {
      return;
    }
    try {
      const stored = window.localStorage.getItem(dqlStorageKey);
      if (!stored) {
        return;
      }
      const parsed = JSON.parse(stored) as {
        query?: unknown;
      };
      if (typeof parsed.query === 'string') {
        setDqlQuery(parsed.query);
      }
    } catch (error) {
      console.warn('Failed to restore DQL editor preferences', error);
    }
  }, [dqlStorageKey]);

  useEffect(() => {
    if (!dqlStorageKey || typeof window === 'undefined') {
      return;
    }
    try {
      const payload = JSON.stringify({
        query: dqlQuery,
      });
      window.localStorage.setItem(dqlStorageKey, payload);
    } catch (error) {
      console.warn('Failed to persist DQL editor preferences', error);
    }
  }, [dqlStorageKey, dqlQuery]);

  // Local state for scroll position
  const [experimentViewerScrollPosition, setExperimentViewerScrollPosition] =
    useState<number | undefined>(() => cachedState?.scrollPosition);

  const sortField = useAppSelector(selectSortField);
  const sortDirection = useAppSelector(selectSortDirection);

  const router = useRouter();

  const [metadataData, setMetadataData] = useState<
    Record<string, Record<string, unknown>>
  >(() => cachedState?.metadataData ?? {});
  const metadataDataRef = useRef(metadataData);
  metadataDataRef.current = metadataData;
  const [pendingMetadataFieldsById, setPendingMetadataFieldsById] =
    useState<MetadataFieldsById>({});
  const metadataRequestIdRef = useRef(0);
  const activeMetadataRequestRef = useRef<{
    id: number;
    abort?: () => void;
    pending: Map<string, Set<string>>;
    canceled: boolean;
  } | null>(null);

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
  const hasAutoSelectedColumnsRef = useRef(false);
  const [hasLoadedSortFromStorage, setHasLoadedSortFromStorage] =
    useState(false);
  const previousCollectionIdRef = useRef<string | undefined>(collectionId);

  // Load persisted column selection on mount and when collectionId changes
  useEffect(() => {
    hasAutoSelectedColumnsRef.current = false;

    const key = getColumnsStorageKey(collectionId);
    if (key) {
      try {
        const persisted = localStorage.getItem(key);
        if (persisted) {
          const parsedColumns = JSON.parse(persisted);
          if (Array.isArray(parsedColumns)) {
            // Migrate: truncate to MAX_SELECTED_COLUMNS if over limit
            const migratedColumns = parsedColumns.slice(
              0,
              MAX_SELECTED_COLUMNS
            );

            // Persist migrated value if truncated
            if (parsedColumns.length > MAX_SELECTED_COLUMNS) {
              localStorage.setItem(key, JSON.stringify(migratedColumns));
            }

            setSelectedColumns(migratedColumns);
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

  const debugAgentRunsRef = useRef(false);
  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    debugAgentRunsRef.current =
      window.localStorage.getItem('docent.debug.agent_runs') === '1';
  }, [collectionId]);

  const logAgentRunDebug = useCallback(
    (event: string, details?: Record<string, unknown>) => {
      if (!debugAgentRunsRef.current) {
        return;
      }
      if (details) {
        console.debug('[agent-runs]', event, details);
        return;
      }
      console.debug('[agent-runs]', event);
    },
    []
  );

  const [fetchAgentRunMetadata] =
    collectionApi.useLazyGetAgentRunMetadataQuery();
  const [fetchAgentRunIds] = collectionApi.useLazyGetAgentRunIdsQuery();
  const [postBaseFilter] = collectionApi.usePostBaseFilterMutation();
  const baseFilterRequestIdRef = useRef(0);
  const activeBaseFilterRequestRef = useRef<{
    id: number;
    abort?: () => void;
  } | null>(null);
  const [agentRunIds, setAgentRunIds] = useState<string[] | undefined>(
    undefined
  );
  const agentRunIdsRef = useRef(agentRunIds);
  agentRunIdsRef.current = agentRunIds;
  const [isAgentRunIdsLoading, setIsAgentRunIdsLoading] = useState(false);
  const [isAgentRunIdsFetching, setIsAgentRunIdsFetching] = useState(false);
  const agentRunIdsRequestIdRef = useRef(0);
  const activeAgentRunIdsRequestRef = useRef<{
    id: number;
    key: string;
    abort?: () => void;
  } | null>(null);

  const { data: metadataFieldsData } = useGetAgentRunMetadataFieldsQuery(
    collectionId!,
    { skip: !collectionId }
  );
  const agentRunMetadataFields = metadataFieldsData?.fields ?? [];

  const { data: sortableFieldsData } = useGetAgentRunSortableFieldsQuery(
    collectionId!,
    { skip: !collectionId }
  );

  const { data: serverBaseFilter } = useGetBaseFilterQuery(
    collectionId ? collectionId : skipToken
  );
  const [appliedBaseFilter, setAppliedBaseFilter] = useState<
    ComplexFilter | null | undefined
  >(undefined);
  const [draftBaseFilter, setDraftBaseFilter] = useState<
    ComplexFilter | null | undefined
  >(undefined);
  const appliedBaseFilterRef = useRef(appliedBaseFilter);
  appliedBaseFilterRef.current = appliedBaseFilter;

  const getBaseFilterKey = useCallback((filter: ComplexFilter | null) => {
    return filter ? JSON.stringify(filter) : 'none';
  }, []);

  useEffect(() => {
    if (serverBaseFilter === undefined) {
      return;
    }
    if (activeBaseFilterRequestRef.current) {
      return;
    }
    const currentKey =
      appliedBaseFilterRef.current === undefined
        ? null
        : getBaseFilterKey(appliedBaseFilterRef.current);
    const serverKey = getBaseFilterKey(serverBaseFilter);
    if (currentKey !== serverKey) {
      setAppliedBaseFilter(serverBaseFilter);
      setDraftBaseFilter(serverBaseFilter);
    }
  }, [getBaseFilterKey, serverBaseFilter]);

  const applyBaseFilter = useCallback(
    async (nextFilter: ComplexFilter | null) => {
      if (!collectionId) {
        return;
      }
      logAgentRunDebug('base_filter_apply', {
        nextFilterKey: getBaseFilterKey(nextFilter),
      });
      setDraftBaseFilter(nextFilter);
      if (
        appliedBaseFilterRef.current !== undefined &&
        getBaseFilterKey(appliedBaseFilterRef.current) ===
          getBaseFilterKey(nextFilter)
      ) {
        return;
      }
      if (activeBaseFilterRequestRef.current?.abort) {
        logAgentRunDebug('base_filter_abort', {
          requestId: activeBaseFilterRequestRef.current.id,
        });
        activeBaseFilterRequestRef.current.abort();
      }

      const requestId = baseFilterRequestIdRef.current + 1;
      baseFilterRequestIdRef.current = requestId;

      const triggerResult = postBaseFilter({
        collection_id: collectionId,
        filter: nextFilter,
      });

      activeBaseFilterRequestRef.current = {
        id: requestId,
        abort:
          typeof triggerResult.abort === 'function'
            ? () => triggerResult.abort()
            : undefined,
      };
      logAgentRunDebug('base_filter_request_start', {
        requestId,
        nextFilterKey: getBaseFilterKey(nextFilter),
      });

      try {
        const response = await triggerResult.unwrap();
        if (activeBaseFilterRequestRef.current?.id !== requestId) {
          return;
        }
        logAgentRunDebug('base_filter_request_success', {
          requestId,
          responseKey: getBaseFilterKey(response ?? null),
        });
        setAppliedBaseFilter(response ?? null);
        setDraftBaseFilter(response ?? null);
      } catch (error) {
        if (activeBaseFilterRequestRef.current?.id !== requestId) {
          return;
        }
        logAgentRunDebug('base_filter_request_error', { requestId });
        console.error('Failed to update base filter', error);
      } finally {
        if (activeBaseFilterRequestRef.current?.id === requestId) {
          activeBaseFilterRequestRef.current = null;
        }
      }
    },
    [collectionId, getBaseFilterKey, logAgentRunDebug, postBaseFilter]
  );

  const baseFilterKey = useMemo(() => {
    if (appliedBaseFilter === undefined) {
      return null;
    }
    return getBaseFilterKey(appliedBaseFilter);
  }, [appliedBaseFilter, getBaseFilterKey]);

  const agentRunIdsRequestKey = useMemo(() => {
    if (!collectionId || baseFilterKey === null) {
      return null;
    }
    return `${collectionId}:${sortField ?? ''}:${sortDirection}:${baseFilterKey}`;
  }, [collectionId, sortField, sortDirection, baseFilterKey]);

  useEffect(() => {
    if (!agentRunIdsRequestKey || !collectionId) {
      if (activeAgentRunIdsRequestRef.current?.abort) {
        logAgentRunDebug('agent_run_ids_abort', {
          requestId: activeAgentRunIdsRequestRef.current.id,
          key: activeAgentRunIdsRequestRef.current.key,
        });
        activeAgentRunIdsRequestRef.current.abort();
      }
      activeAgentRunIdsRequestRef.current = null;
      setAgentRunIds(undefined);
      setIsAgentRunIdsLoading(baseFilterKey === null);
      setIsAgentRunIdsFetching(false);
      logAgentRunDebug('agent_run_ids_skip', {
        collectionId,
        baseFilterKey,
      });
      return;
    }

    if (activeAgentRunIdsRequestRef.current?.key === agentRunIdsRequestKey) {
      return;
    }

    if (activeAgentRunIdsRequestRef.current?.abort) {
      logAgentRunDebug('agent_run_ids_abort', {
        requestId: activeAgentRunIdsRequestRef.current.id,
        key: activeAgentRunIdsRequestRef.current.key,
      });
      activeAgentRunIdsRequestRef.current.abort();
    }

    const requestId = agentRunIdsRequestIdRef.current + 1;
    agentRunIdsRequestIdRef.current = requestId;
    const triggerResult = fetchAgentRunIds({
      collectionId,
      sortField: sortField || undefined,
      sortDirection,
    });

    activeAgentRunIdsRequestRef.current = {
      id: requestId,
      key: agentRunIdsRequestKey,
      abort: () => triggerResult.abort(),
    };
    logAgentRunDebug('agent_run_ids_request_start', {
      requestId,
      key: agentRunIdsRequestKey,
    });
    setIsAgentRunIdsFetching(true);
    if (!agentRunIdsRef.current) {
      setIsAgentRunIdsLoading(true);
    }

    triggerResult
      .unwrap()
      .then((response) => {
        if (activeAgentRunIdsRequestRef.current?.id !== requestId) {
          return;
        }
        logAgentRunDebug('agent_run_ids_request_success', {
          requestId,
          count: response.length,
        });
        setAgentRunIds(response);
      })
      .catch((error) => {
        if (activeAgentRunIdsRequestRef.current?.id !== requestId) {
          return;
        }
        if (error?.name === 'AbortError') {
          logAgentRunDebug('agent_run_ids_request_aborted', { requestId });
          return;
        }
        logAgentRunDebug('agent_run_ids_request_error', { requestId });
        console.error('Failed to fetch agent run ids', error);
      })
      .finally(() => {
        if (activeAgentRunIdsRequestRef.current?.id !== requestId) {
          return;
        }
        logAgentRunDebug('agent_run_ids_request_done', { requestId });
        setIsAgentRunIdsFetching(false);
        setIsAgentRunIdsLoading(false);
        activeAgentRunIdsRequestRef.current = null;
      });
  }, [
    agentRunIdsRequestKey,
    collectionId,
    fetchAgentRunIds,
    sortDirection,
    sortField,
    logAgentRunDebug,
    baseFilterKey,
  ]);
  const isLoadingAgentRuns = isAgentRunIdsLoading;
  const isFetchingAgentRuns = isAgentRunIdsFetching;

  const isAgentRunQueryPending =
    appliedBaseFilter === undefined ||
    isLoadingAgentRuns ||
    isFetchingAgentRuns;

  const availableColumns = useMemo(() => {
    const filterableFieldNames = agentRunMetadataFields.map(
      (field) => field.name
    );
    const filteredFieldNames = filterableFieldNames.filter(
      (key) => key !== 'agent_run_id'
    );
    const uniqueColumns = Array.from(new Set(filteredFieldNames));

    // Sort in column display order:
    // non-config metadata, metadata.config.*, then created_at.
    return uniqueColumns.sort(compareAgentRunColumnNames);
  }, [agentRunMetadataFields]);

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
    setSelectedColumns(availableColumns.slice(0, MAX_SELECTED_COLUMNS));
  }, [
    availableColumns,
    hasLoadedFromStorage,
    selectedColumns.length,
    setSelectedColumns,
  ]);

  useEffect(() => {
    if (availableColumns.length === 0) {
      return;
    }
    setSelectedColumns((prev) => {
      const next = prev.filter((column) => availableColumns.includes(column));
      return next.length === prev.length ? prev : next;
    });
  }, [availableColumns]);

  const sortableColumns = useMemo(
    () =>
      new Set<string>(
        (sortableFieldsData?.fields ?? []).map((field) => field.name)
      ),
    [sortableFieldsData]
  );

  const filterableColumns = useMemo(
    () => new Set<string>(agentRunMetadataFields.map((field) => field.name)),
    [agentRunMetadataFields]
  );

  /**
   * Scrolling
   */
  const scrolledOnceRef = useRef(false);
  const [scrollPosition, setScrollPosition] = useState<number | undefined>(
    () => cachedState?.scrollPosition
  );
  const debouncedScrollPosition = useDebounce(scrollPosition, 100);

  useEffect(() => {
    if (collectionId === previousCollectionIdRef.current) {
      return;
    }

    if (!collectionId) {
      setMetadataData({});
      setPendingMetadataFieldsById({});
      setAppliedBaseFilter(undefined);
      setDraftBaseFilter(undefined);
      setAgentRunIds(undefined);
      setIsAgentRunIdsLoading(false);
      setIsAgentRunIdsFetching(false);
      if (activeBaseFilterRequestRef.current?.abort) {
        activeBaseFilterRequestRef.current.abort();
      }
      activeBaseFilterRequestRef.current = null;
      if (activeAgentRunIdsRequestRef.current?.abort) {
        activeAgentRunIdsRequestRef.current.abort();
      }
      activeAgentRunIdsRequestRef.current = null;
      setExperimentViewerScrollPosition(undefined);
      setScrollPosition(undefined);
      setDqlQuery(DEFAULT_DQL_QUERY);
      setDqlResult(null);
      setDqlErrorMessage(null);
      previousCollectionIdRef.current = collectionId;
      return;
    }

    const cached = experimentViewerCache.get(collectionId);
    setMetadataData(cached?.metadataData ?? {});
    // Always reset request tracking on navigation so missing metadata can be refetched.
    setPendingMetadataFieldsById({});
    setAppliedBaseFilter(undefined);
    setDraftBaseFilter(undefined);
    setAgentRunIds(undefined);
    setIsAgentRunIdsLoading(false);
    setIsAgentRunIdsFetching(false);
    if (activeBaseFilterRequestRef.current?.abort) {
      activeBaseFilterRequestRef.current.abort();
    }
    activeBaseFilterRequestRef.current = null;
    if (activeAgentRunIdsRequestRef.current?.abort) {
      activeAgentRunIdsRequestRef.current.abort();
    }
    activeAgentRunIdsRequestRef.current = null;
    setExperimentViewerScrollPosition(cached?.scrollPosition);
    setScrollPosition(cached?.scrollPosition);
    setDqlQuery(cached?.dqlQuery ?? DEFAULT_DQL_QUERY);
    setDqlResult(cached?.dqlResult ?? null);
    setDqlErrorMessage(cached?.dqlError ?? null);
    previousCollectionIdRef.current = collectionId;
  }, [collectionId]);

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
    setPendingMetadataFieldsById({});
    dispatch(
      collectionApi.util.invalidateTags([
        'AgentRunIds',
        'AgentRunMetadataFields',
      ])
    );
  }, [dispatch]);

  const updatePendingFields = useCallback(
    (mode: 'add' | 'remove', idsToFields: Map<string, Iterable<string>>) => {
      setPendingMetadataFieldsById((prev) => {
        const next: MetadataFieldsById = { ...prev };
        idsToFields.forEach((fields, id) => {
          const current = new Set(prev[id] ?? []);
          const fieldList = Array.from(fields);
          for (const field of fieldList) {
            if (mode === 'add') {
              current.add(field);
            } else {
              current.delete(field);
            }
          }
          if (current.size === 0) {
            delete next[id];
          } else {
            next[id] = current;
          }
        });
        if (debugAgentRunsRef.current) {
          let pendingFieldsCount = 0;
          Object.values(next).forEach((fields) => {
            pendingFieldsCount += fields.size;
          });
          logAgentRunDebug('metadata_pending_update', {
            mode,
            pendingIds: Object.keys(next).length,
            pendingFields: pendingFieldsCount,
          });
        }
        return next;
      });
    },
    [logAgentRunDebug]
  );

  const cancelActiveMetadataRequest = useCallback(() => {
    const activeRequest = activeMetadataRequestRef.current;
    if (!activeRequest) {
      return;
    }
    let pendingFieldCount = 0;
    activeRequest.pending.forEach((fields) => {
      pendingFieldCount += fields.size;
    });
    logAgentRunDebug('metadata_request_abort', {
      requestId: activeRequest.id,
      pendingIds: activeRequest.pending.size,
      pendingFields: pendingFieldCount,
    });
    activeRequest.canceled = true;
    if (activeRequest.abort) {
      activeRequest.abort();
    }
    updatePendingFields('remove', activeRequest.pending);
    activeMetadataRequestRef.current = null;
  }, [updatePendingFields]);

  useEffect(() => {
    if (!collectionId) {
      return;
    }

    experimentViewerCache.set(collectionId, {
      metadataData,
      scrollPosition: experimentViewerScrollPosition,
      dqlQuery,
      dqlResult,
      dqlError: dqlErrorMessage,
    });
  }, [
    collectionId,
    metadataData,
    experimentViewerScrollPosition,
    dqlQuery,
    dqlResult,
    dqlErrorMessage,
  ]);

  // Use debouncing to prevent too many updates
  useEffect(() => {
    if (debouncedScrollPosition !== undefined) {
      setExperimentViewerScrollPosition(debouncedScrollPosition);
    }
  }, [debouncedScrollPosition]);

  useEffect(() => {
    const node = scrollContainer;
    if (!node) {
      return;
    }

    if (
      experimentViewerScrollPosition !== undefined &&
      !scrolledOnceRef.current
    ) {
      node.scrollTop = experimentViewerScrollPosition;
      scrolledOnceRef.current = true;
    }

    const handleScroll = () => setScrollPosition(node.scrollTop);
    node.addEventListener('scroll', handleScroll);
    return () => {
      node.removeEventListener('scroll', handleScroll);
    };
  }, [
    experimentViewerScrollPosition,
    scrollContainer,
    setExperimentViewerScrollPosition,
  ]);

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
    async (ids: string[], options?: { force?: boolean; fields?: string[] }) => {
      if (!collectionId || !ids.length) {
        return {};
      }

      const requestedFields = (options?.fields ?? []).filter(
        (field) => field !== 'agent_run_id'
      );
      if (requestedFields.length === 0) {
        return {};
      }

      const uniqueIds = Array.from(new Set(ids));
      logAgentRunDebug('metadata_request_prepare', {
        idsCount: uniqueIds.length,
        fieldCount: requestedFields.length,
        force: options?.force ?? false,
      });
      const missingFieldsById = new Map<string, string[]>();
      const pendingById = new Map<string, Set<string>>();
      const currentMetadataData = metadataDataRef.current;

      uniqueIds.forEach((id) => {
        const loadedFields =
          (currentMetadataData[id]?._loaded_fields as
            | Set<string>
            | undefined) ?? new Set();
        const missingFields = requestedFields.filter((field) => {
          if (options?.force) {
            return true;
          }
          return !loadedFields.has(field);
        });
        if (missingFields.length > 0) {
          missingFieldsById.set(id, missingFields);
          pendingById.set(id, new Set(missingFields));
        }
      });

      if (missingFieldsById.size === 0) {
        logAgentRunDebug('metadata_request_skip', {
          reason: 'no_missing_fields',
          idsCount: uniqueIds.length,
          fieldCount: requestedFields.length,
        });
        return {};
      }
      const activeRequest = activeMetadataRequestRef.current;
      if (activeRequest) {
        let coveredByActive = true;
        const missingEntries = Array.from(missingFieldsById.entries());
        for (const [runId, fields] of missingEntries) {
          const pendingFields = activeRequest.pending.get(runId);
          if (!pendingFields) {
            coveredByActive = false;
            break;
          }
          for (const field of fields) {
            if (!pendingFields.has(field)) {
              coveredByActive = false;
              break;
            }
          }
          if (!coveredByActive) {
            break;
          }
        }
        if (coveredByActive) {
          logAgentRunDebug('metadata_request_skip', {
            reason: 'covered_by_active',
            requestId: activeRequest.id,
            idsCount: missingFieldsById.size,
            fieldCount: requestedFields.length,
          });
          return {};
        }
      }
      cancelActiveMetadataRequest();
      const requestId = metadataRequestIdRef.current + 1;
      metadataRequestIdRef.current = requestId;
      const requestState = {
        id: requestId,
        pending: pendingById,
        canceled: false,
        abort: undefined as (() => void) | undefined,
      };
      activeMetadataRequestRef.current = requestState;
      updatePendingFields('add', missingFieldsById);
      let missingFieldCount = 0;
      missingFieldsById.forEach((fields) => {
        missingFieldCount += fields.length;
      });
      logAgentRunDebug('metadata_request_start', {
        requestId,
        idsCount: missingFieldsById.size,
        fieldCount: requestedFields.length,
        missingFieldCount,
      });

      const runRequest = async () => {
        const fetched: Record<string, Record<string, unknown>> = {};
        const groupedRequests = new Map<
          string,
          { fields: string[]; ids: string[] }
        >();

        missingFieldsById.forEach((fields, id) => {
          const sortedFields = [...fields].sort();
          const key = sortedFields.join('|');
          const existing = groupedRequests.get(key);
          if (existing) {
            existing.ids.push(id);
          } else {
            groupedRequests.set(key, { fields: sortedFields, ids: [id] });
          }
        });

        try {
          const groupedRequestValues = Array.from(groupedRequests.values());
          for (const { fields, ids } of groupedRequestValues) {
            for (let i = 0; i < ids.length; i += METADATA_FETCH_BATCH_SIZE) {
              if (activeMetadataRequestRef.current?.id !== requestId) {
                logAgentRunDebug('metadata_request_stale', { requestId });
                return fetched;
              }

              const chunk = ids.slice(i, i + METADATA_FETCH_BATCH_SIZE);
              const triggerResult = fetchAgentRunMetadata({
                collectionId,
                agent_run_ids: chunk,
                fields: fields.length > 0 ? fields : undefined,
              });
              requestState.abort = () => triggerResult.abort();
              const response = await triggerResult.unwrap();

              if (activeMetadataRequestRef.current?.id !== requestId) {
                logAgentRunDebug('metadata_request_stale', { requestId });
                return fetched;
              }

              Object.entries(response).forEach(
                ([runId, structuredMetadata]) => {
                  const processed = processAgentRunMetadata(structuredMetadata);
                  const existing = metadataDataRef.current[runId] ?? {};
                  const existingLoadedFields =
                    (existing._loaded_fields as Set<string> | undefined) ??
                    new Set();
                  const mergedLoadedFields = new Set<string>();
                  existingLoadedFields.forEach((field) =>
                    mergedLoadedFields.add(field)
                  );
                  fields.forEach((field) => mergedLoadedFields.add(field));
                  fetched[runId] = {
                    ...existing,
                    ...processed,
                    _loaded_fields: mergedLoadedFields,
                  };
                }
              );

              setMetadataData((prev) => {
                const next = { ...prev };
                Object.entries(response).forEach(
                  ([runId, structuredMetadata]) => {
                    const processed =
                      processAgentRunMetadata(structuredMetadata);
                    const existing = next[runId] ?? {};
                    const existingLoadedFields =
                      (existing._loaded_fields as Set<string> | undefined) ??
                      new Set();
                    const mergedLoadedFields = new Set<string>();
                    existingLoadedFields.forEach((field) =>
                      mergedLoadedFields.add(field)
                    );
                    fields.forEach((field) => mergedLoadedFields.add(field));
                    next[runId] = {
                      ...existing,
                      ...processed,
                      _loaded_fields: mergedLoadedFields,
                    };
                  }
                );
                return next;
              });
              const completedFieldsById = new Map<string, string[]>();
              chunk.forEach((runId) => {
                const pendingFields = requestState.pending.get(runId);
                if (!pendingFields) {
                  return;
                }
                const completedFields = fields.filter((field) =>
                  pendingFields.has(field)
                );
                if (completedFields.length === 0) {
                  return;
                }
                completedFields.forEach((field) => pendingFields.delete(field));
                if (pendingFields.size === 0) {
                  requestState.pending.delete(runId);
                }
                completedFieldsById.set(runId, completedFields);
              });
              if (completedFieldsById.size > 0) {
                updatePendingFields('remove', completedFieldsById);
              }
            }
          }
        } catch (error) {
          if (requestState.canceled) {
            logAgentRunDebug('metadata_request_canceled', { requestId });
            return fetched;
          }
          console.error('Failed to fetch agent run metadata', error);
          logAgentRunDebug('metadata_request_error', { requestId });
          throw error;
        } finally {
          if (activeMetadataRequestRef.current?.id === requestId) {
            if (requestState.pending.size > 0) {
              const remainingFieldsById = new Map<string, string[]>();
              requestState.pending.forEach((fields, runId) => {
                if (fields.size > 0) {
                  remainingFieldsById.set(runId, Array.from(fields));
                }
              });
              if (remainingFieldsById.size > 0) {
                updatePendingFields('remove', remainingFieldsById);
              }
            }
            activeMetadataRequestRef.current = null;
          }
        }

        logAgentRunDebug('metadata_request_done', {
          requestId,
          fetchedCount: Object.keys(fetched).length,
        });
        return fetched;
      };

      return runRequest();
    },
    [
      cancelActiveMetadataRequest,
      collectionId,
      fetchAgentRunMetadata,
      updatePendingFields,
    ]
  );

  const handleSortingChange = useCallback(
    (field: string | null, direction: 'asc' | 'desc') => {
      dispatch(setSorting({ field, direction }));
    },
    [dispatch]
  );

  const normalizeFilterValue = useCallback((value: unknown) => {
    if (
      typeof value === 'string' ||
      typeof value === 'number' ||
      typeof value === 'boolean' ||
      value === null
    ) {
      return value;
    }

    if (value === undefined) {
      return undefined;
    }

    try {
      return JSON.stringify(value);
    } catch (error) {
      console.warn('Unable to serialize filter value', error);
      return String(value);
    }
  }, []);

  const dedupePrimitiveFilters = useCallback(
    (filters: CollectionFilter[]): CollectionFilter[] => {
      const seenFilterKeys = new Set<string>();
      return filters.reduceRight<CollectionFilter[]>((acc, filter) => {
        if (filter.type !== 'primitive') {
          return [filter, ...acc];
        }

        const primitiveFilter = filter as PrimitiveFilter;
        const keyPath = primitiveFilter.key_path?.join('.') || '';
        const filterKey = `${keyPath}:${primitiveFilter.value}:${primitiveFilter.op}`;

        if (seenFilterKeys.has(filterKey)) {
          return acc;
        }

        seenFilterKeys.add(filterKey);
        return [filter, ...acc];
      }, []);
    },
    []
  );

  const handleCreateFilterFromCell = useCallback(
    (columnKey: string, value: unknown, mode: 'append' | 'replace') => {
      if (!collectionId) {
        return;
      }

      const normalizedValue = normalizeFilterValue(value);
      if (normalizedValue === undefined) {
        return;
      }

      const isNullValue = normalizedValue === null;
      const nextFilter: PrimitiveFilter = {
        id: uuid4(),
        name: null,
        type: 'primitive',
        key_path: columnKey.split('.'),
        value: isNullValue ? 'null' : normalizedValue,
        op: isNullValue ? 'is' : '==',
        supports_sql: true,
        disabled: false,
      };

      const existingFilters =
        mode === 'append' ? (draftBaseFilter?.filters ?? []) : [];
      const mergedFilters = [...existingFilters, nextFilter];
      const dedupedFilters = dedupePrimitiveFilters(mergedFilters);

      const updatedFilter: ComplexFilter = {
        id: draftBaseFilter?.id ?? uuid4(),
        name: draftBaseFilter?.name ?? null,
        type: 'complex',
        filters: dedupedFilters,
        op: draftBaseFilter?.op ?? 'and',
        supports_sql: draftBaseFilter?.supports_sql ?? true,
        disabled: draftBaseFilter?.disabled,
      };

      void applyBaseFilter(updatedFilter);

      posthog.capture('agent_run_table_quick_filter', {
        collectionId,
        columnKey,
        mode,
      });
    },
    [
      applyBaseFilter,
      draftBaseFilter,
      collectionId,
      dedupePrimitiveFilters,
      normalizeFilterValue,
    ]
  );

  const handleRowMouseDown = useCallback(
    (runId: string, event: React.MouseEvent<HTMLTableRowElement>) => {
      event.stopPropagation();
      // Treat ctrl+click as context menu (common on macOS) to avoid navigating when opening quick filter menu.
      const isContextClick =
        event.button === 2 ||
        (event.button === 0 && event.ctrlKey && !event.metaKey);
      if (isContextClick) {
        event.preventDefault();
        return;
      }
      const openInNewTab = event.button === 1 || event.metaKey;

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
    agentRunIds === undefined && isAgentRunQueryPending ? (
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
    <div className="flex-1 flex flex-col h-full min-w-0">
      <Tabs
        value={activeTab}
        onValueChange={handleTabChange}
        className="flex-1 flex flex-col space-y-3 min-h-0"
      >
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
          <div className="flex flex-col">
            <div className="text-sm font-semibold">
              {activeTab === 'filters' && activeRunId
                ? `${agentRunIds?.length || 0} Runs`
                : activeTab === 'filters'
                  ? 'Agent Run Table'
                  : 'DQL Explorer'}
            </div>
            {!activeRunId && (
              <div className="text-xs text-muted-foreground">
                {activeTab === 'filters'
                  ? `${agentRunIds?.length || 0} agent runs matching the current view`
                  : 'Query collection data with Docent Query Language'}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div>
              <UploadRunsButton
                onImportSuccess={handleUploadSuccess}
                disabled={!hasWritePermission}
              />
            </div>
            <TabsList className="grid grid-cols-2 h-8">
              <TabsTrigger value="filters" className="py-0.5">
                Filters
              </TabsTrigger>
              <TabsTrigger value="dql" className="py-0.5">
                DQL
              </TabsTrigger>
            </TabsList>
          </div>
        </div>
        <TabsContent
          value="filters"
          className="mt-0 flex-1 flex flex-col gap-3 min-h-0 data-[state=active]:flex data-[state=inactive]:hidden"
        >
          <TranscriptFilterControls
            metadataData={metadataData}
            baseFilter={draftBaseFilter}
            onFiltersChange={applyBaseFilter}
          />
          <div className="flex-1 min-w-0 min-h-0 flex">
            <AgentRunTable
              agentRunIds={agentRunIds}
              metadataData={metadataData}
              availableColumns={availableColumns}
              selectedColumns={selectedColumns}
              onSelectedColumnsChange={setSelectedColumns}
              sortableColumns={sortableColumns}
              sortField={sortField}
              sortDirection={sortDirection}
              onSortChange={handleSortingChange}
              activeRunId={activeRunId}
              baseFilter={appliedBaseFilter ?? null}
              requestMetadataForIds={requestMetadataForIds}
              dropZoneHandlers={dropZoneHandlers}
              isDragActive={isDragActive}
              isOverDropZone={isOverDropZone}
              scrollContainerRef={setScrollContainer}
              isLoadingAgentRuns={isLoadingAgentRuns}
              isFetchingAgentRuns={isFetchingAgentRuns}
              onRowMouseDown={handleRowMouseDown}
              onCreateFilterFromCell={handleCreateFilterFromCell}
              filterableColumns={filterableColumns}
              emptyState={emptyStateContent}
            />
          </div>
        </TabsContent>
        <TabsContent
          value="dql"
          className="mt-0 flex-1 flex flex-col min-h-0 data-[state=active]:flex data-[state=inactive]:hidden"
        >
          <DQLEditor
            collectionId={collectionId ?? undefined}
            initialQuery={dqlQuery}
            onQueryChange={setDqlQuery}
            initialResult={dqlResult}
            onResultChange={setDqlResult}
            initialErrorMessage={dqlErrorMessage}
            onErrorMessageChange={setDqlErrorMessage}
          />
        </TabsContent>
      </Tabs>

      <UploadRunsDialog
        isOpen={uploadDialogOpen}
        onClose={handleUploadDialogClose}
        file={draggedFile}
        onImportSuccess={handleUploadSuccess}
      />
    </div>
  );
}
