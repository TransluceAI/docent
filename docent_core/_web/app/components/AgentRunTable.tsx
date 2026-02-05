'use client';

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent as ReactDragEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  type UIEvent as ReactUIEvent,
} from 'react';
import posthog from 'posthog-js';
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  Columns3,
  Copy,
  Loader2,
  FileCode,
  Upload,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import DownloadMenu from '@/app/components/DownloadMenu';
import { compareAgentRunColumnNames } from '@/lib/agentRunColumns';
import { cn } from '@/lib/utils';
import { useParams } from 'next/navigation';
import { Skeleton } from '@/components/ui/skeleton';
import { MultiCombobox, SingleCombobox } from './Combobox';
import { TableContainer } from './TableContainer';
import { isDateString, formatDateValue } from '@/lib/dateUtils';
import UuidPill from '@/components/UuidPill';
import {
  exportTabularData,
  type DelimitedFormat,
} from '@/app/utils/exportTable';
import { BASE_URL } from '@/app/constants';
import { useDownloadApiKey } from '@/app/hooks/use-download-api-key';
import {
  downloadPythonSample,
  fetchPythonSample,
  API_KEY_PLACEHOLDER,
} from '@/app/utils/pythonSamples';
import { toast } from 'sonner';
import { ComplexFilter } from '@/app/types/collectionTypes';
import { copyDqlToClipboard } from '@/app/utils/copyDql';
import { formatFilterFieldLabel } from '@/app/utils/formatMetadataField';
import { copyToClipboard } from '@/lib/utils';

export type AgentRunTableRow = {
  agentRunId: string;
};

const ROW_HEIGHT_PX = 36;
const OVERSCAN_COUNT = 50;
const METADATA_REQUEST_DEBOUNCE_MS = 200;
const SCROLL_IDLE_DEBOUNCE_MS = 150;
const MIN_SKELETON_ROW_COUNT = 12;
export const MAX_SELECTED_COLUMNS = 20;
export const MAX_EXPORT_ROWS = 50_000;

// Debounces metadata fetches with immediate cancellation on scroll.
// When the visible range changes, immediately cancels any in-flight request,
// then waits for the debounce period before starting a new request.
// This ensures rapid scrolling doesn't queue up stale requests.
function useDebouncedMetadataRequest(
  agentRunIds: string[] | undefined,
  metadataData: Record<string, Record<string, unknown>>,
  selectedColumns: string[],
  startIndex: number,
  endIndex: number,
  requestMetadataForIds: (
    ids: string[],
    options?: { force?: boolean; fields?: string[] }
  ) => Promise<Record<string, Record<string, unknown>>>,
  cancelMetadataRequest: (() => void) | undefined,
  isScrolling: boolean,
  isFetchingAgentRuns: boolean
) {
  const selectedMetadataFields = useMemo(
    () => selectedColumns.filter((column) => column !== 'agent_run_id'),
    [selectedColumns]
  );

  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastRangeKeyRef = useRef<string | null>(null);

  // Compute range key to detect when visible range changes
  const rangeKey = `${startIndex}-${endIndex}`;

  useEffect(() => {
    // Clear any pending debounce timer when unmounting
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    // When the visible range changes, immediately cancel in-flight requests
    if (lastRangeKeyRef.current !== rangeKey) {
      lastRangeKeyRef.current = rangeKey;

      // Cancel any in-flight request immediately on scroll
      if (cancelMetadataRequest) {
        cancelMetadataRequest();
      }

      // Clear any pending debounce timer
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
    }

    // Skip metadata requests while scrolling or while IDs are being fetched.
    // When IDs are being fetched, the visible range is about to change,
    // so any metadata request would be for stale IDs.
    if (isScrolling || isFetchingAgentRuns) {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
      return;
    }

    if (
      !agentRunIds ||
      !agentRunIds.length ||
      selectedMetadataFields.length === 0
    ) {
      return;
    }

    const prefetchStart = Math.max(startIndex - OVERSCAN_COUNT, 0);
    const prefetchEnd = Math.min(endIndex + OVERSCAN_COUNT, agentRunIds.length);
    const idsToCheck = agentRunIds.slice(prefetchStart, prefetchEnd);

    const needsFields = (runId: string) => {
      const data = metadataData[runId];
      if (!data) {
        return true;
      }
      const loadedFields = data._loaded_fields as Set<string> | undefined;
      if (!loadedFields) {
        return true;
      }
      return selectedMetadataFields.some((column) => !loadedFields.has(column));
    };

    const missingIds = idsToCheck.filter((id) => needsFields(id));

    if (missingIds.length === 0) {
      return;
    }

    // Debounce: wait before making the request
    // Clear any existing timer to prevent stale requests when dependencies change
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }
    debounceTimerRef.current = setTimeout(() => {
      debounceTimerRef.current = null;
      void requestMetadataForIds(missingIds, {
        fields: selectedMetadataFields,
      });
    }, METADATA_REQUEST_DEBOUNCE_MS);
  }, [
    agentRunIds,
    cancelMetadataRequest,
    endIndex,
    isFetchingAgentRuns,
    metadataData,
    rangeKey,
    requestMetadataForIds,
    selectedMetadataFields,
    startIndex,
    isScrolling,
  ]);
}

export interface AgentRunTableProps {
  agentRunIds?: string[];
  agentRunIdsOffset?: number;
  metadataData: Record<string, Record<string, unknown>>;
  availableColumns: string[];
  selectedColumns: string[];
  onSelectedColumnsChange: (columns: string[]) => void;
  sortableColumns: Set<string>;
  sortField: string | null;
  sortDirection: 'asc' | 'desc';
  collectionId?: string;
  baseFilter?: ComplexFilter | null;
  onSortChange: (field: string | null, direction: 'asc' | 'desc') => void;
  activeRunId?: string;
  onRowMouseDown: (
    runId: string,
    event: ReactMouseEvent<HTMLTableRowElement>
  ) => void;
  requestMetadataForIds: (
    ids: string[],
    options?: { force?: boolean; fields?: string[] }
  ) => Promise<Record<string, Record<string, unknown>>>;
  cancelMetadataRequest?: () => void;
  cancelLoadMoreIds?: () => void;
  dropZoneHandlers: {
    onDragOver: (event: ReactDragEvent<HTMLDivElement>) => void;
    onDragLeave: (event: ReactDragEvent<HTMLDivElement>) => void;
    onDrop: (event: ReactDragEvent<HTMLDivElement>) => void;
  };
  isDragActive: boolean;
  isOverDropZone: boolean;
  scrollContainerRef?: (node: HTMLDivElement | null) => void;
  emptyState?: ReactNode;
  isLoadingAgentRuns: boolean;
  isFetchingAgentRuns: boolean;
  onCreateFilterFromCell?: (
    columnKey: string,
    value: unknown,
    mode: 'append' | 'replace'
  ) => void;
  filterableColumns?: Set<string>;
  totalCount?: number;
  onLoadMoreIds?: (anchorIndex?: number) => void;
  fetchIdsForExport?: (
    limit: number
  ) => Promise<{ ids: string[]; truncated: boolean }>;
}

const formatCellValue = (value: unknown, keyExists: boolean): string => {
  // For missing keys, return empty string (standard CSV practice)
  if (!keyExists) {
    return '';
  }
  // For existing keys with null/undefined, return the string representation
  if (value === null) {
    return 'null';
  }
  if (value === undefined) {
    return 'undefined';
  }
  if (typeof value === 'string' && isDateString(value)) {
    return formatDateValue(value);
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch (error) {
      return String(value);
    }
  }
  return String(value);
};

const getNestedValue = (
  obj: Record<string, unknown>,
  path: string
): unknown => {
  const keys = path.split('.');
  let current: unknown = obj;

  for (const key of keys) {
    if (
      current === null ||
      current === undefined ||
      typeof current !== 'object'
    ) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[key];
  }

  return current;
};

const hasNestedKey = (obj: Record<string, unknown>, path: string): boolean => {
  const keys = path.split('.');
  let current: unknown = obj;

  for (let i = 0; i < keys.length; i++) {
    if (
      current === null ||
      current === undefined ||
      typeof current !== 'object'
    ) {
      return false;
    }
    const key = keys[i];
    if (!(key in (current as Record<string, unknown>))) {
      return false;
    }
    if (i < keys.length - 1) {
      current = (current as Record<string, unknown>)[key];
    }
  }

  return true;
};

const SortToggle = memo(function SortToggle({
  columnKey,
  label,
  sortable,
  currentSortField,
  currentSortDirection,
  onSortChange,
}: {
  columnKey: string;
  label: string;
  sortable: boolean;
  currentSortField: string | null;
  currentSortDirection: 'asc' | 'desc';
  onSortChange: (field: string | null, direction: 'asc' | 'desc') => void;
}) {
  const isActive = currentSortField === columnKey;

  const handleClick = useCallback(() => {
    if (!sortable) {
      return;
    }
    if (!isActive) {
      onSortChange(columnKey, 'asc');
      return;
    }
    if (currentSortDirection === 'asc') {
      onSortChange(columnKey, 'desc');
      return;
    }
    onSortChange(null, 'asc');
  }, [columnKey, currentSortDirection, isActive, onSortChange, sortable]);

  return (
    <button
      type="button"
      onClick={handleClick}
      className={cn(
        'flex items-center gap-1 text-xs font-medium text-muted-foreground',
        sortable ? 'hover:text-primary' : 'cursor-default'
      )}
      aria-pressed={isActive}
      disabled={!sortable}
    >
      <span>{label}</span>
      {sortable && (
        <span className="inline-flex items-center">
          {isActive ? (
            currentSortDirection === 'asc' ? (
              <ArrowUp className="h-3 w-3" />
            ) : (
              <ArrowDown className="h-3 w-3" />
            )
          ) : (
            <ArrowUpDown className="h-3 w-3 opacity-40" />
          )}
        </span>
      )}
    </button>
  );
});

interface AgentRunTableCellProps {
  cellId: string;
  columnIndex: number;
  columnKey: string;
  columnSize: number | undefined;
  columnMaxSize: number | undefined;
  isActive: boolean;
  runId: string;
  cellValue: unknown;
  isFilterable: boolean;
  hasFilterValue: boolean;
  onContextMenu?: (
    e: React.MouseEvent,
    rowId: string,
    columnKey: string,
    value: unknown
  ) => void;
  children: ReactNode;
}

const AgentRunTableCell = memo(function AgentRunTableCell({
  cellId,
  columnIndex,
  columnKey,
  columnSize,
  columnMaxSize,
  isActive,
  runId,
  cellValue,
  isFilterable,
  hasFilterValue,
  onContextMenu,
  children,
}: AgentRunTableCellProps) {
  const handleContextMenu = useCallback(
    (e: React.MouseEvent) => {
      if (onContextMenu && isFilterable && hasFilterValue) {
        e.preventDefault();
        onContextMenu(e, runId, columnKey, cellValue);
      }
    },
    [onContextMenu, isFilterable, hasFilterValue, runId, columnKey, cellValue]
  );

  return (
    <TableCell
      key={cellId}
      className={`py-1.5 ${
        columnIndex === 0
          ? `sticky left-0 z-10 ${
              isActive
                ? 'bg-indigo-bg/80 group-hover:bg-indigo-bg'
                : 'bg-background group-hover:bg-muted transition-colors duration-150'
            }`
          : ''
      }`}
      style={{
        width: columnSize,
        maxWidth: columnMaxSize || columnSize,
      }}
      onContextMenu={onContextMenu ? handleContextMenu : undefined}
    >
      {children}
    </TableCell>
  );
});

export const AgentRunTable = memo(function AgentRunTable({
  agentRunIds,
  agentRunIdsOffset,
  metadataData,
  availableColumns,
  selectedColumns,
  onSelectedColumnsChange,
  sortableColumns,
  sortField,
  sortDirection,
  collectionId,
  baseFilter,
  onSortChange,
  activeRunId,
  onRowMouseDown,
  requestMetadataForIds,
  cancelMetadataRequest,
  cancelLoadMoreIds,
  dropZoneHandlers,
  isDragActive,
  isOverDropZone,
  scrollContainerRef,
  emptyState,
  isLoadingAgentRuns,
  isFetchingAgentRuns,
  onCreateFilterFromCell,
  filterableColumns,
  totalCount,
  onLoadMoreIds,
  fetchIdsForExport,
}: AgentRunTableProps) {
  const internalScrollRef = useRef<HTMLDivElement | null>(null);
  // Ref to access metadataData in cell render functions without causing columns useMemo to re-run
  const metadataDataRef = useRef(metadataData);
  metadataDataRef.current = metadataData;
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(0);
  const [isScrolling, setIsScrolling] = useState(false);
  const isScrollingRef = useRef(false);
  const scrollIdleTimeoutRef = useRef<number | null>(null);
  const lastRequestedAnchorRef = useRef<number | null>(null);
  // https://nextjs.org/docs/messages/react-hydration-error#solution-1-using-useeffect-to-run-on-the-client-only
  const [hasMounted, setHasMounted] = useState(false);
  useEffect(() => {
    setHasMounted(true);
  }, []);
  useEffect(() => {
    return () => {
      if (
        copyResetTimeoutRef.current !== null &&
        typeof window !== 'undefined'
      ) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
      if (
        scrollIdleTimeoutRef.current !== null &&
        typeof window !== 'undefined'
      ) {
        window.clearTimeout(scrollIdleTimeoutRef.current);
      }
    };
  }, []);
  const [isExporting, setIsExporting] = useState(false);
  const { getApiKey: getDownloadApiKey, isLoading: isApiKeyLoading } =
    useDownloadApiKey();
  const [isDownloadingSample, setIsDownloadingSample] = useState(false);
  const [isCopyingDql, setIsCopyingDql] = useState(false);
  const params = useParams();
  const resolvedCollectionId =
    collectionId ??
    (Array.isArray(params?.collection_id)
      ? params?.collection_id[0]
      : (params as { collection_id?: string } | null | undefined)
          ?.collection_id);

  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(
    null
  );
  const [contextMenuCell, setContextMenuCell] = useState<{
    rowId: string;
    columnKey: string;
    value: unknown;
    x: number;
    y: number;
  } | null>(null);
  const [viewValueCell, setViewValueCell] = useState<{
    columnKey: string;
    value: unknown;
  } | null>(null);
  const [isValueCopied, setIsValueCopied] = useState(false);
  const copyResetTimeoutRef = useRef<number | null>(null);
  const skipNextRowClickRef = useRef(false);
  const columnSearchInputRef = useRef<HTMLInputElement | null>(null);
  const handleColumnsMenuOpenChange = useCallback((open: boolean) => {
    if (open) {
      // Focus the search input when the menu opens
      requestAnimationFrame(() => {
        columnSearchInputRef.current?.focus();
      });
    }
  }, []);

  const combinedScrollRef = useCallback(
    (node: HTMLDivElement | null) => {
      internalScrollRef.current = node;
      setScrollElement(node);
      if (scrollContainerRef) {
        scrollContainerRef(node);
      }
    },
    [scrollContainerRef]
  );

  useEffect(() => {
    const node = scrollElement;
    if (!node) {
      return;
    }

    const handleResize = () => {
      setContainerHeight(node.clientHeight);
    };

    handleResize();

    let resizeObserver: ResizeObserver | null = null;
    if (typeof window !== 'undefined') {
      if ('ResizeObserver' in window) {
        resizeObserver = new ResizeObserver(handleResize);
        resizeObserver.observe(node);
      } else {
        (window as Window).addEventListener('resize', handleResize);
      }
    }

    return () => {
      if (resizeObserver) {
        resizeObserver.disconnect();
      } else {
        window.removeEventListener('resize', handleResize);
      }
    };
  }, [scrollElement]);

  const handleScroll = useCallback(
    (event: ReactUIEvent<HTMLDivElement>) => {
      setScrollTop(event.currentTarget.scrollTop);

      if (cancelMetadataRequest) {
        cancelMetadataRequest();
      }
      if (cancelLoadMoreIds) {
        cancelLoadMoreIds();
      }
      lastRequestedAnchorRef.current = null;

      if (!isScrollingRef.current) {
        isScrollingRef.current = true;
        setIsScrolling(true);
      }
      if (
        scrollIdleTimeoutRef.current !== null &&
        typeof window !== 'undefined'
      ) {
        window.clearTimeout(scrollIdleTimeoutRef.current);
      }
      if (typeof window !== 'undefined') {
        scrollIdleTimeoutRef.current = window.setTimeout(() => {
          isScrollingRef.current = false;
          setIsScrolling(false);
          scrollIdleTimeoutRef.current = null;
        }, SCROLL_IDLE_DEBOUNCE_MS);
      }
    },
    [cancelLoadMoreIds, cancelMetadataRequest]
  );

  const data = useMemo<AgentRunTableRow[]>(() => {
    if (!agentRunIds) {
      return [];
    }
    return agentRunIds.map((agentRunId) => ({ agentRunId }));
  }, [agentRunIds]);

  const getCellValue = useCallback(
    (
      runId: string,
      columnKey: string,
      dataOverride?: Record<string, Record<string, unknown>>
    ): unknown => {
      if (columnKey === 'agent_run_id') {
        return runId;
      }

      const processedData = (dataOverride ?? metadataData)[runId];
      if (!processedData) {
        return undefined;
      }

      if (columnKey.startsWith('metadata.')) {
        const structured = processedData._structured as
          | Record<string, unknown>
          | undefined;
        if (structured?.metadata && typeof structured.metadata === 'object') {
          const metadataKey = columnKey.replace('metadata.', '');
          return getNestedValue(
            structured.metadata as Record<string, unknown>,
            metadataKey
          );
        }
      }

      return (processedData as Record<string, unknown>)[columnKey];
    },
    [metadataData]
  );

  const exportColumns = useMemo(() => {
    const unique = new Set<string>(['agent_run_id', ...selectedColumns]);
    return Array.from(unique);
  }, [selectedColumns]);

  const handleExport = useCallback(
    async (format: DelimitedFormat) => {
      if (!agentRunIds?.length) {
        return;
      }
      setIsExporting(true);
      try {
        // Fetch all IDs for export if the callback is provided, otherwise use loaded IDs
        let idsToExport = agentRunIds;
        if (fetchIdsForExport) {
          const result = await fetchIdsForExport(MAX_EXPORT_ROWS);
          idsToExport = result.ids;
          if (result.truncated) {
            toast.warning(
              `Export limited to ${MAX_EXPORT_ROWS.toLocaleString()} rows. Use Python/Notebook export for larger datasets.`
            );
          }
        }

        if (!idsToExport.length) {
          return;
        }

        const missingIds = idsToExport.filter((id) => !metadataData[id]);
        const fetchedMetadata = await requestMetadataForIds(missingIds, {
          force: true,
          fields: exportColumns,
        });
        const combinedMetadata = {
          ...metadataData,
          ...fetchedMetadata,
        };
        const rows = idsToExport.map((runId) =>
          exportColumns.map((columnKey) => {
            // Get the value
            const value = getCellValue(runId, columnKey, combinedMetadata);

            // Special case: agent_run_id always exists
            if (columnKey === 'agent_run_id') {
              return formatCellValue(value, true);
            }

            // Check if key exists in the metadata
            const processedData = combinedMetadata[runId];
            let keyExists = false;

            if (processedData) {
              if (columnKey.startsWith('metadata.')) {
                const structured = processedData._structured as
                  | Record<string, unknown>
                  | undefined;
                if (
                  structured?.metadata &&
                  typeof structured.metadata === 'object'
                ) {
                  const metadataKey = columnKey.replace('metadata.', '');
                  keyExists = hasNestedKey(
                    structured.metadata as Record<string, unknown>,
                    metadataKey
                  );
                }
              } else {
                keyExists = columnKey in processedData;
              }
            }

            return formatCellValue(value, keyExists);
          })
        );
        exportTabularData({
          columns: exportColumns,
          rows,
          format,
          filename: `agent-runs${
            resolvedCollectionId ? `-${resolvedCollectionId}` : ''
          }`,
        });
        posthog.capture('agent_run_table_download', {
          collectionId: resolvedCollectionId,
          format,
          rowCount: idsToExport.length,
          columnCount: exportColumns.length,
        });
      } catch (error) {
        console.error('Failed to export agent run table', error);
      } finally {
        setIsExporting(false);
      }
    },
    [
      agentRunIds,
      exportColumns,
      fetchIdsForExport,
      getCellValue,
      metadataData,
      requestMetadataForIds,
      resolvedCollectionId,
    ]
  );

  const handleDownloadSample = useCallback(
    async (format: 'python' | 'notebook') => {
      if (!agentRunIds?.length) {
        return;
      }
      if (!resolvedCollectionId) {
        toast.error('Open a collection before downloading a code sample.');
        return;
      }

      const eventName =
        format === 'notebook'
          ? 'agent_run_table_download_notebook_sample'
          : 'agent_run_table_download_python_sample';
      const errorDescription =
        format === 'notebook'
          ? 'Unable to generate a notebook sample for this table.'
          : 'Unable to generate a Python sample for this table.';

      try {
        setIsDownloadingSample(true);
        const apiKey = await getDownloadApiKey();
        await downloadPythonSample({
          type: 'agent_runs',
          api_key: apiKey,
          server_url: BASE_URL,
          collection_id: resolvedCollectionId,
          columns: exportColumns,
          sort_field: sortField ?? null,
          sort_direction: sortDirection,
          base_filter: baseFilter ?? null,
          format,
        });

        posthog.capture(eventName, {
          collectionId: resolvedCollectionId,
          rowCount: agentRunIds.length,
          columnCount: exportColumns.length,
        });
      } catch (error) {
        console.error('Failed to download agent run sample', error);
        toast.error(errorDescription);
      } finally {
        setIsDownloadingSample(false);
      }
    },
    [
      agentRunIds,
      baseFilter,
      exportColumns,
      getDownloadApiKey,
      resolvedCollectionId,
      sortDirection,
      sortField,
    ]
  );

  const handleCopyDql = useCallback(async () => {
    if (!agentRunIds?.length) {
      return;
    }
    if (!resolvedCollectionId) {
      toast.error('Open a collection before copying DQL.');
      return;
    }

    try {
      setIsCopyingDql(true);
      const sample = await fetchPythonSample({
        type: 'agent_runs',
        api_key: API_KEY_PLACEHOLDER,
        server_url: BASE_URL,
        collection_id: resolvedCollectionId,
        columns: exportColumns,
        sort_field: sortField ?? null,
        sort_direction: sortDirection,
        base_filter: baseFilter ?? null,
        format: 'python',
      });

      const didCopy = await copyDqlToClipboard(sample.dql_query);
      if (didCopy) {
        posthog.capture('agent_run_table_copy_dql', {
          collectionId: resolvedCollectionId,
          rowCount: agentRunIds.length,
          columnCount: exportColumns.length,
        });
      }
    } catch (error) {
      console.error('Failed to copy DQL for agent run table', error);
      toast.error('Unable to copy DQL for this table.');
    } finally {
      setIsCopyingDql(false);
    }
  }, [
    agentRunIds,
    baseFilter,
    exportColumns,
    resolvedCollectionId,
    sortDirection,
    sortField,
  ]);

  const skeletonRowCount = useMemo(() => {
    if (!containerHeight) {
      return MIN_SKELETON_ROW_COUNT;
    }
    return Math.max(
      MIN_SKELETON_ROW_COUNT,
      Math.ceil(containerHeight / ROW_HEIGHT_PX)
    );
  }, [containerHeight]);

  const columns = useMemo<ColumnDef<AgentRunTableRow, unknown>[]>(() => {
    const baseColumn: ColumnDef<AgentRunTableRow> = {
      id: 'agentRunId',
      header: () => (
        <SortToggle
          columnKey="agent_run_id"
          label="Agent Run"
          sortable={true}
          currentSortField={sortField}
          currentSortDirection={sortDirection}
          onSortChange={onSortChange}
        />
      ),
      cell: ({ row }) => {
        const runId = row.original.agentRunId;
        return <UuidPill uuid={runId} stopPropagation={true} />;
      },
      size: 160,
      maxSize: 300,
      meta: { align: 'left', key: 'agent_run_id' },
    };

    const metadataColumns = selectedColumns
      .filter((columnKey) => columnKey !== 'agent_run_id') // Exclude agent_run_id since it has a hardcoded column
      .sort(compareAgentRunColumnNames)
      .map<ColumnDef<AgentRunTableRow>>((columnKey) => ({
        id: columnKey,
        header: () => (
          <SortToggle
            columnKey={columnKey}
            label={formatFilterFieldLabel(columnKey)}
            sortable={sortableColumns.has(columnKey)}
            currentSortField={sortField}
            currentSortDirection={sortDirection}
            onSortChange={onSortChange}
          />
        ),
        cell: ({ row }) => {
          const runId = row.original.agentRunId;

          // Use ref to avoid re-creating columns when metadataData changes
          const processedData = metadataDataRef.current[runId];

          const loadedFields = processedData?._loaded_fields as
            | Set<string>
            | undefined;
          const isFieldLoaded = loadedFields?.has(columnKey) ?? false;

          if (!processedData || !isFieldLoaded) {
            return <Skeleton className="h-4 w-full" />;
          }

          // Access the value based on the column type
          let value: unknown;
          let keyExists: boolean;

          if (columnKey.startsWith('metadata.')) {
            // For metadata columns, try to access from the structured metadata first
            const structured = processedData._structured as
              | Record<string, unknown>
              | undefined;
            if (
              structured?.metadata &&
              typeof structured.metadata === 'object'
            ) {
              const metadataKey = columnKey.replace('metadata.', '');
              // Check if key exists in nested path
              keyExists = hasNestedKey(
                structured.metadata as Record<string, unknown>,
                metadataKey
              );
              // Only get value if key exists
              value = keyExists
                ? getNestedValue(
                    structured.metadata as Record<string, unknown>,
                    metadataKey
                  )
                : undefined;
            } else {
              keyExists = false;
            }
          } else {
            // For regular columns, check if key exists
            keyExists = columnKey in processedData;
            value = processedData[columnKey];
          }

          // Format the value - empty string if key doesn't exist, "null" if key exists with null value
          let text = formatCellValue(value, keyExists);
          if (columnKey === 'tag' && Array.isArray(value)) {
            text = value.join(', ');
          }
          if (columnKey.startsWith('rubric.') && keyExists) {
            const structured = processedData._structured as
              | Record<string, unknown>
              | undefined;
            const rubricCounts = structured?._rubric_counts as
              | Record<string, { matched: number; total: number }>
              | undefined;
            const count = rubricCounts?.[columnKey];
            if (count && count.total > 1) {
              text = `${text} (${count.matched}/${count.total})`;
            }
          }
          return (
            <span className="text-xs text-foreground truncate block">
              {text}
            </span>
          );
        },
        maxSize: 300,
        meta: { align: 'left', key: columnKey },
      }));

    return [baseColumn, ...metadataColumns];
  }, [
    onSortChange,
    selectedColumns,
    sortDirection,
    sortField,
    sortableColumns,
  ]);

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    state: {
      sorting:
        sortField !== null
          ? [{ id: sortField, desc: sortDirection === 'desc' }]
          : [],
    },
    onSortingChange: (updater) => {
      const nextState =
        typeof updater === 'function'
          ? updater(
              sortField !== null
                ? [{ id: sortField, desc: sortDirection === 'desc' }]
                : []
            )
          : updater;

      if (!nextState.length) {
        onSortChange(null, 'asc');
        return;
      }

      const [nextSort] = nextState;
      const nextDirection = nextSort.desc ? 'desc' : 'asc';
      if (nextSort.id !== sortField || nextDirection !== sortDirection) {
        onSortChange(nextSort.id, nextDirection);
      }
    },
  });

  const loadedRows = data.length;
  const effectiveIdsOffset = agentRunIdsOffset ?? 0;
  // Use totalCount when available; otherwise keep at least the current window size
  // to avoid collapsing the scrollbar while scrolling.
  const totalRows = Math.max(totalCount ?? 0, loadedRows + effectiveIdsOffset);
  const effectiveContainerHeight = containerHeight || 1;
  const visibleRowCount =
    Math.ceil(effectiveContainerHeight / ROW_HEIGHT_PX) + OVERSCAN_COUNT * 2;
  const scrollIndex = Math.max(Math.floor(scrollTop / ROW_HEIGHT_PX), 0);
  const rawStartIndex = Math.max(scrollIndex - OVERSCAN_COUNT, 0);
  const rawEndIndex = Math.min(rawStartIndex + visibleRowCount, totalRows);
  const localStartIndex = Math.max(rawStartIndex - effectiveIdsOffset, 0);
  const localEndIndex = Math.min(
    Math.max(rawEndIndex - effectiveIdsOffset, 0),
    loadedRows
  );
  const startIndex = localStartIndex;
  const endIndex = localEndIndex;

  // Request a new window of IDs when the scroll anchor leaves the loaded window.
  useEffect(() => {
    if (!onLoadMoreIds || isScrolling || isFetchingAgentRuns || !totalRows) {
      return;
    }

    const windowStart = effectiveIdsOffset;
    const windowEnd = effectiveIdsOffset + loadedRows;
    const needsWindow = scrollIndex < windowStart || scrollIndex >= windowEnd;

    if (!needsWindow) {
      lastRequestedAnchorRef.current = null;
      return;
    }

    if (lastRequestedAnchorRef.current === scrollIndex) {
      return;
    }

    lastRequestedAnchorRef.current = scrollIndex;
    onLoadMoreIds(scrollIndex);
  }, [
    effectiveIdsOffset,
    scrollIndex,
    loadedRows,
    isScrolling,
    isFetchingAgentRuns,
    onLoadMoreIds,
    totalRows,
  ]);

  // Use debounced metadata request hook
  useDebouncedMetadataRequest(
    agentRunIds,
    metadataData,
    selectedColumns,
    startIndex,
    endIndex,
    requestMetadataForIds,
    cancelMetadataRequest,
    isScrolling,
    isFetchingAgentRuns
  );

  // When no rows are rendered (startIndex >= endIndex), the padding calculation
  // must still maintain total height = totalRows * ROW_HEIGHT_PX to prevent
  // the scrollbar from jumping. Use scroll position as the anchor in this case.
  const hasRowsToRender = startIndex < endIndex;
  const firstRenderedIndex = hasRowsToRender
    ? effectiveIdsOffset + startIndex
    : Math.min(scrollIndex, totalRows);
  const lastRenderedIndex = hasRowsToRender
    ? effectiveIdsOffset + endIndex
    : firstRenderedIndex;

  const paddingTop = firstRenderedIndex * ROW_HEIGHT_PX;
  const paddingBottom = Math.max(
    (totalRows - lastRenderedIndex) * ROW_HEIGHT_PX,
    0
  );

  const columnCount = columns.length || 1;
  const hasRows = totalRows > 0;
  // Show skeleton rows during SSR/hydration (before mount) to prevent hydration mismatch,
  // or when actually loading with no data
  const showSkeletonRows = !hasMounted || (isLoadingAgentRuns && !hasRows);
  const showFetchOverlay = hasMounted && isFetchingAgentRuns && hasRows;
  const visibleColumns = table.getVisibleLeafColumns();
  const isAtColumnLimit = selectedColumns.length >= MAX_SELECTED_COLUMNS;

  const handleSelectAll = useCallback(() => {
    posthog.capture('agent_run_table_columns_select_all', {
      collectionId: resolvedCollectionId,
    });

    // Sort columns alphabetically and take up to MAX_SELECTED_COLUMNS
    const sortedColumns = [...availableColumns].sort(
      compareAgentRunColumnNames
    );
    const columnsToSelect = sortedColumns.slice(0, MAX_SELECTED_COLUMNS);

    onSelectedColumnsChange(columnsToSelect);

    // Show toast if selection was limited
    if (availableColumns.length > MAX_SELECTED_COLUMNS) {
      toast.info(
        `Selected first ${MAX_SELECTED_COLUMNS} of ${availableColumns.length} columns. Maximum limit is ${MAX_SELECTED_COLUMNS}.`
      );
    }
  }, [availableColumns, onSelectedColumnsChange, resolvedCollectionId]);

  const handleClearAll = useCallback(() => {
    posthog.capture('agent_run_table_columns_clear_all', {
      collectionId: resolvedCollectionId,
    });

    onSelectedColumnsChange([]);
  }, [onSelectedColumnsChange, resolvedCollectionId]);

  const handleColumnsChange = useCallback(
    (nextColumns: string[]) => {
      // Guard: prevent exceeding the column limit
      if (nextColumns.length > MAX_SELECTED_COLUMNS) {
        return;
      }

      const added = nextColumns.find(
        (column) => !selectedColumns.includes(column)
      );
      const removed = selectedColumns.find(
        (column) => !nextColumns.includes(column)
      );
      const changedColumn = added ?? removed;

      if (changedColumn) {
        posthog.capture('agent_run_table_column_toggled', {
          collectionId: resolvedCollectionId,
          column: changedColumn,
          action: added ? 'add' : 'remove',
        });
      }

      onSelectedColumnsChange(nextColumns);
    },
    [onSelectedColumnsChange, resolvedCollectionId, selectedColumns]
  );

  // Sort controls handlers
  const handleFieldChange = useCallback(
    (field: string) => {
      posthog.capture('agent_run_table_sort_changed', {
        collectionId: resolvedCollectionId,
        field: field === 'none' ? null : field,
        direction: sortDirection,
      });

      if (field === 'none') {
        onSortChange(null, 'asc');
      } else {
        onSortChange(field, sortDirection);
      }
    },
    [onSortChange, resolvedCollectionId, sortDirection]
  );

  const handleDirectionChange = useCallback(() => {
    if (sortField) {
      const newDirection = sortDirection === 'asc' ? 'desc' : 'asc';
      posthog.capture('agent_run_table_sort_changed', {
        collectionId: resolvedCollectionId,
        field: sortField,
        direction: newDirection,
      });

      onSortChange(sortField, newDirection);
    }
  }, [onSortChange, resolvedCollectionId, sortField, sortDirection]);

  const handleCellContextMenu = useCallback(
    (e: React.MouseEvent, rowId: string, columnKey: string, value: unknown) => {
      e.preventDefault();
      setContextMenuCell({
        rowId,
        columnKey,
        value,
        x: e.clientX,
        y: e.clientY,
      });
    },
    []
  );

  const handleContextMenuClose = useCallback(() => {
    setContextMenuCell(null);
  }, []);

  const handleViewValue = useCallback((columnKey: string, value: unknown) => {
    setViewValueCell({ columnKey, value });
  }, []);

  const handleCopyValue = useCallback(async (text: string) => {
    const success = await copyToClipboard(text);
    if (!success) {
      return;
    }
    setIsValueCopied(true);
    if (copyResetTimeoutRef.current !== null && typeof window !== 'undefined') {
      window.clearTimeout(copyResetTimeoutRef.current);
    }
    if (typeof window !== 'undefined') {
      copyResetTimeoutRef.current = window.setTimeout(() => {
        setIsValueCopied(false);
        copyResetTimeoutRef.current = null;
      }, 2000);
    }
  }, []);

  const viewValueLabel = useMemo(() => {
    if (!viewValueCell) {
      return '';
    }
    return formatFilterFieldLabel(viewValueCell.columnKey);
  }, [viewValueCell]);

  const viewValueText = useMemo(() => {
    if (!viewValueCell) {
      return '';
    }
    const value = viewValueCell.value;
    if (value === null) {
      return 'null';
    }
    if (value === undefined) {
      return '';
    }
    if (typeof value === 'string') {
      return value;
    }
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value);
    }
  }, [viewValueCell]);

  // Prepare sortable fields for the select
  const sortOptions = useMemo(
    () => [
      { value: 'none', label: 'No sorting' },
      ...Array.from(sortableColumns).map((field) => ({
        value: field,
        label: formatFilterFieldLabel(field),
      })),
    ],
    [sortableColumns]
  );

  const columnOptions = useMemo(
    () =>
      availableColumns.map((column) => {
        const isSelected = selectedColumns.includes(column);
        const shouldDisable = isAtColumnLimit && !isSelected;
        const label = formatFilterFieldLabel(column);
        return {
          value: column,
          label,
          disabled: shouldDisable,
        };
      }),
    [availableColumns, selectedColumns, isAtColumnLimit]
  );

  const columnLimitWarning = useMemo(() => {
    if (!isAtColumnLimit) {
      return null;
    }
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-xs bg-amber-50 border-b border-amber-200 text-amber-800">
        <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
        <span>
          Maximum of {MAX_SELECTED_COLUMNS} columns selected. Deselect a column
          to add another.
        </span>
      </div>
    );
  }, [isAtColumnLimit]);

  const columnActionItems = useMemo(
    () => [
      {
        key: 'select_all',
        label:
          availableColumns.length > MAX_SELECTED_COLUMNS
            ? `Select first ${MAX_SELECTED_COLUMNS}`
            : 'Select all',
        onSelect: handleSelectAll,
        disabled: !availableColumns.length || isAtColumnLimit,
      },
      {
        key: 'clear_all',
        label: 'Clear all',
        onSelect: handleClearAll,
        disabled: selectedColumns.length === 0,
      },
    ],
    [
      availableColumns.length,
      handleClearAll,
      handleSelectAll,
      selectedColumns.length,
      isAtColumnLimit,
    ]
  );

  return (
    <div className="relative flex flex-col h-full min-h-0 w-full space-y-3 agent-run-table">
      <div className="relative flex flex-wrap items-start gap-2">
        {showFetchOverlay && (
          <div className="flex flex-wrap items-center gap-1 text-xs h-full text-muted-foreground ml-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            Updating runs...
          </div>
        )}

        <div className="ml-auto flex flex-col sm:flex-row flex-wrap items-stretch sm:items-center gap-1.5 justify-end min-w-0 w-full sm:w-auto">
          {/* Sorting controls */}
          <div className="flex flex-wrap items-center gap-1.5 justify-end min-w-0">
            <ArrowUpDown className="h-4 w-4 text-muted-foreground flex-shrink-0" />
            <div className="max-w-72">
              <SingleCombobox
                value={sortField ?? 'none'}
                onChange={handleFieldChange}
                options={sortOptions}
                placeholder="Select field"
                searchPlaceholder="Search fields..."
                emptyMessage="No field found."
                triggerProps={{ title: sortField ?? 'No sorting' }}
                triggerClassName="bg-background font-mono text-muted-foreground"
                commandInputClassName="h-8 text-xs"
                optionClassName="font-mono text-primary text-xs"
                popoverClassName="max-w-[720px] w-auto"
                popoverAlign="start"
                renderValue={(selected) =>
                  sortField ? (selected?.label ?? sortField) : 'Select field'
                }
              />
            </div>

            {sortField && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleDirectionChange}
                className="h-7 flex-shrink-0 text-xs bg-background font-mono text-muted-foreground border-border hover:bg-muted-foreground/10 flex items-center gap-1 px-2 w-16"
              >
                {sortDirection === 'asc' ? 'asc' : 'desc'}
                {sortDirection === 'asc' ? (
                  <ArrowUp className="h-3 w-3" />
                ) : (
                  <ArrowDown className="h-3 w-3" />
                )}
              </Button>
            )}
          </div>

          <DownloadMenu
            options={[
              {
                key: 'python',
                label: 'Python',
                disabled:
                  !agentRunIds?.length ||
                  isDownloadingSample ||
                  isApiKeyLoading,
                icon:
                  isDownloadingSample || isApiKeyLoading ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <FileCode className="h-3 w-3" />
                  ),
                onSelect: () => {
                  void handleDownloadSample('python');
                },
              },
              {
                key: 'notebook',
                label: 'Notebook',
                disabled:
                  !agentRunIds?.length ||
                  isDownloadingSample ||
                  isApiKeyLoading,
                icon:
                  isDownloadingSample || isApiKeyLoading ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <FileCode className="h-3 w-3" />
                  ),
                onSelect: () => {
                  void handleDownloadSample('notebook');
                },
              },
              {
                key: 'copy_dql',
                label: 'Copy DQL',
                disabled:
                  !agentRunIds?.length ||
                  isCopyingDql ||
                  isDownloadingSample ||
                  isApiKeyLoading,
                icon:
                  isCopyingDql || isApiKeyLoading ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  ),
                onSelect: () => {
                  void handleCopyDql();
                },
              },
              {
                key: 'csv',
                label: 'Download CSV',
                disabled: !agentRunIds?.length || isExporting,
                onSelect: () => {
                  void handleExport('csv');
                },
              },
              {
                key: 'tsv',
                label: 'Download TSV',
                disabled: !agentRunIds?.length || isExporting,
                onSelect: () => {
                  void handleExport('tsv');
                },
              },
            ]}
            isLoading={isExporting || isDownloadingSample || isCopyingDql}
            triggerDisabled={
              !agentRunIds?.length ||
              isExporting ||
              isDownloadingSample ||
              isCopyingDql ||
              isApiKeyLoading
            }
            className="h-7 gap-1 text-xs text-muted-foreground flex-shrink-0 w-full sm:w-auto"
            contentClassName="w-36"
          />

          {/* Columns selection */}
          <MultiCombobox
            values={selectedColumns}
            onChange={handleColumnsChange}
            options={columnOptions}
            actionItems={columnActionItems}
            placeholder="Columns"
            searchPlaceholder="Search columns..."
            emptyMessage="No columns found."
            triggerClassName="h-7 gap-1 text-xs text-muted-foreground flex-shrink-0 w-full sm:w-auto"
            triggerProps={{
              variant: 'outline',
              size: 'sm',
            }}
            valueClassName="flex items-center gap-1"
            renderValue={(selected) => (
              <span className="flex items-center gap-1">
                <Columns3 className="h-3 w-3" />
                <span className="truncate">
                  {selected.length
                    ? `Columns (${selected.length}/${availableColumns.length})`
                    : 'Columns'}
                </span>
              </span>
            )}
            commandInputClassName="h-8 text-xs"
            commandInputRef={columnSearchInputRef}
            commandListClassName="max-h-80"
            optionClassName="text-xs font-mono"
            popoverClassName="min-w-[288px] max-w-[640px]"
            popoverStyle={{
              width: 'fit-content',
              maxWidth: '640px',
            }}
            popoverAlign="end"
            onOpenChange={handleColumnsMenuOpenChange}
            headerContent={columnLimitWarning}
          />
        </div>
      </div>

      <TableContainer
        scrollRef={combinedScrollRef}
        onScroll={handleScroll}
        dropZoneHandlers={dropZoneHandlers}
        overlay={
          isDragActive ? (
            <div
              className={cn(
                'absolute inset-0 flex flex-col items-center justify-center z-50 transition-all duration-200 border-2 rounded',
                isOverDropZone
                  ? 'bg-blue-100 bg-opacity-95 border-blue-text border-solid'
                  : 'bg-blue-100 bg-opacity-80 border-blue-text border-dashed'
              )}
              style={{ pointerEvents: 'none' }}
            >
              <Upload className="h-8 w-8 text-blue-text" />
              <div className="mt-2 text-sm font-medium transition-all duration-200 text-blue-text">
                Drop Inspect logs to upload
              </div>
            </div>
          ) : null
        }
      >
        <Table className="min-w-full">
          <TableHeader className="sticky top-0 z-20 bg-secondary">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header, index) => (
                  <TableHead
                    key={header.id}
                    className={`text-xs truncate ${index === 0 ? 'sticky left-0 z-10 bg-secondary' : ''}`}
                    style={{
                      height: ROW_HEIGHT_PX,
                      width: header.column.columnDef.size,
                      maxWidth:
                        header.column.columnDef.maxSize ||
                        header.column.columnDef.size,
                    }}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {showSkeletonRows ? (
              <>
                {Array.from({ length: skeletonRowCount }).map((_, index) => (
                  <TableRow
                    key={`skeleton-${index}`}
                    className="text-xs select-none"
                    style={{ height: ROW_HEIGHT_PX }}
                  >
                    {visibleColumns.map((column, columnIndex) => (
                      <TableCell
                        key={`${column.id}-${index}`}
                        className={`py-1.5 ${
                          columnIndex === 0
                            ? 'sticky left-0 z-10 bg-background'
                            : ''
                        }`}
                        style={{
                          width: column.columnDef.size,
                          maxWidth:
                            column.columnDef.maxSize ?? column.columnDef.size,
                        }}
                      >
                        <div>
                          <Skeleton
                            className={`h-4 ${
                              columnIndex === 0 ? 'w-16' : 'w-full'
                            }`}
                          />
                        </div>
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </>
            ) : !hasRows ? (
              <TableRow>
                <TableCell colSpan={columnCount} className="py-4">
                  <div className="flex flex-col items-center justify-center text-center text-xs text-foreground py-10">
                    {emptyState}
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              <>
                {paddingTop > 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={columnCount}
                      style={{ height: paddingTop, padding: 0 }}
                    />
                  </TableRow>
                )}
                {table
                  .getRowModel()
                  .rows.slice(startIndex, endIndex)
                  .map((row) => {
                    const runId = row.original.agentRunId;
                    const isActive = activeRunId === runId;
                    return (
                      <TableRow
                        key={row.id}
                        data-state={isActive ? 'active' : undefined}
                        onClick={(event) => {
                          if (skipNextRowClickRef.current) {
                            skipNextRowClickRef.current = false;
                            event.preventDefault();
                            event.stopPropagation();
                            return;
                          }
                          onRowMouseDown(runId, event);
                        }}
                        onAuxClick={(event) => {
                          if (skipNextRowClickRef.current) {
                            skipNextRowClickRef.current = false;
                            event.preventDefault();
                            event.stopPropagation();
                            return;
                          }
                          onRowMouseDown(runId, event);
                        }}
                        className={cn(
                          'text-xs cursor-pointer select-none transition-colors duration-150 group',
                          isActive
                            ? 'bg-indigo-bg/80 hover:bg-indigo-bg'
                            : 'hover:bg-muted'
                        )}
                        style={{ height: ROW_HEIGHT_PX }}
                        tabIndex={0}
                      >
                        {row.getVisibleCells().map((cell, index) => {
                          const columnKey =
                            (
                              cell.column.columnDef.meta as
                                | { key?: string }
                                | undefined
                            )?.key ?? cell.column.id;
                          const cellValue = getCellValue(runId, columnKey);
                          const isFilterable =
                            !filterableColumns ||
                            filterableColumns.has(columnKey);
                          const hasFilterValue =
                            cellValue !== undefined &&
                            !Array.isArray(cellValue);

                          return (
                            <AgentRunTableCell
                              key={cell.id}
                              cellId={cell.id}
                              columnIndex={index}
                              columnKey={columnKey}
                              columnSize={cell.column.columnDef.size}
                              columnMaxSize={cell.column.columnDef.maxSize}
                              isActive={isActive}
                              runId={runId}
                              cellValue={cellValue}
                              isFilterable={isFilterable}
                              hasFilterValue={hasFilterValue}
                              onContextMenu={
                                onCreateFilterFromCell
                                  ? handleCellContextMenu
                                  : undefined
                              }
                            >
                              {flexRender(
                                cell.column.columnDef.cell,
                                cell.getContext()
                              )}
                            </AgentRunTableCell>
                          );
                        })}
                      </TableRow>
                    );
                  })}
                {paddingBottom > 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={columnCount}
                      style={{ height: paddingBottom, padding: 0 }}
                    />
                  </TableRow>
                )}
              </>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Single shared context menu - positioned at cursor on right-click */}
      {contextMenuCell && onCreateFilterFromCell && (
        <>
          {/* Backdrop to catch clicks outside */}
          <div
            className="fixed inset-0 z-40"
            onClick={handleContextMenuClose}
            onContextMenu={(e) => {
              e.preventDefault();
              handleContextMenuClose();
            }}
          />
          {/* Menu */}
          <div
            className="fixed z-50 rounded-md border bg-popover p-1 text-popover-foreground shadow-md animate-in fade-in-0 zoom-in-95"
            style={{
              left: contextMenuCell.x,
              top: contextMenuCell.y,
            }}
          >
            <button
              className="flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1 text-sm outline-none hover:bg-accent hover:text-accent-foreground"
              onClick={() => {
                skipNextRowClickRef.current = true;
                onCreateFilterFromCell(
                  contextMenuCell.columnKey,
                  contextMenuCell.value,
                  'append'
                );
                handleContextMenuClose();
              }}
            >
              Add filter
            </button>
            <button
              className="flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1 text-sm outline-none hover:bg-accent hover:text-accent-foreground"
              onClick={() => {
                skipNextRowClickRef.current = true;
                onCreateFilterFromCell(
                  contextMenuCell.columnKey,
                  contextMenuCell.value,
                  'replace'
                );
                handleContextMenuClose();
              }}
            >
              Clear filters then add filter
            </button>
            <button
              className="flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1 text-sm outline-none hover:bg-accent hover:text-accent-foreground"
              onClick={() => {
                skipNextRowClickRef.current = true;
                handleViewValue(
                  contextMenuCell.columnKey,
                  contextMenuCell.value
                );
                handleContextMenuClose();
              }}
            >
              View value
            </button>
            <button
              className="flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1 text-sm outline-none hover:bg-accent hover:text-accent-foreground"
              onClick={() => {
                skipNextRowClickRef.current = true;
                void handleCopyValue(
                  formatCellValue(contextMenuCell.value, true)
                );
                handleContextMenuClose();
              }}
            >
              Copy value
            </button>
          </div>
        </>
      )}
      <Dialog
        open={Boolean(viewValueCell)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setViewValueCell(null);
            setIsValueCopied(false);
            if (
              copyResetTimeoutRef.current !== null &&
              typeof window !== 'undefined'
            ) {
              window.clearTimeout(copyResetTimeoutRef.current);
              copyResetTimeoutRef.current = null;
            }
          }
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader className="flex flex-row items-start justify-between gap-3 pr-10">
            <DialogTitle className="text-base font-semibold break-words">
              {viewValueLabel}
            </DialogTitle>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void handleCopyValue(viewValueText);
              }}
              className="h-7 gap-2 text-xs"
              aria-label="Copy cell value"
            >
              {isValueCopied ? (
                <>
                  <Check className="h-3.5 w-3.5" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5" />
                  Copy
                </>
              )}
            </Button>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-auto rounded border bg-muted/40 p-3 font-mono text-xs whitespace-pre-wrap break-words">
            {viewValueText || (
              <span className="text-muted-foreground">(empty)</span>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
});

AgentRunTable.displayName = 'AgentRunTable';
