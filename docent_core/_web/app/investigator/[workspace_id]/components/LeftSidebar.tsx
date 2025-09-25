'use client';

import React from 'react';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
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

  return (
    <div
      className={`p-3 rounded-md cursor-pointer transition-colors ${
        isSelected && !isCreatingNew
          ? 'bg-background border border-border'
          : 'hover:bg-background'
      }`}
      onClick={onSelect}
    >
      <div className="font-medium text-sm">
        Experiment #{experiment.id.slice(0, 8)}
      </div>
      <div className="text-xs text-muted-foreground">
        {formatDateTime(experiment.created_at)}
      </div>
      {isRunning ? (
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
      ) : status === 'completed' ? (
        <div className="mt-2 text-xs text-green-text">Completed</div>
      ) : status === 'error' || status === 'errored' ? (
        <div className="mt-2 text-xs text-red-text">Error</div>
      ) : status === 'cancelled' ? (
        <div className="mt-2 text-xs text-red-text">Cancelled</div>
      ) : null}
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
