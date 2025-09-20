'use client';

import { useMemo, useState, useEffect } from 'react';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useGetRubricQuery } from '@/app/api/rubricApi';
import { cn } from '@/lib/utils';
import { useResultFilterControls } from '@/providers/use-result-filters';
import { Pencil } from 'lucide-react';
import { useParams } from 'next/navigation';
import {
  JudgeResultWithCitations,
  JudgeRunLabel,
} from '@/app/store/rubricSlice';
import { useRubricVersion } from '@/providers/use-rubric-version';

interface AgreementPopoverProps {
  judgeResults: JudgeResultWithCitations[];
  judgeRunLabels: JudgeRunLabel[];
}

export const AgreementPopover = ({
  judgeResults,
  judgeRunLabels,
}: AgreementPopoverProps) => {
  const { rubric_id: rubricId, collection_id: collectionId } = useParams<{
    rubric_id: string;
    collection_id: string;
  }>();
  const { version } = useRubricVersion();

  // Fetch data using existing queries
  const { data: rubric } = useGetRubricQuery({
    collectionId,
    rubricId,
    version,
  });
  const schema = rubric?.output_schema;
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

  // Apply the filters to the runs
  const { applyFilters } = useResultFilterControls();
  const filteredJudgeResults = useMemo(
    () => applyFilters(judgeResults, judgeRunLabels),
    [applyFilters, judgeResults, judgeRunLabels]
  );

  // Set the visible property (one on the trigger) to the first countable property
  const [visibleProperty, setVisibleProperty] = useState<string | null>(null);
  const [isEditMode, setIsEditMode] = useState(false);

  useEffect(() => {
    if (countableProperties.length > 0) {
      setVisibleProperty(countableProperties[0]);
    }
  }, [countableProperties]);

  // Calculate agreement for each property
  const propertyStats = useMemo(() => {
    if (!rubric?.output_schema || !filteredJudgeResults) {
      return {};
    }

    // Create a map of agent_run_id to label
    const resultAndLabelList = filteredJudgeResults.map((result) => {
      return {
        result,
        label: judgeRunLabels.find(
          (label) => label.agent_run_id === result.agent_run_id
        ),
      };
    });

    // Track agreement for each property
    const propertyStats: Record<string, { matches: number; total: number }> =
      {};

    // Compare each result with its label
    resultAndLabelList.forEach(({ result, label }) => {
      if (!label) return; // Skip if no label exists

      countableProperties.forEach((key) => {
        const judgeValue = result.output[key];
        const labelValue = label.label[key];

        // Only count if both values exist
        if (judgeValue !== undefined && labelValue !== undefined) {
          // Initialize property stats if not exists
          if (!propertyStats[key]) {
            propertyStats[key] = { matches: 0, total: 0 };
          }

          propertyStats[key].total++;

          // Check for match
          if (judgeValue === labelValue) {
            propertyStats[key].matches++;
          }
        }
      });
    });

    return propertyStats;
  }, [rubric, filteredJudgeResults, judgeRunLabels, countableProperties]);

  const handlePropertySelect = (property: string) => {
    setVisibleProperty(property);
    setIsEditMode(false);
  };

  const statsContent = () => {
    return (
      <div className="space-y-2">
        {Object.entries(propertyStats).map(([property, { total, matches }]) => (
          <div
            key={property}
            className={cn(
              'flex items-center justify-between text-xs rounded px-2 py-1',
              isEditMode &&
                'cursor-pointer hover:bg-secondary/70 transition-colors',
              isEditMode && visibleProperty === property && 'border'
            )}
            onClick={
              isEditMode ? () => handlePropertySelect(property) : undefined
            }
          >
            <span
              className={cn(
                'font-mono text-muted-foreground',
                visibleProperty === property && 'font-bold'
              )}
            >
              {property}
            </span>
            <div
              className={cn(
                'flex items-center gap-2',
                isEditMode && 'opacity-40'
              )}
            >
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
        ))}
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
    } else if (visibleProperty === null) {
      return (
        <span className="text-xs text-muted-foreground">
          Add a countable label to compute stats.
        </span>
      );
    } else if (judgeRunLabels.length === 0) {
      return (
        <span className="text-xs text-muted-foreground">
          No judge run labels to compute stats.
        </span>
      );
    } else if (countableProperties.length > 0) {
      return statsContent();
    }
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className="text-xs min-h-7 w-40 text-end text-muted-foreground hover:text-primary disabled:text-muted-foreground transition-colors">
          <span className="hidden 2xl:inline">
            <span className="font-mono">{visibleProperty} </span>
          </span>
          agreement:{' '}
          {visibleProperty ? (
            <span>
              {propertyStats[visibleProperty]
                ? propertyStats[visibleProperty]?.matches
                : '-'}
              /
              {propertyStats[visibleProperty]
                ? propertyStats[visibleProperty]?.total
                : '-'}
            </span>
          ) : (
            '-'
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-3" align="end" sideOffset={6}>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-xs font-medium">Per property</div>
            <button
              onClick={() => setIsEditMode(!isEditMode)}
              className="p-1 hover:bg-secondary disabled:hover:bg-transparent disabled:cursor-not-allowed rounded transition-colors"
              aria-label="Edit visible property"
              disabled={
                filteredJudgeResults.length === 0 ||
                countableProperties.length === 0 ||
                judgeRunLabels.length === 0
              }
            >
              <Pencil className="h-3 w-3 text-muted-foreground" />
            </button>
          </div>
          {content()}
          {isEditMode && (
            <div className="text-xs text-muted-foreground">
              Select a property to display on the button
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
};
