import {
  ArrowLeftRight,
  FunnelPlus,
  Download,
  Scale,
  Database,
  Loader2,
} from 'lucide-react';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import posthog from 'posthog-js';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

import { useAppSelector } from '../store/hooks';
import {
  ChartSpec,
  ChartDimension,
  ComplexFilter,
  PrimitiveFilter,
  DataTableColumn,
} from '../types/collectionTypes';
import {
  useGetChartMetadataQuery,
  useGetChartDataQuery,
  useGetDataTableColumnsQuery,
} from '../api/chartApi';
import { useListDataTablesQuery } from '../api/dataTableApi';
import { FilterControls } from './FilterControls';
import { FilterChips } from './FilterChips';
import { FilterActionsBar } from './FilterActionsBar';
import { useFilterFields } from '@/hooks/use-filter-fields';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import SelectWithSubmenus, {
  SelectWithSubmenusItem,
  SelectWithSubmenusSub,
  SelectWithSubmenusSubContent,
  SelectWithSubmenusSubTrigger,
} from '@/components/ui/select-with-submenus';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

import { exportChartToPng, exportChartToCsv } from '../utils/exportChart';

interface ChartSettingsProps {
  chart: ChartSpec;
  onChange: (chart: ChartSpec) => void;
}

const NONE_VALUE = '__none__';

function ColumnSelect({
  value,
  onChange,
  columns,
  allowNone = true,
  disabled = false,
  widthClass = 'w-24',
  filterNumeric = false,
  isLoading = false,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  columns: DataTableColumn[];
  allowNone?: boolean;
  disabled?: boolean;
  widthClass?: string;
  filterNumeric?: boolean;
  isLoading?: boolean;
}) {
  const filteredColumns = filterNumeric
    ? columns.filter((c) => c.inferred_type === 'numeric')
    : columns;

  const handleChange = (v: string) => {
    onChange(v === NONE_VALUE ? null : v);
  };

  if (isLoading) {
    return (
      <div className={widthClass}>
        <div className="h-6 flex items-center justify-center text-xs text-muted-foreground border border-border rounded-md px-2">
          <Loader2 className="h-3 w-3 animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className={widthClass}>
      <Select
        value={value ?? NONE_VALUE}
        onValueChange={handleChange}
        disabled={disabled}
      >
        <SelectTrigger className="h-6 text-xs border-border bg-transparent hover:bg-secondary px-2 font-normal">
          <SelectValue placeholder={allowNone ? 'None' : 'Select...'} />
        </SelectTrigger>
        <SelectContent>
          {allowNone && (
            <SelectItem value={NONE_VALUE} className="text-xs">
              None
            </SelectItem>
          )}
          {filteredColumns.map((col) => (
            <SelectItem key={col.name} value={col.name} className="text-xs">
              {col.name}
              {col.inferred_type === 'numeric' && (
                <span className="text-muted-foreground ml-1">(num)</span>
              )}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function DimensionSelect({
  dim,
  onChange,
  fields,
  allowNone = true,
  disabled = false,
  widthClass = 'w-16',
}: {
  dim: string | null;
  onChange: (dim: string | null) => void;
  fields: ChartDimension[];
  allowNone?: boolean;
  disabled?: boolean;
  widthClass?: string;
}) {
  const judgeGroups: Record<
    string,
    {
      name: string;
      judge_version: number;
      items: { key: string; label: string }[];
    }
  > = {};
  const allItems = fields.map((f) => ({ key: f.key, label: f.name }));
  const selectedLabel = useMemo(() => {
    if (dim == null) return 'None';
    return allItems.find((i) => i.key === dim)?.label || dim;
  }, [dim, allItems]);
  const runMetadataFields = [] as ChartDimension[];
  const judgeFields = [] as ChartDimension[];
  const countFields = [] as ChartDimension[];
  for (const field of fields) {
    if (field.kind === 'judge_output') {
      judgeGroups[field.judge_id] = judgeGroups[field.judge_id] || {
        name: field.judge_name,
        judge_version: field.judge_version,
        items: [],
      };
      judgeGroups[field.judge_id].items.push({
        key: field.key,
        label: field.name,
      });
    } else {
      if (field.key.startsWith('ar.metadata_json')) {
        runMetadataFields.push(field);
      } else if (field.key.startsWith('jr.output')) {
        judgeFields.push(field);
      } else {
        countFields.push(field);
      }
    }
  }

  return (
    <div className={widthClass}>
      <SelectWithSubmenus
        selectedKey={dim}
        onChange={onChange}
        selectedLabel={selectedLabel}
        allowNone={allowNone}
        disabled={disabled}
        className="h-6 text-xs px-2"
      >
        {countFields.map((f) => (
          <SelectWithSubmenusItem key={f.key} value={f.key}>
            {f.name}
          </SelectWithSubmenusItem>
        ))}
        {runMetadataFields.length > 0 && (
          <SelectWithSubmenusSub>
            <SelectWithSubmenusSubTrigger className="text-xs">
              Run Metadata
            </SelectWithSubmenusSubTrigger>
            <SelectWithSubmenusSubContent>
              {runMetadataFields.map((f) => (
                <SelectWithSubmenusItem key={f.key} value={f.key}>
                  {f.name}
                </SelectWithSubmenusItem>
              ))}
            </SelectWithSubmenusSubContent>
          </SelectWithSubmenusSub>
        )}
        {Object.values(judgeGroups).map((jg) => (
          <SelectWithSubmenusSub key={jg.name}>
            <SelectWithSubmenusSubTrigger className="text-xs">
              <Scale className="h-4 w-4 mr-2 text-muted-foreground" />
              <span className="mr-1">{jg.name}</span>
              <span className="text-muted-foreground">v{jg.judge_version}</span>
            </SelectWithSubmenusSubTrigger>
            <SelectWithSubmenusSubContent>
              {jg.items.map((item) => (
                <SelectWithSubmenusItem key={item.key} value={item.key}>
                  {item.label}
                </SelectWithSubmenusItem>
              ))}
            </SelectWithSubmenusSubContent>
          </SelectWithSubmenusSub>
        ))}
      </SelectWithSubmenus>
    </div>
  );
}

export default function ChartSettings({ chart, onChange }: ChartSettingsProps) {
  const { x_key, y_key, series_key, runs_filter, data_table_id } = chart;
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const hasWritePermission = useHasCollectionWritePermission();
  const { fields: agentRunMetadataFields } = useFilterFields({
    collectionId,
    context: { mode: 'agent_runs' },
  });
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false);
  const [editingFilter, setEditingFilter] = useState<PrimitiveFilter | null>(
    null
  );

  const usesDataTable = !!data_table_id;

  // Get chart metadata (fields + search queries) in one request
  const { data: chartMetadata } = useGetChartMetadataQuery(
    { collectionId: collectionId! },
    { skip: !collectionId || usesDataTable }
  );

  // Get list of data tables for selection
  const { data: dataTables } = useListDataTablesQuery(
    { collectionId: collectionId! },
    { skip: !collectionId }
  );

  // Get columns for the selected data table
  const { data: dataTableColumns, isFetching: isFetchingColumns } =
    useGetDataTableColumnsQuery(
      { collectionId: collectionId!, dataTableId: data_table_id! },
      { skip: !collectionId || !data_table_id }
    );

  // Track which data table we've auto-populated for to avoid duplicate updates
  const autoPopulatedForRef = useRef<string | null>(null);

  // Auto-populate x_key and y_key when columns load for a data table
  useEffect(() => {
    if (!data_table_id || !dataTableColumns || dataTableColumns.length === 0) {
      return;
    }

    // Skip if we've already auto-populated for this data table
    if (autoPopulatedForRef.current === data_table_id) {
      return;
    }

    // Skip if x_key and y_key are already set
    if (x_key && y_key) {
      autoPopulatedForRef.current = data_table_id;
      return;
    }

    // Find first numeric column for y_key
    const numericColumns = dataTableColumns.filter(
      (c) => c.inferred_type === 'numeric'
    );
    const defaultYKey = numericColumns[0]?.name ?? dataTableColumns[0]?.name;

    // Use first column for x_key (excluding the y column if possible)
    const defaultXKey =
      dataTableColumns.find((c) => c.name !== defaultYKey)?.name ??
      dataTableColumns[0]?.name;

    if (defaultXKey && defaultYKey) {
      autoPopulatedForRef.current = data_table_id;
      onChange({
        ...chart,
        x_key: x_key ?? defaultXKey,
        y_key: y_key ?? defaultYKey,
      });
    }
  }, [data_table_id, dataTableColumns, x_key, y_key, chart, onChange]);

  // Reset auto-populate tracking when data table changes
  useEffect(() => {
    if (!data_table_id) {
      autoPopulatedForRef.current = null;
    }
  }, [data_table_id]);

  // Reuse chart data cache for export without extra requests
  const { data: chartDataResponse, isFetching: isFetchingChartData } =
    useGetChartDataQuery(
      { collectionId: collectionId!, chartId: chart.id },
      { skip: !collectionId }
    );

  // In the new system, innerBinKey and outerBinKey are metadata keys directly
  const innerDim = useMemo(() => {
    if (!x_key) return null;
    return x_key;
  }, [x_key]);

  const outerDim = useMemo(() => {
    if (!series_key) return null;
    return series_key;
  }, [series_key]);

  const handleInnerDimChange = (value: string | null) => {
    if (!collectionId || value == null) return;
    onChange({ ...chart, x_key: value, series_key });
  };

  const handleOuterDimChange = (value: string | null) => {
    if (!collectionId) return;
    onChange({ ...chart, x_key, series_key: value });
  };

  const handleSwapDimensions = () => {
    if (x_key && series_key) {
      onChange({
        ...chart,
        x_key: series_key,
        series_key: x_key,
      });
    }
  };

  const showSwapButton = innerDim && outerDim;

  function handleChartTypeChange(value: string) {
    onChange({ ...chart, chart_type: value as 'bar' | 'line' | 'table' });
  }

  function handleYDimChange(value: string | null) {
    if (value == null) return;
    onChange({ ...chart, y_key: value });
  }

  function handleDataSourceChange(value: string) {
    if (value === 'standard') {
      // Switch to standard mode - clear data table and reset keys
      onChange({
        ...chart,
        data_table_id: null,
        x_key: undefined,
        y_key: undefined,
        series_key: null,
      });
    } else {
      // Switch to data table mode with selected table
      onChange({
        ...chart,
        data_table_id: value,
        x_key: undefined,
        y_key: undefined,
        series_key: null,
        runs_filter: null,
      });
    }
  }

  function handleDataTableColumnChange(
    field: 'x_key' | 'y_key' | 'series_key',
    value: string | null
  ) {
    onChange({ ...chart, [field]: value });
  }

  function handleRunsFilterChange(runsFilter: ComplexFilter | null) {
    onChange({ ...chart, runs_filter: runsFilter });
    setEditingFilter(null);
    setFilterPopoverOpen(false);
  }

  const handleRequestEdit = (filter: PrimitiveFilter) => {
    setEditingFilter(filter);
    setFilterPopoverOpen(true);
  };

  const handleDownloadPng = async () => {
    try {
      posthog.capture('chart_download_png', {
        chart_id: chart.id,
        chart_name: chart.name || 'untitled',
        chart_type: chart.chart_type,
        x_key: chart.x_key,
        y_key: chart.y_key,
        series_key: chart.series_key,
      });

      await exportChartToPng(chart.id, chart.name || 'chart');
    } catch (e) {
      console.error('Failed to export chart PNG', e);
    }
  };

  const handleDownloadCsv = () => {
    try {
      const binStats = chartDataResponse?.result?.binStats;
      if (isFetchingChartData || !binStats) return;

      posthog.capture('chart_download_csv', {
        chart_id: chart.id,
        chart_name: chart.name || 'untitled',
        chart_type: chart.chart_type,
        x_key: chart.x_key,
        y_key: chart.y_key,
        series_key: chart.series_key,
      });

      exportChartToCsv(chart, binStats, chart.name || 'chart');
    } catch (e) {
      console.error('Failed to export chart CSV', e);
    }
  };

  const dimensions = chartMetadata?.dimensions || [];
  const measures = chartMetadata?.measures || [];

  const columns = dataTableColumns || [];

  return (
    <div className="flex flex-row flex-wrap p-2">
      <div className="flex flex-row flex-1 flex-wrap items-center gap-x-2 gap-y-1">
        {/* Data Source Selector */}
        <div className="flex items-center gap-x-1">
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            <Database size={12} className="inline mr-1" />
            Source:
          </span>
          <Select
            value={usesDataTable ? data_table_id! : 'standard'}
            onValueChange={handleDataSourceChange}
            disabled={!hasWritePermission}
          >
            <SelectTrigger className="h-6 w-28 text-xs border-border bg-transparent hover:bg-secondary px-2 font-normal">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="standard" className="text-xs">
                Standard
              </SelectItem>
              {dataTables && dataTables.length > 0 && (
                <>
                  {dataTables.map((table) => (
                    <SelectItem
                      key={table.id}
                      value={table.id}
                      className="text-xs"
                    >
                      {table.name}
                    </SelectItem>
                  ))}
                </>
              )}
            </SelectContent>
          </Select>
        </div>

        {/* Dimension/Column selectors - show different UI based on mode */}
        {usesDataTable ? (
          // Data Table Mode - simple column selectors
          <div className="flex items-center gap-x-1">
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              Series:
            </span>
            <ColumnSelect
              value={series_key}
              onChange={(v) => handleDataTableColumnChange('series_key', v)}
              columns={columns}
              disabled={!hasWritePermission}
              isLoading={isFetchingColumns}
            />
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary flex-shrink-0"
              onClick={handleSwapDimensions}
              title="Swap dimensions"
              disabled={
                !showSwapButton || !hasWritePermission || isFetchingColumns
              }
            >
              <ArrowLeftRight size={14} className="stroke-[1.5]" />
            </Button>

            <span className="text-xs text-muted-foreground whitespace-nowrap">
              X:
            </span>
            <ColumnSelect
              value={x_key ?? null}
              onChange={(v) => handleDataTableColumnChange('x_key', v)}
              columns={columns}
              allowNone={false}
              disabled={!hasWritePermission}
              isLoading={isFetchingColumns}
            />

            <span className="text-xs text-muted-foreground whitespace-nowrap">
              Y:
            </span>
            <ColumnSelect
              value={y_key ?? null}
              onChange={(v) => handleDataTableColumnChange('y_key', v)}
              columns={columns}
              allowNone={false}
              disabled={!hasWritePermission}
              filterNumeric={true}
              isLoading={isFetchingColumns}
            />
          </div>
        ) : (
          // Standard Mode - dimension selectors
          <div className="flex items-center gap-x-1">
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              Series:
            </span>
            <DimensionSelect
              dim={outerDim}
              onChange={handleOuterDimChange}
              fields={dimensions}
              disabled={!hasWritePermission}
            />
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary flex-shrink-0"
              onClick={handleSwapDimensions}
              title="Swap dimensions"
              disabled={!showSwapButton || !hasWritePermission}
            >
              <ArrowLeftRight size={14} className="stroke-[1.5]" />
            </Button>

            <span className="text-xs text-muted-foreground whitespace-nowrap">
              X:
            </span>
            <DimensionSelect
              dim={innerDim}
              onChange={handleInnerDimChange}
              fields={dimensions}
              allowNone={false}
              disabled={!hasWritePermission}
            />

            <span className="text-xs text-muted-foreground whitespace-nowrap">
              Y:
            </span>
            <DimensionSelect
              dim={y_key ?? null}
              onChange={handleYDimChange}
              fields={measures}
              allowNone={false}
              disabled={!hasWritePermission}
              widthClass="w-24"
            />
          </div>
        )}

        <div className="flex items-center gap-x-1">
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            Type:
          </span>
          <Select
            value={chart.chart_type}
            onValueChange={handleChartTypeChange}
            disabled={!hasWritePermission}
          >
            <SelectTrigger className="h-6 max-w-24 w-24 text-xs border-border bg-transparent hover:bg-secondary px-2 font-normal">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="bar" className="text-xs">
                Bar
              </SelectItem>
              <SelectItem value="line" className="text-xs">
                Line
              </SelectItem>
              <SelectItem value="table" className="text-xs">
                Table
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Filters - only shown in standard mode */}
        {!usesDataTable && (
          <div className="flex flex-wrap items-center gap-x-1">
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              Filters:
            </span>

            {runs_filter && (
              <FilterChips
                filters={runs_filter}
                onFiltersChange={handleRunsFilterChange}
                onRequestEdit={handleRequestEdit}
                className="mr-1"
                readOnly={!hasWritePermission}
              />
            )}

            {/* Filter button/popover */}
            <Popover
              open={filterPopoverOpen}
              onOpenChange={setFilterPopoverOpen}
            >
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  className="h-6 px-1 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary flex-shrink-0"
                  title="Filter"
                  disabled={!hasWritePermission}
                >
                  <FunnelPlus size={18} className="stroke-[1.5]" />
                  <span className="text-xs">Filter</span>
                </Button>
              </PopoverTrigger>
              <PopoverContent
                align="start"
                sideOffset={4}
                className="w-[520px] overflow-x-auto space-y-1.5"
              >
                <FilterControls
                  filters={runs_filter}
                  onFiltersChange={handleRunsFilterChange}
                  metadataFields={agentRunMetadataFields}
                  collectionId={collectionId!}
                  showStepFilter={false}
                  initialFilter={editingFilter}
                />
                {hasWritePermission && (
                  <FilterActionsBar
                    collectionId={collectionId!}
                    currentFilter={runs_filter}
                    onApplyFilter={handleRunsFilterChange}
                  />
                )}
              </PopoverContent>
            </Popover>
          </div>
        )}
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary"
            title="Download"
          >
            <Download size={14} />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={handleDownloadPng}>
            Download PNG
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={handleDownloadCsv}
            disabled={
              isFetchingChartData || !chartDataResponse?.result?.binStats
            }
          >
            Download CSV
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
