'use client';

import { useMemo, useState, useEffect } from 'react';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Label } from '@/app/api/labelApi';
import { cn } from '@/lib/utils';
import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { useLabelSets } from '@/providers/use-label-sets';
import { SchemaDefinition } from '@/app/types/schema';
import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import { applyGeneralFilters } from '../utils/viewModeResults';
import { useResultFilterControls } from '@/providers/use-result-filters';
import { useParams } from 'next/navigation';

interface AgreementPopoverProps {
  agentRunResults: AgentRunJudgeResults[];
  labels: Label[];
  schema?: SchemaDefinition;
}

export const AgreementPopover = ({
  agentRunResults,
  labels,
  schema,
}: AgreementPopoverProps) => {
  const { rubric_id: rubricId } = useParams<{
    rubric_id: string;
  }>();

  const { activeLabelSet } = useLabelSets(rubricId);

  // Filter for properties that can be counted (statistics computed for)
  const countableProperties: string[] = useMemo(() => {
    if (!schema) return [];
    return Object.keys(schema.properties).filter((key) => {
      switch (schema.properties[key].type) {
        case 'string':
          return 'enum' in schema.properties[key] ? true : false;
        case 'integer':
        case 'number':
          return true;
        case 'boolean':
          return true;
        default:
          return false;
      }
    });
  }, [schema]);

  // Get first results per agent run for filtering
  const firstResults = useMemo(
    () => agentRunResults.map((arr) => arr.results[0]).filter(Boolean),
    [agentRunResults]
  );

  // Apply the filters to the runs
  const { filters } = useResultFilterControls();
  const filteredFirstResults = useMemo(
    () => firstResults.filter((result) => applyGeneralFilters(result, filters)),
    [firstResults, filters]
  );
  // Track the selected property for the visible selection
  const [selectedProperty, setSelectedProperty] = useState<string | null>(null);

  // Default to the first property
  useEffect(() => {
    if (countableProperties.length > 0 && activeLabelSet) {
      setSelectedProperty(countableProperties[0]);
    }
  }, [countableProperties, activeLabelSet]);

  // Calculate agreement for each property
  const propertyStats = useMemo(() => {
    if (!filteredFirstResults || !activeLabelSet) {
      return {};
    }

    return calculatePropertyStats(
      filteredFirstResults,
      labels,
      countableProperties,
      activeLabelSet.id
    );
  }, [filteredFirstResults, labels, countableProperties, activeLabelSet]);

  const statsContent = () => {
    if (!activeLabelSet) return null;

    return (
      <div className="space-y-2 max-h-64 overflow-y-auto">
        <div className="text-xs font-semibold text-foreground border-b pb-1">
          {activeLabelSet.name}
        </div>
        {Object.entries(propertyStats).map(([property, { total, matches }]) => {
          const isSelected = selectedProperty === property;
          return (
            <div
              key={property}
              className="flex items-center justify-between text-xs rounded px-2 py-1 cursor-pointer hover:bg-secondary/70 transition-colors"
              onClick={() => setSelectedProperty(property)}
            >
              <span
                className={cn(
                  'font-mono text-muted-foreground flex items-center gap-1',
                  isSelected && 'font-bold'
                )}
              >
                {property}
                {isSelected && (
                  <div className="!size-1.5 ml-1 bg-blue-500 rounded-full" />
                )}
              </span>
              <div className={cn('flex items-center gap-2 ')}>
                <div className="flex items-center gap-3">
                  <div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden">
                    <div
                      className={cn('h-full transition-all bg-blue-500')}
                      style={{ width: `${(matches / total) * 100}%` }}
                    />
                  </div>
                  <span className="text-muted-foreground">
                    {matches}/{total}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const content = () => {
    if (filteredFirstResults.length === 0) {
      return (
        <span className="text-xs text-muted-foreground">
          No judge results to compute stats.
        </span>
      );
    } else if (!activeLabelSet) {
      return (
        <span className="text-xs text-muted-foreground">
          Select an active label set to compute stats.
        </span>
      );
    } else if (selectedProperty === null) {
      return (
        <span className="text-xs text-muted-foreground">
          Add a countable label to compute stats.
        </span>
      );
    } else if (labels.length === 0) {
      return (
        <span className="text-xs text-muted-foreground">
          No labels to compute stats.
        </span>
      );
    } else if (countableProperties.length > 0) {
      return statsContent();
    }
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className="text-xs h-7 gap-2 text-muted-foreground items-center flex justify-center px-2">
          <span className="font-mono truncate">
            {selectedProperty && activeLabelSet
              ? `${activeLabelSet.name}.${selectedProperty}`
              : ''}
          </span>
          {selectedProperty && activeLabelSet ? (
            <span className="whitespace-nowrap">
              {propertyStats[selectedProperty]
                ? propertyStats[selectedProperty].matches
                : '-'}
              /
              {propertyStats[selectedProperty]
                ? propertyStats[selectedProperty].total
                : '-'}
            </span>
          ) : (
            <span>
              Agreement <span className="font-mono">null</span>
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-3" align="end" sideOffset={6}>
        <div className="space-y-3">
          <div className="text-xs font-medium">Agreement</div>
          {content()}
        </div>
      </PopoverContent>
    </Popover>
  );
};

function calculatePropertyStats(
  filteredJudgeResults: JudgeResultWithCitations[],
  labels: Label[],
  countableProperties: string[],
  activeLabelSetId: string
): Record<string, { matches: number; total: number }> {
  const stats: Record<string, { matches: number; total: number }> = {};

  // Compare each result with its label from the active label set
  filteredJudgeResults.forEach((result) => {
    // Find the label for this agent_run_id from the active label set
    const label = labels.find(
      (l) =>
        l.agent_run_id === result.agent_run_id &&
        l.label_set_id === activeLabelSetId
    );

    if (!label) return;

    countableProperties.forEach((key) => {
      const judgeValue = result.output[key];
      const labelValue = label.label_value[key];

      // Only count if both values exist
      if (judgeValue !== undefined && labelValue !== undefined) {
        // Initialize property stats if not exists
        if (!stats[key]) {
          stats[key] = { matches: 0, total: 0 };
        }

        stats[key].total++;

        // Check for match
        if (judgeValue === labelValue) {
          stats[key].matches++;
        }
      }
    });
  });

  return stats;
}
