'use client';

import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  Loader2,
  Pencil,
  Check,
  X,
  Columns3,
  Square,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  AlertCircle,
  CircleX,
  Eraser,
} from 'lucide-react';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import { MultiCombobox, SingleCombobox } from '@/app/components/Combobox';
import { v4 as uuid4 } from 'uuid';
import {
  applyResultFilterOp,
  type ResultColumnType,
  type ResultFilter,
} from '@/app/utils/resultFilters';

import {
  useUpdateResultSetNameMutation,
  useCancelJobsMutation,
  ResultResponse,
} from '@/app/api/resultSetApi';
import { useSlidingPanelContext } from '@/components/sliding-panels';
import { hasTextWithCitations } from '@/components/CitationRenderer';

function isPending(result: ResultResponse): boolean {
  return result.output === null && result.error_json === null;
}

function isError(result: ResultResponse): boolean {
  return result.output === null && result.error_json !== null;
}

function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
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
}

export interface ResultsTablePanelContentProps {
  results: ResultResponse[];
  hasActiveJob: boolean;
  resultSet: {
    id: string;
    name: string | null;
    job_id?: string | null;
    job_status?: string | null;
  };
  completedCount: number;
  errorCount: number;
  pendingCount: number;
  collectionId: string;
  resultSetIdOrName: string;
  hasWritePermission: boolean;
  availableColumns: string[];
  selectedColumns: string[];
  onSelectedColumnsChange: (columns: string[]) => void;
  autoJoinColumns: Set<string>;
  sortField: string | null;
  sortDirection: 'asc' | 'desc';
  onSortChange: (field: string | null, direction: 'asc' | 'desc') => void;
  filters: ResultFilter[];
  onFiltersChange: (filters: ResultFilter[]) => void;
}

export function ResultsTablePanelContent({
  results,
  hasActiveJob,
  resultSet,
  completedCount,
  errorCount,
  pendingCount,
  collectionId,
  resultSetIdOrName,
  hasWritePermission,
  availableColumns,
  selectedColumns,
  onSelectedColumnsChange,
  autoJoinColumns,
  sortField,
  sortDirection,
  onSortChange,
  filters,
  onFiltersChange,
}: ResultsTablePanelContentProps) {
  const router = useRouter();
  const { pushPanel, replacePanelsAfter, panelStack } =
    useSlidingPanelContext();
  const [isEditingName, setIsEditingName] = useState(false);
  const [editedName, setEditedName] = useState('');
  const [updateName, { isLoading: isUpdatingName }] =
    useUpdateResultSetNameMutation();
  const [cancelJobs, { isLoading: isCancellingJob }] = useCancelJobsMutation();
  const [hasPendingCancel, setHasPendingCancel] = useState(false);

  const [filterField, setFilterField] = useState<string | null>(null);
  const [filterOp, setFilterOp] = useState<ResultFilter['op']>('==');
  const [filterValueRaw, setFilterValueRaw] = useState('');

  const isJobCancelling = resultSet.job_status === 'cancelling';
  const showCancellingState =
    isCancellingJob || hasPendingCancel || isJobCancelling;

  useEffect(() => {
    if (!resultSet.job_id || isJobCancelling) {
      setHasPendingCancel(false);
    }
  }, [resultSet.job_id, isJobCancelling]);

  const handleCancelJob = async () => {
    setHasPendingCancel(true);
    try {
      await cancelJobs({
        collectionId,
        resultSetIdOrName,
      }).unwrap();
      toast.success('Job cancelled');
    } catch {
      toast.error('Failed to cancel job');
      setHasPendingCancel(false);
    }
  };

  const handleStartEditName = () => {
    setEditedName(resultSet.name || '');
    setIsEditingName(true);
  };

  const handleCancelEditName = () => {
    setIsEditingName(false);
    setEditedName('');
  };

  const handleSaveName = async () => {
    try {
      await updateName({
        collectionId,
        resultSetIdOrName,
        name: editedName || null,
      }).unwrap();
      setIsEditingName(false);
      toast.success('Name updated successfully');
      if (editedName && editedName !== resultSetIdOrName) {
        router.replace(
          `/dashboard/${collectionId}/results/${encodeURIComponent(editedName)}`
        );
      }
    } catch {
      toast.error('Failed to update name');
    }
  };

  const formatValue = (value: unknown): string => {
    if (value === null || value === undefined) return '-';
    if (hasTextWithCitations(value)) return value.text;
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };

  const getColumnDisplayName = (col: string): string => {
    if (col.startsWith('user_metadata.')) {
      return col.replace('user_metadata.', '');
    }
    if (col.startsWith('output.')) {
      return col.replace('output.', '');
    }
    if (col.startsWith('joined.')) {
      return col.replace('joined.', '');
    }
    return col;
  };

  const getColumnType = (col: string): 'metadata' | 'output' | 'other' => {
    if (col.startsWith('user_metadata.')) return 'metadata';
    if (col.startsWith('output.')) return 'output';
    return 'other';
  };

  type ColumnCategory = 'metadata' | 'output' | 'joined' | 'other';

  const getColumnCategory = (col: string): ColumnCategory => {
    if (autoJoinColumns.has(col)) return 'joined';
    return getColumnType(col);
  };

  const getColumnCategoryLabel = (category: ColumnCategory): string | null => {
    if (category === 'joined') return 'joined';
    if (category === 'output') return 'output';
    if (category === 'metadata') return 'metadata';
    return null;
  };

  const getColumnCategoryTextClass = (category: ColumnCategory): string => {
    if (category === 'metadata') return 'text-purple-text';
    if (category === 'output') return 'text-orange-text';
    if (category === 'joined') return 'text-blue-text';
    return 'text-muted-foreground';
  };

  const renderCellValue = (
    result: ResultResponse,
    col: string
  ): React.ReactNode => {
    const value = getNestedValue(
      result as unknown as Record<string, unknown>,
      col
    );

    if (col.startsWith('output.') && isError(result)) {
      return <AlertCircle className="h-4 w-4 text-red-text" />;
    }

    if (col.startsWith('output.') && isPending(result) && hasActiveJob) {
      return (
        <Loader2 size={14} className="animate-spin text-muted-foreground" />
      );
    }

    return formatValue(value);
  };

  const handleRowClick = (result: ResultResponse) => {
    if (panelStack.length > 0) {
      replacePanelsAfter(panelStack[0].id, {
        type: 'result',
        title: 'Result',
        resultId: result.id,
        result,
      });
    } else {
      pushPanel({
        type: 'result',
        title: 'Result',
        resultId: result.id,
        result,
      });
    }
  };

  const columnOptions = useMemo(
    () =>
      availableColumns.map((col) => ({
        value: col,
        label: getColumnDisplayName(col),
      })),
    [availableColumns]
  );

  const columnActionItems = useMemo(
    () => [
      {
        key: 'select_all',
        label: 'Select all',
        onSelect: () => onSelectedColumnsChange(availableColumns),
        disabled: availableColumns.length === 0,
      },
      {
        key: 'clear_all',
        label: 'Clear all',
        onSelect: () => onSelectedColumnsChange([]),
        disabled: selectedColumns.length === 0,
      },
    ],
    [availableColumns, onSelectedColumnsChange, selectedColumns.length]
  );

  const visibleColumns = useMemo(() => {
    const selected = new Set(selectedColumns);
    return {
      base: availableColumns.filter(
        (col) => selected.has(col) && !autoJoinColumns.has(col)
      ),
      autoJoin: availableColumns.filter(
        (col) => selected.has(col) && autoJoinColumns.has(col)
      ),
    };
  }, [selectedColumns, availableColumns, autoJoinColumns]);

  const sortOptions = useMemo(
    () => [
      { value: 'none', label: 'No sorting' },
      ...availableColumns.map((col) => ({
        value: col,
        label: getColumnDisplayName(col),
      })),
    ],
    [availableColumns]
  );

  const inferColumnType = useCallback(
    (col: string): ResultColumnType => {
      for (const result of results) {
        const v = getNestedValue(
          result as unknown as Record<string, unknown>,
          col
        );
        if (v === null || v === undefined) continue;
        if (typeof v === 'boolean') return 'bool';
        if (typeof v === 'number') return 'number';
        if (typeof v === 'string') return 'str';
        return 'other';
      }
      return 'str';
    },
    [results]
  );

  const selectedFilterFieldType = useMemo<ResultColumnType>(() => {
    if (!filterField) return 'str';
    return inferColumnType(filterField);
  }, [filterField, inferColumnType]);

  const filterOpOptions = useMemo<
    { value: ResultFilter['op']; label: string }[]
  >(() => {
    if (selectedFilterFieldType === 'bool') {
      return [
        { value: '==', label: '==' },
        { value: '!=', label: '!=' },
      ];
    }
    if (selectedFilterFieldType === 'number') {
      return [
        { value: '==', label: '==' },
        { value: '!=', label: '!=' },
        { value: '<', label: '<' },
        { value: '<=', label: '<=' },
        { value: '>', label: '>' },
        { value: '>=', label: '>=' },
      ];
    }
    return [
      { value: '~*', label: '~*' },
      { value: '==', label: '==' },
      { value: '!=', label: '!=' },
      { value: '<', label: '<' },
      { value: '<=', label: '<=' },
      { value: '>', label: '>' },
      { value: '>=', label: '>=' },
    ];
  }, [selectedFilterFieldType]);

  useEffect(() => {
    if (!filterOpOptions.some((o) => o.value === filterOp)) {
      setFilterOp(filterOpOptions[0]?.value ?? '==');
    }
  }, [filterOp, filterOpOptions]);

  const parsedFilterValue = useMemo<
    { ok: true; value: ResultFilter['value'] } | { ok: false; reason: string }
  >(() => {
    const raw = filterValueRaw.trim();
    if (!raw) return { ok: false, reason: 'Enter a value' };

    if (selectedFilterFieldType === 'bool') {
      if (raw === 'true') return { ok: true, value: true };
      if (raw === 'false') return { ok: true, value: false };
      return { ok: false, reason: 'Use true/false' };
    }

    if (selectedFilterFieldType === 'number') {
      const n = Number(raw);
      if (Number.isFinite(n)) return { ok: true, value: n };
      return { ok: false, reason: 'Enter a valid number' };
    }

    if (filterOp === '~*') {
      try {
        void new RegExp(raw, 'i');
      } catch {
        return { ok: false, reason: 'Invalid regex' };
      }
    }

    return { ok: true, value: raw };
  }, [filterOp, filterValueRaw, selectedFilterFieldType]);

  const handleAddFilter = useCallback(() => {
    if (!filterField) {
      toast.error('Select a field');
      return;
    }
    if (!parsedFilterValue.ok) {
      toast.error(parsedFilterValue.reason);
      return;
    }

    const newFilter: ResultFilter = {
      id: uuid4(),
      column: filterField,
      op: filterOp,
      value: parsedFilterValue.value,
    };
    onFiltersChange([...filters, newFilter]);
    setFilterValueRaw('');
  }, [filterField, filterOp, filters, onFiltersChange, parsedFilterValue]);

  const handleRemoveFilter = useCallback(
    (filterId: string) => {
      onFiltersChange(filters.filter((f) => f.id !== filterId));
    },
    [filters, onFiltersChange]
  );

  const handleClearFilters = useCallback(() => {
    onFiltersChange([]);
  }, [onFiltersChange]);

  const sortedResults = useMemo(() => {
    if (!sortField) return results;

    return [...results].sort((a, b) => {
      const aVal = getNestedValue(
        a as unknown as Record<string, unknown>,
        sortField
      );
      const bVal = getNestedValue(
        b as unknown as Record<string, unknown>,
        sortField
      );

      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return sortDirection === 'asc' ? 1 : -1;
      if (bVal == null) return sortDirection === 'asc' ? -1 : 1;

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortDirection === 'asc'
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  }, [results, sortField, sortDirection]);

  const filteredResults = useMemo(() => {
    if (filters.length === 0) return sortedResults;
    return sortedResults.filter((result) =>
      filters.every((filter) => {
        const value = getNestedValue(
          result as unknown as Record<string, unknown>,
          filter.column
        );
        return applyResultFilterOp(value, filter.op, filter.value);
      })
    );
  }, [filters, sortedResults]);

  const handleFieldChange = (field: string) => {
    if (field === 'none') {
      onSortChange(null, 'asc');
    } else {
      onSortChange(field, sortDirection);
    }
  };

  const handleDirectionToggle = () => {
    if (sortField) {
      onSortChange(sortField, sortDirection === 'asc' ? 'desc' : 'asc');
    }
  };

  return (
    <div className="flex flex-col h-full p-4">
      {/* Header */}
      <div className="border-b pb-4 border-border">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            {isEditingName ? (
              <div className="flex items-center gap-2">
                <Input
                  value={editedName}
                  onChange={(e) => setEditedName(e.target.value)}
                  className="h-8 w-64"
                  placeholder="Enter name..."
                  autoFocus
                />
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={handleSaveName}
                  disabled={isUpdatingName}
                >
                  <Check className="h-4 w-4 text-green-600" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={handleCancelEditName}
                >
                  <X className="h-4 w-4 text-red-600" />
                </Button>
              </div>
            ) : (
              <>
                <div className="text-sm font-semibold tracking-tight">
                  {resultSet.name || (
                    <span className="text-muted-foreground italic">
                      Unnamed ({resultSet.id.slice(0, 8)}...)
                    </span>
                  )}
                </div>
                {hasWritePermission && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={handleStartEditName}
                  >
                    <Pencil className="h-3 w-3" />
                  </Button>
                )}
              </>
            )}
          </div>
          <div className="text-xs text-muted-foreground flex items-center gap-2">
            <span>{completedCount} completed</span>
            {errorCount > 0 && <span>{errorCount} errors</span>}
            {pendingCount > 0 && (
              <span className="flex items-center gap-1">
                <Loader2 size={12} className="animate-spin" />
                {pendingCount} in progress
              </span>
            )}
            {hasActiveJob &&
              hasWritePermission &&
              (showCancellingState ? (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled
                  className="h-6 px-2 text-xs"
                >
                  Cancelling...
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs text-destructive hover:text-destructive"
                  onClick={handleCancelJob}
                >
                  <Square className="h-3 w-3 mr-1 fill-current" />
                  Stop
                </Button>
              ))}
          </div>
        </div>
        {/* Filter controls */}
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[240px] flex-1">
              <div className="text-xs text-muted-foreground font-mono ml-1 mb-1">
                Filter by
              </div>
              <SingleCombobox
                value={filterField}
                onChange={(val) => setFilterField(val)}
                options={availableColumns.map((col) => ({
                  value: col,
                  label: getColumnDisplayName(col),
                }))}
                placeholder="Select field"
                searchPlaceholder="Search columns..."
                emptyMessage="No column found."
                triggerProps={{ title: filterField ?? 'Select field' }}
                triggerClassName="w-full justify-between h-7 text-xs text-muted-foreground bg-background font-mono"
                commandInputClassName="h-8 text-xs"
                optionClassName="font-mono text-primary text-xs"
                popoverClassName="max-w-[720px] w-auto"
                popoverAlign="start"
              />
            </div>
            <div className="w-20 flex-shrink-0">
              <div className="text-xs text-muted-foreground font-mono ml-1 mb-1">
                Operator
              </div>
              <Select
                value={filterOp}
                onValueChange={(val) => setFilterOp(val as ResultFilter['op'])}
              >
                <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground w-full hover:bg-secondary hover:text-primary">
                  <SelectValue placeholder="==" />
                </SelectTrigger>
                <SelectContent>
                  {filterOpOptions.map((opt) => (
                    <SelectItem
                      key={opt.value}
                      value={opt.value}
                      className="font-mono text-xs"
                    >
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="min-w-[260px] flex-[2]">
              <div className="text-xs text-muted-foreground font-mono ml-1 mb-1">
                Value ({selectedFilterFieldType})
              </div>
              <Input
                value={filterValueRaw}
                onChange={(e) => setFilterValueRaw(e.target.value)}
                placeholder={
                  selectedFilterFieldType === 'bool'
                    ? 'true/false'
                    : selectedFilterFieldType === 'number'
                      ? 'e.g. 42'
                      : filterOp === '~*'
                        ? 'e.g. value'
                        : 'e.g. value'
                }
                className="h-7 text-xs bg-background font-mono text-muted-foreground hover:bg-secondary hover:text-primary"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddFilter();
                  }
                }}
              />
            </div>
            <div className="flex-shrink-0">
              <Button
                onClick={handleAddFilter}
                disabled={!filterField || !parsedFilterValue.ok}
                className="h-7 text-xs whitespace-nowrap px-3"
                size="sm"
              >
                Add filter
              </Button>
            </div>
          </div>

          {/* Filter chips */}
          {filters.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {filters.map((f) => (
                <div
                  key={f.id}
                  className="inline-flex items-center gap-x-1 text-[11px] border pl-1.5 pr-1 py-0.5 rounded-md transition-colors min-w-0 bg-indigo-bg text-primary border-indigo-border hover:bg-indigo-bg/80 hover:border-indigo-border/80"
                >
                  <span
                    className="font-mono inline-block max-w-[200px] truncate"
                    title={f.column}
                  >
                    {getColumnDisplayName(f.column)}
                  </span>
                  <span className="font-mono inline-block text-indigo-text">
                    {f.op}
                  </span>
                  <span
                    className="font-mono inline-block max-w-[260px] truncate"
                    title={String(f.value)}
                  >
                    {String(f.value)}
                  </span>
                  <button
                    onClick={() => handleRemoveFilter(f.id)}
                    className="p-0.5 text-current hover:text-current/80 hover:bg-foreground/10 rounded-sm transition-colors"
                    title="Remove filter"
                  >
                    <CircleX size={10} />
                  </button>
                </div>
              ))}
              {filters.length > 1 && (
                <button
                  onClick={handleClearFilters}
                  className="inline-flex items-center gap-x-1 text-[11px] bg-red-bg text-primary border border-red-border px-1.5 py-0.5 rounded-md hover:bg-red-bg/50 transition-colors"
                >
                  Clear All
                  <Eraser size={10} />
                </button>
              )}
            </div>
          )}
        </div>

        {/* Column selector and sort controls */}
        <div className="mt-3 flex items-center gap-2 flex-wrap">
          <div className="ml-auto flex items-center gap-2 flex-nowrap">
            {/* Sort controls */}
            <div className="flex items-center gap-1.5">
              <ArrowUpDown className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              <div className="max-w-72">
                <SingleCombobox
                  value={sortField ?? 'none'}
                  onChange={handleFieldChange}
                  options={sortOptions}
                  placeholder="Sort by"
                  searchPlaceholder="Search columns..."
                  emptyMessage="No column found."
                  triggerProps={{ title: sortField ?? 'No sorting' }}
                  triggerClassName="h-7 text-xs text-muted-foreground bg-background font-mono"
                  commandInputClassName="h-8 text-xs"
                  optionClassName="font-mono text-primary text-xs"
                  popoverClassName="max-w-[480px] w-auto"
                  popoverAlign="start"
                  renderValue={(selected) =>
                    sortField ? (selected?.label ?? sortField) : 'Sort by'
                  }
                />
              </div>

              {sortField && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleDirectionToggle}
                  className="h-7 flex-shrink-0 text-xs bg-background font-mono text-muted-foreground border-border hover:bg-muted-foreground/10 flex items-center gap-1 px-2 w-16"
                >
                  {sortDirection}
                  {sortDirection === 'asc' ? (
                    <ArrowUp className="h-3 w-3" />
                  ) : (
                    <ArrowDown className="h-3 w-3" />
                  )}
                </Button>
              )}
            </div>

            <MultiCombobox
              values={selectedColumns}
              onChange={onSelectedColumnsChange}
              options={columnOptions}
              actionItems={columnActionItems}
              placeholder="Columns"
              searchPlaceholder="Search columns..."
              emptyMessage="No columns found."
              triggerClassName="h-7 text-xs text-muted-foreground"
              triggerProps={{ variant: 'outline', size: 'sm' }}
              commandInputClassName="h-8 text-xs"
              optionClassName="text-xs font-mono"
              popoverClassName="min-w-[288px] max-w-[480px]"
              popoverAlign="start"
              renderValue={(selected) => (
                <span className="flex items-center gap-1">
                  <Columns3 className="h-3 w-3" />
                  <span>
                    Columns ({selected.length}/{availableColumns.length})
                  </span>
                </span>
              )}
            />
          </div>
        </div>
      </div>

      {/* Table */}
      {results.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-muted-foreground text-xs">
          No results in this result set yet.
        </div>
      ) : filteredResults.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-muted-foreground text-xs">
          No results match the current filters.
        </div>
      ) : (
        <div className="flex-1 overflow-auto min-h-0">
          <Table>
            <TableHeader className="bg-secondary sticky top-0 z-10">
              <TableRow>
                {visibleColumns.base.map((col) => {
                  const displayName = getColumnDisplayName(col);
                  const category = getColumnCategory(col);
                  const colorClass = getColumnCategoryTextClass(category);
                  const categoryLabel = getColumnCategoryLabel(category);
                  return (
                    <TableHead key={col} className="py-2.5 whitespace-nowrap">
                      <div className="flex flex-col leading-tight">
                        <span className={`font-medium text-xs ${colorClass}`}>
                          {displayName}
                        </span>
                        {categoryLabel && (
                          <span className="text-[10px] font-normal text-muted-foreground">
                            {categoryLabel}
                          </span>
                        )}
                      </div>
                    </TableHead>
                  );
                })}
                {visibleColumns.autoJoin.map((col) => {
                  const displayName = getColumnDisplayName(col);
                  const category = getColumnCategory(col);
                  const colorClass = getColumnCategoryTextClass(category);
                  const categoryLabel = getColumnCategoryLabel(category);
                  return (
                    <TableHead key={col} className="py-2.5 whitespace-nowrap">
                      <div className="flex flex-col leading-tight">
                        <span className={`font-medium text-xs ${colorClass}`}>
                          {displayName}
                        </span>
                        {categoryLabel && (
                          <span className="text-[10px] font-normal text-muted-foreground">
                            {categoryLabel}
                          </span>
                        )}
                      </div>
                    </TableHead>
                  );
                })}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredResults.map((result) => {
                const isSelected = panelStack.some(
                  (p) => p.resultId === result.id
                );
                return (
                  <TableRow
                    key={result.id}
                    className={`cursor-pointer hover:bg-secondary/50 ${isSelected ? 'bg-secondary' : ''}`}
                    onClick={() => handleRowClick(result)}
                  >
                    {visibleColumns.base.map((col) => (
                      <TableCell
                        key={col}
                        className="py-2 text-xs max-w-[200px] truncate"
                      >
                        {renderCellValue(result, col)}
                      </TableCell>
                    ))}
                    {visibleColumns.autoJoin.map((col) => (
                      <TableCell
                        key={col}
                        className="py-2 text-xs max-w-[200px] truncate"
                      >
                        {renderCellValue(result, col)}
                      </TableCell>
                    ))}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
