'use client';

import { useMemo } from 'react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tags, Split, AlertCircle } from 'lucide-react';
import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import { cn } from '@/lib/utils';
import { applyViewModeResults, ViewMode } from '../utils/viewModeResults';
import { Label } from '@/app/api/labelApi';

interface ViewModeOption {
  value: ViewMode;
  label: string;
  subtitle?: string;
  icon?: React.ComponentType<{ className?: string }>;
}

const VIEW_MODE_OPTIONS: ViewModeOption[] = [
  {
    value: 'all',
    label: 'All results',
  },
  {
    value: 'labeled_disagreement',
    label: 'Labeled runs',
    subtitle: 'Sort by judge/human disagreement',
    icon: Tags,
  },
  {
    value: 'missing_labels',
    label: 'Missing labels',
    subtitle: 'Sort by judge rollout disagreement',
    icon: Split,
  },
  {
    value: 'incomplete_labels',
    label: 'Incomplete labels',
    icon: AlertCircle,
  },
];

interface ViewModeDropdownProps {
  agentRunResults: AgentRunJudgeResults[];
  labels: Label[];
  className?: string;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
}

export default function ViewModeDropdown({
  agentRunResults,
  labels,
  className,
  viewMode,
  setViewMode,
}: ViewModeDropdownProps) {
  const counts = useMemo(() => {
    const viewModes: ViewMode[] = [
      'all',
      'labeled_disagreement',
      'missing_labels',
      'incomplete_labels',
    ];

    const countsMap: Record<ViewMode, number> = {} as Record<ViewMode, number>;

    for (const mode of viewModes) {
      const filteredAgentRuns = applyViewModeResults(
        agentRunResults,
        labels,
        mode,
        null
      );
      countsMap[mode] = filteredAgentRuns.length;
    }

    return countsMap;
  }, [agentRunResults, labels]);

  const currentOption = VIEW_MODE_OPTIONS.find(
    (option) => option.value === viewMode
  );
  const Icon = currentOption?.icon;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('h-7 gap-1.5 text-xs font-normal', className)}
        >
          {Icon && <Icon className="h-3 w-3" />}
          <span className="hidden sm:inline">{currentOption?.label}</span>
          <Badge variant="secondary" className="h-4 px-1 text-xs font-normal">
            {counts[viewMode]}
          </Badge>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80">
        {VIEW_MODE_OPTIONS.map((option) => {
          const OptionIcon = option.icon;
          const isSelected = viewMode === option.value;

          return (
            <DropdownMenuItem
              key={option.value}
              onClick={() => setViewMode(option.value)}
              className={cn(
                'flex flex-col items-start gap-0.5 py-1.5 cursor-pointer',
                isSelected && 'bg-accent'
              )}
            >
              <div className="flex items-center justify-between w-full">
                <div className="flex items-center gap-2">
                  {OptionIcon && (
                    <OptionIcon className="h-3.5 w-3.5 text-muted-foreground" />
                  )}
                  <span className="font-medium text-xs">{option.label}</span>
                </div>
                <Badge
                  variant={isSelected ? 'default' : 'secondary'}
                  className="h-4 px-1.5 text-xs font-normal"
                >
                  {counts[option.value]}
                </Badge>
              </div>
              <span className="text-xs text-muted-foreground pl-5">
                {option.subtitle}
              </span>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
