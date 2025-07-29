import { ArrowLeftRight } from 'lucide-react';
import React, { useMemo } from 'react';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

import { useAppSelector } from '../store/hooks';
import { ChartSpec, ChartDimension } from '../types/collectionTypes';
import { useGetChartMetadataQuery } from '../api/chartApi';

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
  const { x_key, y_key, series_key } = chart;
  const collectionId = useAppSelector((state) => state.collection.collectionId);

  // Get chart metadata (fields + search queries) in one request
  const { data: chartMetadata } = useGetChartMetadataQuery(
    { collectionId: collectionId! },
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

  return (
    <div className="flex flex-col lg:flex-row items-start sm:items-center gap-2 p-2">
      <div className="flex items-center space-x-1 py-0.5 overflow-x-auto min-w-0 w-full">
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          Type:
        </span>
        <Select value={chart.chart_type} onValueChange={handleChartTypeChange}>
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

        <span className="text-xs text-muted-foreground whitespace-nowrap">
          Filter:
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
              <SelectItem key={rubric.id} value={rubric.id} className="text-xs">
                {rubric.description.slice(0, 60)}...
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

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
          className="h-6 px-1 w-6 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary flex-shrink-0"
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
              <SelectItem key={field.key} value={field.key} className="text-xs">
                {field.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
