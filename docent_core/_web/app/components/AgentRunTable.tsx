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
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  Columns3,
  Loader2,
  FileCode,
  Upload,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
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
import { useDebounce } from '@/hooks/use-debounce';
import { useParams } from 'next/navigation';
import { Skeleton } from '@/components/ui/skeleton';
import { Combobox } from './Combobox';
import { TableContainer } from './TableContainer';
import { isDateString, formatDateValue } from '@/lib/dateUtils';
import UuidPill from '@/components/UuidPill';
import {
  exportTabularData,
  type DelimitedFormat,
} from '@/app/utils/exportTable';
import { BASE_URL } from '@/app/constants';
import { useDownloadApiKey } from '@/app/hooks/use-download-api-key';
import { downloadPythonSample } from '@/app/utils/pythonSamples';
import { toast } from '@/hooks/use-toast';
import { ComplexFilter } from '@/app/types/collectionTypes';

export type AgentRunTableRow = {
  agentRunId: string;
};

const ROW_HEIGHT_PX = 32;
const OVERSCAN_COUNT = 50;
const METADATA_REQUEST_DEBOUNCE_MS = 150;
const MIN_SKELETON_ROW_COUNT = 12;

// Debounces metadata fetches to limit repeated requests while scrolling.
function useDebouncedMetadataRequest(
  agentRunIds: string[] | undefined,
  metadataData: Record<string, Record<string, unknown>>,
  loadingMetadataIds: Set<string>,
  requestedMetadataIds: Set<string>,
  selectedColumns: string[],
  startIndex: number,
  endIndex: number,
  requestMetadataForIds: (
    ids: string[],
    options?: { force?: boolean }
  ) => Promise<Record<string, Record<string, unknown>>>
) {
  // Create a key that changes when we need to make a new request
  const requestKey = useMemo(() => {
    if (!agentRunIds || !agentRunIds.length || selectedColumns.length === 0) {
      return null;
    }

    const prefetchStart = Math.max(startIndex - OVERSCAN_COUNT, 0);
    const prefetchEnd = Math.min(endIndex + OVERSCAN_COUNT, agentRunIds.length);
    const idsToCheck = agentRunIds.slice(prefetchStart, prefetchEnd);
    const missing = idsToCheck.filter(
      (id) =>
        !metadataData[id] &&
        !loadingMetadataIds.has(id) &&
        !requestedMetadataIds.has(id)
    );

    // Return a string key that represents the current request state
    return missing.length > 0 ? missing.sort().join(',') : null;
  }, [
    agentRunIds,
    endIndex,
    metadataData,
    loadingMetadataIds,
    requestedMetadataIds,
    startIndex,
    selectedColumns,
  ]);

  // Debounce the request key
  const debouncedRequestKey = useDebounce(
    requestKey,
    METADATA_REQUEST_DEBOUNCE_MS
  );

  // Make the request when the debounced key changes
  useEffect(() => {
    if (debouncedRequestKey) {
      const idsToRequest = debouncedRequestKey.split(',');
      void requestMetadataForIds(idsToRequest);
    }
  }, [debouncedRequestKey, requestMetadataForIds]);
}

export interface AgentRunTableProps {
  agentRunIds?: string[];
  metadataData: Record<string, Record<string, unknown>>;
  loadingMetadataIds: Set<string>;
  requestedMetadataIds: Set<string>;
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
    options?: { force?: boolean }
  ) => Promise<Record<string, Record<string, unknown>>>;
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
}

const formatMetadataValue = (value: unknown): string => {
  if (value === null || value === undefined) {
    return '';
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

function SortToggle({
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
}

export const AgentRunTable = memo(function AgentRunTable({
  agentRunIds,
  metadataData,
  loadingMetadataIds,
  requestedMetadataIds,
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
  dropZoneHandlers,
  isDragActive,
  isOverDropZone,
  scrollContainerRef,
  emptyState,
  isLoadingAgentRuns,
  isFetchingAgentRuns,
  onCreateFilterFromCell,
  filterableColumns,
}: AgentRunTableProps) {
  const internalScrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(0);
  const [isExporting, setIsExporting] = useState(false);
  const { getApiKey: getDownloadApiKey, isLoading: isApiKeyLoading } =
    useDownloadApiKey();
  const [isDownloadingSample, setIsDownloadingSample] = useState(false);
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

  const handleScroll = useCallback((event: ReactUIEvent<HTMLDivElement>) => {
    setScrollTop(event.currentTarget.scrollTop);
  }, []);

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
      const missingIds = agentRunIds.filter((id) => !metadataData[id]);
      try {
        const fetchedMetadata = await requestMetadataForIds(missingIds, {
          force: true,
        });
        const combinedMetadata = {
          ...metadataData,
          ...fetchedMetadata,
        };
        const rows = agentRunIds.map((runId) =>
          exportColumns.map((columnKey) =>
            formatMetadataValue(
              getCellValue(runId, columnKey, combinedMetadata)
            )
          )
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
          rowCount: agentRunIds.length,
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
        toast({
          title: 'Missing collection',
          description: 'Open a collection before downloading a code sample.',
          variant: 'destructive',
        });
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
        toast({
          title: 'Download failed',
          description: errorDescription,
          variant: 'destructive',
        });
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
            label={columnKey}
            sortable={sortableColumns.has(columnKey)}
            currentSortField={sortField}
            currentSortDirection={sortDirection}
            onSortChange={onSortChange}
          />
        ),
        cell: ({ row }) => {
          const runId = row.original.agentRunId;
          const processedData = metadataData[runId];

          // Access the value based on the column type
          let value: unknown;
          if (columnKey.startsWith('metadata.')) {
            // For metadata columns, try to access from the structured metadata first
            const structured = processedData?._structured as
              | Record<string, unknown>
              | undefined;
            if (
              structured?.metadata &&
              typeof structured.metadata === 'object'
            ) {
              const metadataKey = columnKey.replace('metadata.', '');
              // Handle nested metadata access (e.g., metadata.x.y.z)
              value = getNestedValue(
                structured.metadata as Record<string, unknown>,
                metadataKey
              );
            }
          } else {
            value = processedData?.[columnKey];
          }

          // Format the value
          const text = formatMetadataValue(value);
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
    metadataData,
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

  const totalRows = data.length;
  const effectiveContainerHeight = containerHeight || 1;
  const visibleRowCount =
    Math.ceil(effectiveContainerHeight / ROW_HEIGHT_PX) + OVERSCAN_COUNT * 2;
  const rawStartIndex = Math.max(
    Math.floor(scrollTop / ROW_HEIGHT_PX) - OVERSCAN_COUNT,
    0
  );
  const endIndex = Math.min(rawStartIndex + visibleRowCount, totalRows);
  const startIndex = Math.max(0, endIndex - visibleRowCount);

  // Use debounced metadata request hook
  useDebouncedMetadataRequest(
    agentRunIds,
    metadataData,
    loadingMetadataIds,
    requestedMetadataIds,
    selectedColumns,
    startIndex,
    endIndex,
    requestMetadataForIds
  );

  const paddingTop = startIndex * ROW_HEIGHT_PX;
  const paddingBottom = Math.max((totalRows - endIndex) * ROW_HEIGHT_PX, 0);

  const columnCount = columns.length || 1;
  const hasRows = totalRows > 0;
  const showSkeletonRows = isLoadingAgentRuns && !hasRows;
  const showFetchOverlay = isFetchingAgentRuns && hasRows;
  const visibleColumns = table.getVisibleLeafColumns();

  const handleToggleColumn = useCallback(
    (column: string, checked: boolean) => {
      posthog.capture('agent_run_table_column_toggled', {
        collectionId: resolvedCollectionId,
        column: column,
        action: checked ? 'add' : 'remove',
      });

      if (checked) {
        const next = Array.from(new Set([...selectedColumns, column]));
        onSelectedColumnsChange(next);
        return;
      }
      const next = selectedColumns.filter((item) => item !== column);
      onSelectedColumnsChange(next);
    },
    [onSelectedColumnsChange, resolvedCollectionId, selectedColumns]
  );

  const handleSelectAll = useCallback(() => {
    posthog.capture('agent_run_table_columns_select_all', {
      collectionId: resolvedCollectionId,
    });

    onSelectedColumnsChange(availableColumns);
  }, [availableColumns, onSelectedColumnsChange, resolvedCollectionId]);

  const handleClearAll = useCallback(() => {
    posthog.capture('agent_run_table_columns_clear_all', {
      collectionId: resolvedCollectionId,
    });

    onSelectedColumnsChange([]);
  }, [onSelectedColumnsChange, resolvedCollectionId]);

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

  // Prepare sortable fields for the select
  const sortOptions = useMemo(
    () => [
      { value: 'none', label: 'No sorting' },
      ...Array.from(sortableColumns).map((field) => ({
        value: field,
        label: field,
      })),
    ],
    [sortableColumns]
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

        <div className="ml-auto flex flex-1 flex-wrap items-center gap-2 justify-end min-w-0">
          {/* Sorting controls */}
          <div className="flex flex-1 flex-wrap items-center gap-1.5 justify-end min-w-0">
            <ArrowUpDown className="h-4 w-4 text-muted-foreground flex-shrink-0" />
            <div className="max-w-72">
              <Combobox
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
            ]}
            isLoading={isExporting || isDownloadingSample}
            triggerDisabled={
              !agentRunIds?.length ||
              isExporting ||
              isDownloadingSample ||
              isApiKeyLoading
            }
            className="h-7 gap-1 text-xs text-muted-foreground flex-shrink-0"
            contentClassName="w-36"
          />

          {/* Columns selection */}
          <DropdownMenu onOpenChange={handleColumnsMenuOpenChange}>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="h-7 gap-1 text-xs text-muted-foreground flex-shrink-0 mx-1"
              >
                <Columns3 className="h-3 w-3" />
                Columns
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              className="min-w-[288px] max-w-[640px] p-0"
              align="end"
              style={{
                width: 'fit-content',
                maxWidth: '640px',
              }}
            >
              <Command>
                <CommandInput
                  ref={columnSearchInputRef}
                  placeholder="Search columns..."
                  className="h-8 text-xs"
                />
                <CommandList>
                  <CommandEmpty>No columns found.</CommandEmpty>
                  <CommandGroup>
                    <CommandItem
                      onSelect={() => handleSelectAll()}
                      className="text-xs text-muted-foreground"
                    >
                      Select all
                    </CommandItem>
                    <CommandItem
                      onSelect={() => handleClearAll()}
                      className="text-xs text-muted-foreground"
                    >
                      Clear all
                    </CommandItem>
                  </CommandGroup>
                  <CommandGroup>
                    {availableColumns.map((column) => {
                      const checked = selectedColumns.includes(column);
                      return (
                        <CommandItem
                          key={column}
                          onSelect={() => handleToggleColumn(column, !checked)}
                          className="text-xs font-mono"
                        >
                          <Check
                            className={cn(
                              'mr-2 h-4 w-4',
                              checked ? 'opacity-100' : 'opacity-0'
                            )}
                          />
                          {column}
                        </CommandItem>
                      );
                    })}
                  </CommandGroup>
                </CommandList>
              </Command>
            </DropdownMenuContent>
          </DropdownMenu>
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
                            ? 'bg-indigo-bg/80 border-l-2 border-indigo-border'
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
                          const hasFilterValue = cellValue !== undefined;
                          const canFilter = isFilterable && hasFilterValue;
                          const unsupportedSuffix = isFilterable
                            ? ''
                            : ' (not supported for field type)';

                          if (!onCreateFilterFromCell) {
                            return (
                              <TableCell
                                key={cell.id}
                                className={`py-1.5 ${
                                  index === 0
                                    ? `sticky left-0 z-10 ${
                                        isActive
                                          ? 'bg-indigo-bg/80'
                                          : 'bg-background group-hover:bg-muted transition-colors duration-150'
                                      }`
                                    : ''
                                }`}
                                style={{
                                  width: cell.column.columnDef.size,
                                  maxWidth:
                                    cell.column.columnDef.maxSize ||
                                    cell.column.columnDef.size,
                                }}
                              >
                                {flexRender(
                                  cell.column.columnDef.cell,
                                  cell.getContext()
                                )}
                              </TableCell>
                            );
                          }

                          return (
                            <ContextMenu key={cell.id}>
                              <ContextMenuTrigger asChild>
                                <TableCell
                                  className={`py-1.5 ${
                                    index === 0
                                      ? `sticky left-0 z-10 ${
                                          isActive
                                            ? 'bg-indigo-bg/80'
                                            : 'bg-background group-hover:bg-muted transition-colors duration-150'
                                        }`
                                      : ''
                                  }`}
                                  style={{
                                    width: cell.column.columnDef.size,
                                    maxWidth:
                                      cell.column.columnDef.maxSize ||
                                      cell.column.columnDef.size,
                                  }}
                                >
                                  {flexRender(
                                    cell.column.columnDef.cell,
                                    cell.getContext()
                                  )}
                                </TableCell>
                              </ContextMenuTrigger>
                              <ContextMenuContent className="w-64">
                                <ContextMenuItem
                                  inset
                                  disabled={!canFilter}
                                  onSelect={(event) => {
                                    if (canFilter) {
                                      skipNextRowClickRef.current = true;
                                      onCreateFilterFromCell(
                                        columnKey,
                                        cellValue,
                                        'append'
                                      );
                                    }
                                  }}
                                >
                                  {`Add filter${unsupportedSuffix}`}
                                </ContextMenuItem>
                                <ContextMenuItem
                                  inset
                                  disabled={!canFilter}
                                  onSelect={(event) => {
                                    if (canFilter) {
                                      skipNextRowClickRef.current = true;
                                      onCreateFilterFromCell(
                                        columnKey,
                                        cellValue,
                                        'replace'
                                      );
                                    }
                                  }}
                                >
                                  {`Clear filters then add filter${unsupportedSuffix}`}
                                </ContextMenuItem>
                              </ContextMenuContent>
                            </ContextMenu>
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
    </div>
  );
});

AgentRunTable.displayName = 'AgentRunTable';
