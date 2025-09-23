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
  Columns3,
  Upload,
  Check,
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/use-debounce';
import { Combobox } from './Combobox';
import { useParams } from 'next/navigation';

export type AgentRunTableRow = {
  agentRunId: string;
};

const ROW_HEIGHT_PX = 32;
const OVERSCAN_COUNT = 50;
const METADATA_REQUEST_DEBOUNCE_MS = 150;

// Debounces metadata fetches to limit repeated requests while scrolling.
function useDebouncedMetadataRequest(
  agentRunIds: string[] | undefined,
  metadataData: Record<string, Record<string, unknown>>,
  loadingMetadataIds: Set<string>,
  requestedMetadataIds: Set<string>,
  selectedColumns: string[],
  startIndex: number,
  endIndex: number,
  requestMetadataForIds: (ids: string[]) => void
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
      requestMetadataForIds(idsToRequest);
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
  onSortChange: (field: string | null, direction: 'asc' | 'desc') => void;
  activeRunId?: string;
  onRowMouseDown: (
    runId: string,
    event: ReactMouseEvent<HTMLTableRowElement>
  ) => void;
  requestMetadataForIds: (ids: string[]) => void;
  dropZoneHandlers: {
    onDragOver: (event: ReactDragEvent<HTMLDivElement>) => void;
    onDragLeave: (event: ReactDragEvent<HTMLDivElement>) => void;
    onDrop: (event: ReactDragEvent<HTMLDivElement>) => void;
  };
  isDragActive: boolean;
  isOverDropZone: boolean;
  scrollContainerRef?: (node: HTMLDivElement | null) => void;
  emptyState?: ReactNode;
}

const formatMetadataValue = (value: unknown): string => {
  if (value === null || value === undefined) {
    return '';
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
  onSortChange,
  activeRunId,
  onRowMouseDown,
  requestMetadataForIds,
  dropZoneHandlers,
  isDragActive,
  isOverDropZone,
  scrollContainerRef,
  emptyState,
}: AgentRunTableProps) {
  const internalScrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(0);

  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(
    null
  );

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
        const shortUuid = runId.split('-')[0];
        return (
          <span className="font-mono text-xs text-primary">{shortUuid}</span>
        );
      },
      size: 160,
      maxSize: 300,
      meta: { align: 'left' },
    };

    const metadataColumns = selectedColumns
      .filter((columnKey) => columnKey !== 'agent_run_id') // Exclude agent_run_id since it has a hardcoded column
      .sort((a, b) => {
        // Sort selected columns to match the availableColumns order
        if (a === 'created_at') return 1;
        if (b === 'created_at') return -1;
        return a.localeCompare(b);
      })
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

          // Special formatting for created_at
          if (columnKey === 'created_at') {
            if (!value || typeof value !== 'string') {
              return <span className="text-xs text-muted-foreground">-</span>;
            }
            const date = new Date(value);
            if (isNaN(date.getTime())) {
              return <span className="text-xs text-muted-foreground">-</span>;
            }
            const formattedDate = date.toLocaleString('en-US', {
              year: 'numeric',
              month: '2-digit',
              day: '2-digit',
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
              timeZone: 'UTC',
              timeZoneName: 'short',
            });
            return (
              <span className="text-xs text-muted-foreground truncate block">
                {formattedDate}
              </span>
            );
          }

          // Default formatting for other columns
          const text = formatMetadataValue(value);
          return (
            <span className="text-xs text-muted-foreground truncate block">
              {text}
            </span>
          );
        },
        maxSize: 300,
        meta: { align: 'left' },
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

  const params = useParams();
  const collectionId = params?.collectionId;

  const handleToggleColumn = useCallback(
    (column: string, checked: boolean) => {
      posthog.capture('agent_run_table_column_toggled', {
        collectionId,
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
    [onSelectedColumnsChange, selectedColumns]
  );

  const handleSelectAll = useCallback(() => {
    posthog.capture('agent_run_table_columns_select_all', {
      collectionId,
    });

    onSelectedColumnsChange(availableColumns);
  }, [availableColumns, onSelectedColumnsChange]);

  const handleClearAll = useCallback(() => {
    posthog.capture('agent_run_table_columns_clear_all', {
      collectionId,
    });
  }, [onSelectedColumnsChange]);

  // Sort controls handlers
  const handleFieldChange = useCallback(
    (field: string) => {
      posthog.capture('agent_run_table_sort_changed', {
        collectionId,
        field: field === 'none' ? null : field,
        direction: sortDirection,
      });

      if (field === 'none') {
        onSortChange(null, 'asc');
      } else {
        onSortChange(field, sortDirection);
      }
    },
    [onSortChange, sortDirection]
  );

  const handleDirectionChange = useCallback(() => {
    if (sortField) {
      const newDirection = sortDirection === 'asc' ? 'desc' : 'asc';
      posthog.capture('agent_run_table_sort_changed', {
        collectionId,
        field: sortField,
        direction: newDirection,
      });

      onSortChange(sortField, newDirection);
    }
  }, [onSortChange, sortField, sortDirection]);

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
    <div className="relative flex flex-col h-full min-h-0 w-full space-y-3">
      <div className="flex justify-end items-center gap-2">
        {/* Sorting controls */}
        <div className="flex items-center gap-1.5">
          <ArrowUpDown className="h-4 w-4 text-muted-foreground" />
          <Combobox
            value={sortField ?? 'none'}
            onChange={handleFieldChange}
            options={sortOptions}
            placeholder="Select field"
            searchPlaceholder="Search fields..."
            emptyMessage="No field found."
            triggerClassName="bg-background font-mono text-muted-foreground max-w-lg justify-between"
            valueClassName="truncate flex-1 min-w-0 text-left"
            commandInputClassName="h-8 text-xs"
            commandListClassName="custom-scrollbar"
            optionClassName="font-mono text-muted-foreground text-xs"
            popoverClassName="w-64"
            popoverAlign="start"
            renderValue={(selected) =>
              sortField ? (selected?.label ?? sortField) : 'Select field'
            }
          />

          {sortField && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleDirectionChange}
              className="h-7 text-xs bg-background font-mono text-muted-foreground border-border hover:bg-muted-foreground/10 flex items-center gap-1 px-2 w-16"
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

        {/* Columns selection */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1 text-xs text-muted-foreground"
            >
              <Columns3 className="h-3 w-3" />
              Columns
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-72 p-0" align="end">
            <Command>
              <CommandInput
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

      <div className="border rounded-md flex-1 flex flex-col min-h-0">
        <div
          className="flex-1 min-h-0 overflow-auto custom-scrollbar relative"
          ref={combinedScrollRef}
          onScroll={handleScroll}
          {...dropZoneHandlers}
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
              {!hasRows ? (
                <TableRow>
                  <TableCell colSpan={columnCount} className="py-4">
                    <div className="flex flex-col items-center justify-center text-center text-xs text-muted-foreground py-10">
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
                          onMouseDown={(event) => onRowMouseDown(runId, event)}
                          className={cn(
                            'text-xs cursor-pointer select-none transition-colors duration-150 group',
                            isActive
                              ? 'bg-indigo-bg/80 border-l-2 border-indigo-border'
                              : 'hover:bg-muted'
                          )}
                          style={{ height: ROW_HEIGHT_PX }}
                          tabIndex={0}
                        >
                          {row.getVisibleCells().map((cell, index) => (
                            <TableCell
                              key={cell.id}
                              className={`py-1.5 ${index === 0 ? `sticky left-0 z-10 ${isActive ? 'bg-indigo-bg/80' : 'bg-background group-hover:bg-muted transition-colors duration-150'}` : ''}`}
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
                          ))}
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

          {isDragActive && (
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
          )}
        </div>
      </div>
    </div>
  );
});

AgentRunTable.displayName = 'AgentRunTable';
