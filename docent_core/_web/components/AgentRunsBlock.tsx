import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { ScorePill } from './ScorePill';

// Shared types for agent runs
export interface RunItem {
  id: string;
  replica_idx: number;
  grade: number | null;
  state: 'in_progress' | 'completed' | 'errored';
  error_type?: string;
  error_message?: string;
}

export interface Block {
  cfId: string;
  name: string;
  items: RunItem[];
  mean: number;
}

// Utility function to sort runs by grade (descending, with N/A at bottom)
// Secondary sort by replica_idx (ascending) when grades are equal
export const sortRunsByGrade = (items: RunItem[]): RunItem[] => {
  return [...items].sort((a, c) => {
    const ag = a.grade;
    const cg = c.grade;
    const aNan = ag === null || Number.isNaN(ag);
    const cNan = cg === null || Number.isNaN(cg);

    // Both are N/A - sort by replica_idx
    if (aNan && cNan) return a.replica_idx - c.replica_idx;

    // One is N/A - N/A goes to bottom
    if (aNan) return 1;
    if (cNan) return -1;

    // Both have grades - sort by grade descending, then by replica_idx ascending
    const gradeDiff = (cg as number) - (ag as number);
    if (gradeDiff === 0) {
      return a.replica_idx - c.replica_idx;
    }
    return gradeDiff;
  });
};

// Utility to compute mean score (excluding null grades)
export const computeMeanScore = (items: RunItem[]): number => {
  const graded = items.filter(
    (x) => typeof x.grade === 'number' && !Number.isNaN(x.grade)
  ) as Array<RunItem & { grade: number }>;

  return graded.length
    ? graded.reduce((s, x) => s + x.grade, 0) / graded.length
    : Number.NaN;
};

interface AgentRunsBlockProps {
  block: Block;
  selectedAgentRunId?: string | null;
  onReplicaClick: (runId: string) => void;
  defaultOpen?: boolean;
  onToggle?: (blockId: string) => void;
}

/**
 * A collapsible block component for displaying agent runs with grades
 */
export const AgentRunsBlock: React.FC<AgentRunsBlockProps> = ({
  block,
  selectedAgentRunId,
  onReplicaClick,
  defaultOpen = false,
  onToggle,
}) => {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isOpen = defaultOpen !== undefined ? defaultOpen : internalOpen;

  const meanStr = Number.isNaN(block.mean) ? 'N/A' : block.mean.toFixed(2);

  return (
    <div className="border border-border rounded-md">
      <button
        onClick={() => {
          if (onToggle) {
            onToggle(block.cfId);
          } else {
            setInternalOpen(!internalOpen);
          }
        }}
        className="w-full flex items-center justify-between p-3"
      >
        <div className="flex items-center gap-2">
          {isOpen ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
          <span className="text-sm font-medium text-primary">{block.name}</span>
        </div>
        <ScorePill
          score={Number.isNaN(block.mean) ? null : block.mean}
          title={
            Number.isNaN(block.mean) ? 'Mean score' : `Mean score: ${meanStr}`
          }
        />
      </button>

      {isOpen && (
        <div className="p-3 space-y-2">
          {block.items.map((item) => (
            <AgentRunItem
              key={item.id}
              item={item}
              isSelected={selectedAgentRunId === item.id}
              onClick={() => onReplicaClick(item.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
};

interface AgentRunItemProps {
  item: RunItem;
  isSelected: boolean;
  onClick: () => void;
}

/**
 * Individual agent run item component
 */
const AgentRunItem: React.FC<AgentRunItemProps> = ({
  item,
  isSelected,
  onClick,
}) => {
  return (
    <div
      className={`flex items-center justify-between text-sm py-1.5 px-2 rounded-md cursor-pointer transition-colors ${
        isSelected
          ? 'bg-indigo-bg border border-indigo-border'
          : 'hover:bg-secondary'
      }`}
      onClick={onClick}
    >
      <div className="flex items-center gap-2">
        <span className="text-primary">Replica {item.replica_idx}</span>
        {item.state === 'errored' && item.error_message && (
          <span
            className="text-xs text-red-text bg-red-bg px-2 py-1 rounded border border-red-border"
            title={`Error: ${item.error_message}`}
          >
            Error: {item.error_type?.replace(/_/g, ' ') || 'Unknown'}
          </span>
        )}
      </div>
      <div className="flex items-center gap-3">
        <ScorePill
          score={
            item.grade === null || Number.isNaN(item.grade) ? null : item.grade
          }
          title="Score"
        />
        {item.state === 'in_progress' && (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        )}
      </div>
    </div>
  );
};
