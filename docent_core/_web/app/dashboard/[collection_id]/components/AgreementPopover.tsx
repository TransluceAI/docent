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
import { EyeIcon } from 'lucide-react';
import { SchemaDefinition } from '@/app/types/schema';

interface AgreementPopoverProps {
  filteredJudgeResults: JudgeResultWithCitations[];
  labels: Label[];
  schema?: SchemaDefinition;
}

export const AgreementPopover = ({
  filteredJudgeResults,
  labels,
  schema,
}: AgreementPopoverProps) => {
  const { labelSets } = useLabelSets();

  // Filter for properties that can be counted (statistics computed for)
  const countableProperties: string[] = useMemo(() => {
    if (!schema) return [];
    return Object.keys(schema.properties).filter((key) => {
      switch (schema.properties[key].type) {
        case 'string':
          return 'enum' in schema.properties[key] ? true : false;
        case 'integer':
          return true;
        case 'boolean':
          return true;
        default:
          return false;
      }
    });
  }, [schema]);

  // Track both label set and property for the visible selection
  const [selected, setSelected] = useState<{
    labelSetId: string;
    property: string;
  } | null>(null);

  // Default to the first label set and property
  useEffect(() => {
    if (countableProperties.length > 0 && labelSets.length > 0) {
      setSelected({
        labelSetId: labelSets[0].id,
        property: countableProperties[0],
      });
    }
  }, [countableProperties, labelSets]);

  // Calculate agreement for each property per label set
  const propertyStats = useMemo(() => {
    if (!filteredJudgeResults) {
      return {};
    }

    return calculatePropertyStatsByLabelSet(
      filteredJudgeResults,
      labels,
      countableProperties
    );
  }, [filteredJudgeResults, labels, countableProperties]);

  const statsContent = () => {
    return (
      <div className="space-y-4 max-h-64 overflow-y-auto">
        {labelSets.map((labelSet) => {
          const labelSetStats = propertyStats[labelSet.id] || {};
          const labelSetName = labelSet.name;
          const isSelected = (property: string) =>
            selected?.labelSetId === labelSet.id &&
            selected?.property === property;
          return (
            <div key={labelSet.id} className="space-y-2">
              <div className="text-xs font-semibold text-foreground border-b pb-1">
                {labelSetName}
              </div>
              {Object.entries(labelSetStats).map(
                ([property, { total, matches }]) => (
                  <div
                    key={`${labelSet.id}-${property}`}
                    className="flex items-center justify-between text-xs rounded px-2 py-1 cursor-pointer hover:bg-secondary/70 transition-colors"
                    onClick={() =>
                      setSelected({ labelSetId: labelSet.id, property })
                    }
                  >
                    <span
                      className={cn(
                        'font-mono text-muted-foreground flex items-center gap-1',
                        isSelected(property) && 'font-bold'
                      )}
                    >
                      {property}
                      {isSelected(property) && <EyeIcon className="size-3" />}
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
                )
              )}
            </div>
          );
        })}
      </div>
    );
  };

  const content = () => {
    if (filteredJudgeResults.length === 0) {
      return (
        <span className="text-xs text-muted-foreground">
          No judge results to compute stats.
        </span>
      );
    } else if (selected === null) {
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
    } else if (countableProperties.length > 0 && labelSets.length > 0) {
      return statsContent();
    }
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className="text-xs h-7 gap-2 text-muted-foreground items-center flex justify-center px-2">
          <span className="font-mono truncate">
            {selected
              ? `${labelSets.find((ls) => ls.id === selected.labelSetId)?.name || selected.labelSetId}.${selected.property}`
              : ''}
          </span>
          {selected ? (
            <span className="whitespace-nowrap">
              {propertyStats[selected.labelSetId]?.[selected.property]
                ? propertyStats[selected.labelSetId][selected.property].matches
                : '-'}
              /
              {propertyStats[selected.labelSetId]?.[selected.property]
                ? propertyStats[selected.labelSetId][selected.property].total
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

function calculatePropertyStatsByLabelSet(
  filteredJudgeResults: JudgeResultWithCitations[],
  labels: Label[],
  countableProperties: string[]
): Record<string, Record<string, { matches: number; total: number }>> {
  // Group stats by label set, then by property
  const statsByLabelSet: Record<
    string,
    Record<string, { matches: number; total: number }>
  > = {};

  // Compare each result with all its labels (grouped by label set)
  filteredJudgeResults.forEach((result) => {
    // Find all labels for this agent_run_id
    const labelsForRun = labels.filter(
      (label) => label.agent_run_id === result.agent_run_id
    );

    labelsForRun.forEach((label) => {
      const labelSetId = label.label_set_id;

      // Initialize label set stats if not exists
      if (!statsByLabelSet[labelSetId]) {
        statsByLabelSet[labelSetId] = {};
      }

      countableProperties.forEach((key) => {
        const judgeValue = result.output[key];
        const labelValue = label.label_value[key];

        // Only count if both values exist
        if (judgeValue !== undefined && labelValue !== undefined) {
          // Initialize property stats if not exists
          if (!statsByLabelSet[labelSetId][key]) {
            statsByLabelSet[labelSetId][key] = { matches: 0, total: 0 };
          }

          statsByLabelSet[labelSetId][key].total++;

          // Check for match
          if (judgeValue === labelValue) {
            statsByLabelSet[labelSetId][key].matches++;
          }
        }
      });
    });
  });

  return statsByLabelSet;
}
