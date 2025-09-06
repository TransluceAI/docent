'use client';
import { navToAgentRun } from '@/lib/nav';
import { useRouter } from 'next/navigation';
import { useAppSelector } from '../store/hooks';
import { AgentRunMetadata } from './AgentRunMetadata';
import { cn } from '@/lib/utils';
import { BaseAgentRunMetadata } from '../types/collectionTypes';
import posthog from 'posthog-js';

interface AgentRunCardProps {
  agentRunId: string;
  metadata?: BaseAgentRunMetadata;
  isActive?: boolean;
}

export default function AgentRunCard({
  agentRunId,
  metadata,
  isActive,
}: AgentRunCardProps) {
  const router = useRouter();
  // Collection slice
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const shortUuid = agentRunId.split('-')[0];
  return (
    <div
      className={cn(
        'flex flex-col p-1 border rounded text-xs min-w-0 overflow-x-hidden transition-all duration-200',
        isActive
          ? 'border-indigo-border bg-indigo-bg hover:bg-indigo-bg'
          : 'bg-secondary/30 hover:bg-indigo-bg'
      )}
    >
      <div
        className="cursor-pointer"
        onMouseDown={(e) => {
          e.stopPropagation();

          posthog.capture('agent_run_clicked', {
            agent_run_id: agentRunId,
          });

          navToAgentRun(
            router,
            window,
            agentRunId,
            undefined,
            undefined,
            collectionId,
            undefined,
            e.button === 1 || e.metaKey || e.ctrlKey
          );
        }}
      >
        <div className="flex justify-between pb-0.5 items-center">
          <span className="text-primary shrink-0">
            Agent Run <span className="font-mono">{shortUuid}</span>
          </span>
        </div>
        <div>
          {/* Display metadata if available */}
          {metadata && <AgentRunMetadata metadata={metadata} />}
        </div>
      </div>
    </div>
  );
}
