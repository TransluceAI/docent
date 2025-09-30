'use client';

import React from 'react';
import { Plus, CheckCircle, XCircle, AlertCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

// Synchronized spinner animation - all spinners will be in sync
const spinnerStyle = {
  animation: 'spin 2s linear infinite',
  transformOrigin: 'center center',
};
import type { ExperimentConfig } from '@/app/api/investigatorApi';
import { formatDateTime } from '@/lib/dateUtils';
import {
  useGetActiveExperimentJobsQuery,
  useGetExperimentResultQuery,
} from '@/app/api/investigatorApi';
import { useParams } from 'next/navigation';

interface LeftSidebarProps {
  experiments?: ExperimentConfig[];
  selectedExperimentId?: string;
  isCreatingNew?: boolean;
  onExperimentSelect?: (id: string) => void;
  onNewExperiment?: () => void;
}

// Component to show status for a single experiment
function ExperimentItem({
  experiment,
  isSelected,
  isCreatingNew,
  onSelect,
  activeJobInfo,
}: {
  experiment: ExperimentConfig;
  isSelected: boolean;
  isCreatingNew: boolean;
  onSelect: () => void;
  activeJobInfo?: { job_id: string | null; status: string | null };
}) {
  const params = useParams();
  const workspaceId = params.workspace_id as string;

  // Get experiment result for status and progress
  const isRunning = !!activeJobInfo?.job_id;
  const { data: experimentResult } = useGetExperimentResultQuery(
    { workspaceId, experimentConfigId: experiment.id },
    {
      // Poll frequently when running to get progress updates
      pollingInterval: isRunning ? 2000 : 0,
      refetchOnMountOrArgChange: true,
    }
  );

  // Determine status and progress
  const status =
    experimentResult?.experiment_status?.status ||
    (isRunning ? 'running' : undefined);
  const progress = experimentResult?.experiment_status?.progress ?? 0;
  const percent = Math.max(0, Math.min(100, Math.round(progress * 100)));

  // Helper function to get experiment type name
  const getTypeName = (type: string) => {
    if (type === 'counterfactual') {
      return 'Counterfactual';
    } else if (type === 'simple_rollout') {
      return 'Rollout';
    }
    return 'Experiment';
  };

  // Helper function to get status icon
  const getStatusIcon = (status: string | undefined, isRunning: boolean) => {
    if (isRunning) {
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center">
              <Loader2
                className="w-4 h-4 text-blue-text"
                style={spinnerStyle}
              />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>Running</p>
          </TooltipContent>
        </Tooltip>
      );
    } else if (status === 'completed') {
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center">
              <CheckCircle className="w-4 h-4 text-green-text" />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>Completed</p>
          </TooltipContent>
        </Tooltip>
      );
    } else if (status === 'error') {
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center">
              <XCircle className="w-4 h-4 text-red-text" />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>Error</p>
          </TooltipContent>
        </Tooltip>
      );
    } else if (status === 'cancelled') {
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center">
              <AlertCircle className="w-4 h-4 text-red-text" />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>Cancelled</p>
          </TooltipContent>
        </Tooltip>
      );
    }
    return null;
  };

  return (
    <div
      className={`p-3 rounded-md cursor-pointer transition-colors ${
        isSelected && !isCreatingNew
          ? 'bg-background border border-border'
          : 'hover:bg-background'
      }`}
      onClick={onSelect}
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="font-medium text-sm">
          {getTypeName(experiment.type)} #{experiment.id.slice(0, 8)}
        </div>
        {getStatusIcon(status, isRunning)}
      </div>

      <div className="text-xs text-muted-foreground mb-1">
        {formatDateTime(experiment.created_at)}
      </div>

      {/* Subject info */}
      <div className="text-xs text-muted-foreground mb-1">
        <span className="font-medium">Subject:</span>{' '}
        {experiment.openai_compatible_backend.name}
      </div>

      {/* Base context info */}
      <div className="text-xs text-muted-foreground mb-1">
        <span className="font-medium">Context:</span>{' '}
        {experiment.base_context.name.length > 20
          ? `${experiment.base_context.name.slice(0, 20)}...`
          : experiment.base_context.name}
      </div>

      {/* Judge info */}
      {experiment.judge_config && (
        <div className="text-xs text-muted-foreground mb-1">
          <span className="font-medium">Judge:</span>{' '}
          {experiment.judge_config.name || 'Unnamed Judge'}
        </div>
      )}

      {/* Counterfactual idea (only for counterfactual experiments) */}
      {experiment.type === 'counterfactual' && (
        <div className="text-xs text-muted-foreground mb-1">
          <span className="font-medium">Idea:</span>{' '}
          {experiment.idea.name.length > 20
            ? `${experiment.idea.name.slice(0, 20)}...`
            : experiment.idea.name}
        </div>
      )}

      {isRunning && (
        <div className="mt-2">
          <div className="relative h-4 w-full rounded border border-border bg-background">
            <div
              className="absolute left-0 top-0 h-full rounded bg-secondary"
              style={{ width: `${percent}%` }}
            />
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-[10px] leading-none text-muted-foreground">
                {percent}%
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function LeftSidebar({
  experiments = [],
  selectedExperimentId,
  isCreatingNew,
  onExperimentSelect,
  onNewExperiment,
}: LeftSidebarProps) {
  const params = useParams();
  const workspaceId = params.workspace_id as string;

  // Fetch all active jobs for the workspace in a single call
  const { data: activeJobs } = useGetActiveExperimentJobsQuery(
    workspaceId,
    { pollingInterval: 5000 } // Poll every 5 seconds
  );

  return (
    <div className="w-64 border-r bg-secondary flex flex-col">
      <div className="p-3 border-b">
        <Button
          className="w-full"
          size="sm"
          variant={isCreatingNew ? 'default' : 'outline'}
          onClick={onNewExperiment}
        >
          <Plus className="h-4 w-4 mr-2" />
          New Experiment
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-3 space-y-2">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Experiments
          </h3>
          {experiments.length === 0 ? (
            <div className="text-xs text-muted-foreground p-3 text-center">
              No experiments yet. Click &quot;New Experiment&quot; to create
              one.
            </div>
          ) : (
            experiments.map((exp) => (
              <ExperimentItem
                key={exp.id}
                experiment={exp}
                isSelected={selectedExperimentId === exp.id}
                isCreatingNew={!!isCreatingNew}
                onSelect={() => onExperimentSelect?.(exp.id)}
                activeJobInfo={activeJobs?.[exp.id]}
              />
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
