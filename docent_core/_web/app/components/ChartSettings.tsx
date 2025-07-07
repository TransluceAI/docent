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
import { ChartSpec } from '../types/collectionTypes';
import { getFieldsByPrefix } from '../utils/chartDataUtils';

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
  fields: string[];
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
        {fields.map((key) => (
          <SelectItem key={key} value={key} className="text-xs">
            {key}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export default function ChartSettings({ chart, onChange }: ChartSettingsProps) {
  const { xKey, yKey, seriesKey } = chart;
  const collectionId = useAppSelector((state) => state.collection.collectionId);

  // Read agentRunMetadataFields from Redux
  const agentRunMetadataFields =
    useAppSelector((state) => state.collection.agentRunMetadataFields) || [];

  // In the new system, innerBinKey and outerBinKey are metadata keys directly
  const innerDim = useMemo(() => {
    if (!xKey) return null;
    return xKey;
  }, [xKey]);

  const outerDim = useMemo(() => {
    if (!seriesKey) return null;
    return seriesKey;
  }, [seriesKey]);

  const handleInnerDimChange = (value: string) => {
    if (!collectionId) return;
    onChange({ ...chart, xKey: value, seriesKey });
  };

  const handleOuterDimChange = (value: string) => {
    if (!collectionId) return;

    if (value === 'None') {
      onChange({ ...chart, xKey, seriesKey: undefined });
    } else {
      onChange({ ...chart, xKey, seriesKey: value });
    }
  };

  const handleSwapDimensions = () => {
    if (xKey && seriesKey) {
      onChange({
        ...chart,
        xKey: seriesKey,
        seriesKey: xKey,
      });
    }
  };

  const showSwapButton = innerDim && outerDim && outerDim !== 'None';

  const metadataKeys = useMemo(
    () => getFieldsByPrefix(agentRunMetadataFields, 'metadata.'),
    // .filter((field) => !field.name.includes('run_id')) // Filter out run_id because too high cardinality
    [agentRunMetadataFields]
  );

  const scoreKeys = useMemo(
    () => getFieldsByPrefix(agentRunMetadataFields, 'metadata.scores.'),
    [agentRunMetadataFields]
  );

  function handleChartTypeChange(value: string) {
    onChange({ ...chart, chartType: value as 'bar' | 'line' | 'table' });
  }

  function handleYDimChange(value: string) {
    onChange({ ...chart, yKey: value });
  }

  return (
    <div className="flex flex-col lg:flex-row items-start sm:items-center gap-2 p-2">
      <div className="flex items-center space-x-1 overflow-x-auto min-w-0 w-full">
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          Type:
        </span>
        <Select value={chart.chartType} onValueChange={handleChartTypeChange}>
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
        <Select value={yKey} onValueChange={handleYDimChange}>
          <SelectTrigger className="h-6 max-w-24 w-24 text-xs border-border bg-transparent hover:bg-secondary px-2 font-normal">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {scoreKeys.map((key) => (
              <SelectItem key={key} value={key} className="text-xs">
                {key}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
