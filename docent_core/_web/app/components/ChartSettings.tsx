import { ArrowLeftRight, FunnelPlus, Download } from 'lucide-react';
import React, { useMemo, useState } from 'react';

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
} from '../types/collectionTypes';
import {
  useGetChartMetadataQuery,
  useGetChartDataQuery,
} from '../api/chartApi';
import { FilterControls } from './FilterControls';
import { FilterChips } from './FilterChips';
import { useGetAgentRunMetadataFieldsQuery } from '../api/collectionApi';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

import { exportChartToPng, exportChartToCsv } from '../utils/exportChart';

interface ChartSettingsProps {
  chart: ChartSpec;
  onChange: (chart: ChartSpec) => void;
}

function DimensionSelect({
  dim,
  onChange,
  fields,
  allowNone = true,
}: {
  dim: string | null;
  onChange: (dim: string) => void;
  fields: ChartDimension[];
  allowNone?: boolean;
}) {
  return (
    <Select value={dim || 'None'} onValueChange={onChange}>
      <SelectTrigger className="h-6 max-w-24 w-24 text-xs border-border bg-transparent hover:bg-secondary px-2 font-normal">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {allowNone && (
          <SelectItem value="None" className="text-xs">
            None
          </SelectItem>
        )}
        {fields.map((field) => (
          <SelectItem key={field.key} value={field.key} className="text-xs">
            {field.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export default function ChartSettings({ chart, onChange }: ChartSettingsProps) {
  const { x_key, y_key, series_key, runs_filter } = chart;
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const { data: metadataFieldsData } = useGetAgentRunMetadataFieldsQuery(
    collectionId!,
    {
      skip: !collectionId,
    }
  );
  const agentRunMetadataFields = metadataFieldsData?.fields ?? [];
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false);

  // Get chart metadata (fields + search queries) in one request
  const { data: chartMetadata } = useGetChartMetadataQuery(
    { collectionId: collectionId! },
    { skip: !collectionId }
  );

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

  const handleInnerDimChange = (value: string) => {
    if (!collectionId) return;
    onChange({ ...chart, x_key: value, series_key });
  };

  const handleOuterDimChange = (value: string) => {
    if (!collectionId) return;

    if (value === 'None') {
      onChange({ ...chart, x_key, series_key: null });
    } else {
      onChange({ ...chart, x_key, series_key: value });
    }
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

  const showSwapButton = innerDim && outerDim && outerDim !== 'None';

  const metadataKeys = chartMetadata?.fields?.dimensions || [];

  const scoreKeys = chartMetadata?.fields?.measures || [];

  function handleChartTypeChange(value: string) {
    onChange({ ...chart, chart_type: value as 'bar' | 'line' | 'table' });
  }

  function handleYDimChange(value: string) {
    onChange({ ...chart, y_key: value });
  }

  function handleRubricFilterChange(rubricFilter: string) {
    if (rubricFilter === 'None') {
      onChange({ ...chart, rubric_filter: null });
    } else {
      onChange({
        ...chart,
        rubric_filter: rubricFilter,
      });
    }
  }

  function handleRunsFilterChange(runsFilter: ComplexFilter | null) {
    onChange({ ...chart, runs_filter: runsFilter });
  }

  const removeFilter = (filterId: string) => {
    if (!runs_filter) return;

    const updatedFilters = runs_filter.filters.filter((f) => f.id !== filterId);

    if (updatedFilters.length === 0) {
      handleRunsFilterChange(null);
    } else {
      handleRunsFilterChange({
        ...runs_filter,
        filters: updatedFilters,
      });
    }
  };

  const clearAllFilters = () => {
    handleRunsFilterChange(null);
  };

  const handleDownloadPng = async () => {
    try {
      await exportChartToPng(chart.id, chart.name || 'chart');
    } catch (e) {
      console.error('Failed to export chart PNG', e);
    }
  };

  const handleDownloadCsv = () => {
    try {
      const binStats = chartDataResponse?.result?.binStats;
      if (isFetchingChartData || !binStats) return;
      exportChartToCsv(chart, binStats, chart.name || 'chart');
    } catch (e) {
      console.error('Failed to export chart CSV', e);
    }
  };

  return (
    <div className="flex flex-row flex-wrap p-2">
      <div className="flex flex-row flex-1 flex-wrap items-center gap-x-2 gap-y-1">
        <div className="flex items-center gap-x-1">
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            Series:
          </span>
          <DimensionSelect
            dim={outerDim}
            onChange={handleOuterDimChange}
            fields={metadataKeys}
          />
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary flex-shrink-0"
            onClick={handleSwapDimensions}
            title="Swap dimensions"
            disabled={!showSwapButton}
          >
            <ArrowLeftRight size={14} className="stroke-[1.5]" />
          </Button>

          <span className="text-xs text-muted-foreground whitespace-nowrap">
            X:
          </span>
          <DimensionSelect
            dim={innerDim}
            onChange={handleInnerDimChange}
            fields={metadataKeys}
            allowNone={false}
          />

          <span className="text-xs text-muted-foreground whitespace-nowrap">
            Y:
          </span>
          <Select value={y_key} onValueChange={handleYDimChange}>
            <SelectTrigger className="h-6 max-w-24 w-24 text-xs border-border bg-transparent hover:bg-secondary px-2 font-normal">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {scoreKeys.map((field) => (
                <SelectItem
                  key={field.key}
                  value={field.key}
                  className="text-xs"
                >
                  {field.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-x-1">
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            Type:
          </span>
          <Select
            value={chart.chart_type}
            onValueChange={handleChartTypeChange}
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

        <div className="flex items-center gap-x-1">
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            Rubric:
          </span>

          <Select
            value={chart.rubric_filter || 'None'}
            onValueChange={handleRubricFilterChange}
          >
            <SelectTrigger className="h-6 max-w-24 w-24 text-xs border-border bg-transparent hover:bg-secondary px-2 font-normal">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="None" className="text-xs">
                All Data
              </SelectItem>
              {chartMetadata?.rubrics.map((rubric) => (
                <SelectItem
                  key={rubric.id}
                  value={rubric.id}
                  className="text-xs"
                >
                  {rubric.description.slice(0, 60)}...
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-x-1">
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            Filters:
          </span>

          {runs_filter && (
            <FilterChips
              filters={runs_filter}
              onRemoveFilter={removeFilter}
              onClearAllFilters={clearAllFilters}
              className="mr-1"
            />
          )}

          {/* Add filter button/popover */}
          <Popover open={filterPopoverOpen} onOpenChange={setFilterPopoverOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className="h-6 px-1 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary flex-shrink-0"
                title="Add filter"
              >
                <FunnelPlus size={18} className="stroke-[1.5]" />
                <span className="text-xs">Add Filter</span>
              </Button>
            </PopoverTrigger>
            <PopoverContent
              align="start"
              sideOffset={4}
              className="w-[520px] overflow-x-auto"
            >
              <FilterControls
                filters={runs_filter}
                onFiltersChange={handleRunsFilterChange}
                metadataFields={agentRunMetadataFields}
                showFilterChips={false}
              />
            </PopoverContent>
          </Popover>
        </div>
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
