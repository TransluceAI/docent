import React from 'react';
import {
  FileText,
  Folder,
  FolderOpen,
  Maximize2,
  Minimize2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  AgentRun,
  Transcript,
  TranscriptGroup,
} from '@/app/types/transcriptTypes';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { MetadataPopover } from '@/components/metadata/MetadataPopover';
import { MetadataBlock } from '@/components/metadata/MetadataBlock';
import { Checkbox } from '@/components/ui/checkbox';

// Unified tree node type: a node can be a group or a transcript
export interface TreeNode {
  type: 'group' | 'transcript';
  id: string; // group id or transcript key
  level: number; // indentation level for rendering
  children?: TreeNode[]; // only for group nodes
}

// Component for rendering a single node (recursive for groups)
const TreeNodeView: React.FC<{
  node: TreeNode;
  selectedTranscriptId: string | null;
  selectedTranscriptGroupId: string | null;
  expandedGroups: Set<string>;
  onTranscriptSelect: (transcriptId: string) => void;
  onGroupToggle: (groupId: string) => void;
  agentRun: AgentRun;
  transcriptsById: Record<string, Transcript>;
  transcriptGroupsById: Record<string, TranscriptGroup>;
}> = ({
  node,
  selectedTranscriptId,
  selectedTranscriptGroupId,
  expandedGroups,
  onTranscriptSelect,
  onGroupToggle,
  agentRun,
  transcriptsById,
  transcriptGroupsById,
}) => {
  if (node.type === 'transcript') {
    return (
      <TranscriptListItem
        transcriptId={node.id}
        selectedTranscriptId={selectedTranscriptId}
        agentRun={agentRun}
        transcriptsById={transcriptsById}
        onTranscriptSelect={onTranscriptSelect}
        level={node.level}
      />
    );
  }

  const group = transcriptGroupsById[node.id];
  const isExpanded = expandedGroups.has(node.id);
  const isSelected = selectedTranscriptGroupId === node.id;

  return (
    <div className="space-y-1">
      {/* Group Header */}
      <div
        className={cn(
          'flex items-center text-xs rounded border transition-colors min-w-0',
          isSelected
            ? 'bg-indigo-bg border-indigo-border text-primary'
            : 'bg-muted/60 border-border/80 text-primary/80 hover:bg-muted hover:text-primary'
        )}
        style={{ marginLeft: `${node.level * 12}px` }}
      >
        <button
          onClick={() => onGroupToggle(node.id)}
          className="flex items-center flex-1 px-2 py-1 min-w-0 cursor-pointer"
        >
          {isExpanded ? (
            <FolderOpen className="h-3 w-3 mr-1 flex-shrink-0" />
          ) : (
            <Folder className="h-3 w-3 mr-1 flex-shrink-0" />
          )}
          <span className="text-ellipsis whitespace-nowrap overflow-hidden min-w-0">
            {group?.name || node.id}
          </span>
        </button>
        {(group && Object.keys(group.metadata || {}).length > 0) || node.id ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex h-full items-center">
                <MetadataPopover.Root>
                  <MetadataPopover.Trigger>
                    <button
                      className={cn(
                        'p-0.5 mr-1 rounded transition-colors',
                        isSelected
                          ? 'hover:bg-indigo-bg text-primary'
                          : 'hover:bg-muted text-primary/80'
                      )}
                    >
                      <FileText className="h-3 w-3" />
                    </button>
                  </MetadataPopover.Trigger>
                  <MetadataPopover.Content
                    title={`Transcript Group Metadata - ${group?.name || node.id}`}
                  >
                    <MetadataPopover.Body metadata={group?.metadata || {}}>
                      {(md) => <MetadataBlock metadata={md} />}
                    </MetadataPopover.Body>
                  </MetadataPopover.Content>
                </MetadataPopover.Root>
              </div>
            </TooltipTrigger>
            <TooltipContent side="left" align="center">
              <p>View transcript group metadata</p>
            </TooltipContent>
          </Tooltip>
        ) : null}
      </div>

      {/* Expanded Content */}
      {isExpanded && node.children && node.children.length > 0 && (
        <div className="space-y-1">
          {node.children.map((childNode) => (
            <TreeNodeView
              key={`${childNode.type}:${childNode.id}`}
              node={childNode}
              selectedTranscriptId={selectedTranscriptId}
              selectedTranscriptGroupId={selectedTranscriptGroupId}
              expandedGroups={expandedGroups}
              onTranscriptSelect={onTranscriptSelect}
              onGroupToggle={onGroupToggle}
              agentRun={agentRun}
              transcriptsById={transcriptsById}
              transcriptGroupsById={transcriptGroupsById}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// Component for individual transcript items
const TranscriptListItem: React.FC<{
  transcriptId: string;
  selectedTranscriptId: string | null;
  agentRun: AgentRun;
  transcriptsById: Record<string, Transcript>;
  onTranscriptSelect: (key: string) => void;
  level?: number;
}> = ({
  transcriptId,
  selectedTranscriptId,
  agentRun,
  transcriptsById,
  onTranscriptSelect,
  level = 0,
}) => (
  <div
    className={cn(
      'flex items-center text-xs rounded border transition-colors min-w-0',
      selectedTranscriptId === transcriptId
        ? 'bg-blue-bg border-blue-border text-primary'
        : 'bg-secondary border-border text-primary hover:bg-blue-bg/50 hover:border-blue-border/50'
    )}
    style={{ marginLeft: `${level * 12}px` }}
  >
    <button
      onClick={() => onTranscriptSelect(transcriptId)}
      className="flex-1 text-left px-2 py-1.5 text-ellipsis whitespace-nowrap overflow-hidden min-w-0 font-medium"
      title={transcriptId}
    >
      {transcriptId}
    </button>
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex h-full items-center">
          <MetadataPopover.Root>
            <MetadataPopover.Trigger>
              <button
                className={cn(
                  'p-0.5 mr-1 rounded transition-colors',
                  selectedTranscriptId === transcriptId
                    ? 'hover:bg-blue-bg text-primary'
                    : 'hover:bg-accent text-muted-foreground'
                )}
              >
                <FileText className="h-3 w-3" />
              </button>
            </MetadataPopover.Trigger>
            <MetadataPopover.Content title={`Transcript Metadata`}>
              <MetadataPopover.Body
                metadata={transcriptsById[transcriptId]?.metadata || {}}
              >
                {(md) => <MetadataBlock metadata={md} />}
              </MetadataPopover.Body>
            </MetadataPopover.Content>
          </MetadataPopover.Root>
        </div>
      </TooltipTrigger>
      <TooltipContent side="left" align="center">
        <p>View transcript metadata</p>
      </TooltipContent>
    </Tooltip>
  </div>
);

// Pure navigation component - only concerned with rendering the transcript tree
export const TranscriptNavigator: React.FC<{
  nodes: TreeNode[];
  selectedTranscriptId: string | null;
  selectedTranscriptGroupId: string | null;
  expandedGroups: Set<string>;
  agentRun: AgentRun;
  transcriptsById: Record<string, Transcript>;
  transcriptGroupsById: Record<string, TranscriptGroup>;
  onTranscriptSelect: (key: string) => void;
  onGroupToggle: (groupId: string) => void;
  className?: string; // applies to the scrollable list container
  // Optional header controls
  showHeader?: boolean;
  headerLeft?: React.ReactNode;
  headerClassName?: string;
  fullTree?: boolean;
  onFullTreeChange?: (v: boolean) => void;
  onToggleAllGroups?: () => void;
  allGroupsExpanded?: boolean;
}> = ({
  nodes,
  selectedTranscriptId,
  selectedTranscriptGroupId,
  expandedGroups,
  agentRun,
  transcriptsById,
  transcriptGroupsById,
  onTranscriptSelect,
  onGroupToggle,
  className,
  showHeader = false,
  headerLeft,
  headerClassName,
  fullTree = false,
  onFullTreeChange,
  onToggleAllGroups,
  allGroupsExpanded,
}) => {
  const hasGroups = (agentRun?.transcript_groups || []).length > 0;

  return (
    <div className="flex flex-col min-h-0">
      {showHeader && (
        <div
          className={cn(
            'flex items-center justify-between mb-2',
            headerClassName
          )}
        >
          <div className="flex items-center space-x-1">
            {headerLeft}
            <div className="text-xs font-medium text-primary">Transcripts</div>
          </div>
          <div className="flex items-center gap-2">
            {typeof fullTree !== 'undefined' && onFullTreeChange && (
              <label className="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer select-none">
                <Checkbox
                  checked={!!fullTree}
                  onCheckedChange={(v) => onFullTreeChange(!!v)}
                  className="h-3.5 w-3.5"
                />
                <span>Full tree</span>
              </label>
            )}
            {hasGroups && onToggleAllGroups && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={onToggleAllGroups}
                    className="p-0.5 rounded text-muted-foreground hover:text-primary hover:bg-muted transition-colors"
                    aria-label={
                      allGroupsExpanded
                        ? 'Collapse all groups'
                        : 'Expand all groups'
                    }
                  >
                    {allGroupsExpanded ? (
                      <Minimize2 className="h-3 w-3" />
                    ) : (
                      <Maximize2 className="h-3 w-3" />
                    )}
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom" align="end">
                  <p>
                    {allGroupsExpanded
                      ? 'Collapse all groups'
                      : 'Expand all groups'}
                  </p>
                </TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>
      )}
      <div className={cn('space-y-1 custom-scrollbar', className)}>
        {nodes.map((node) => (
          <TreeNodeView
            key={`${node.type}:${node.id}`}
            node={node}
            selectedTranscriptId={selectedTranscriptId}
            selectedTranscriptGroupId={selectedTranscriptGroupId}
            expandedGroups={expandedGroups}
            onTranscriptSelect={onTranscriptSelect}
            onGroupToggle={onGroupToggle}
            agentRun={agentRun}
            transcriptsById={transcriptsById}
            transcriptGroupsById={transcriptGroupsById}
          />
        ))}
      </div>
    </div>
  );
};

export default TranscriptNavigator;
