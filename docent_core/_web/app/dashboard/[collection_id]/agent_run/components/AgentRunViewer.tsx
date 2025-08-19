import {
  ChevronDown,
  ChevronUp,
  FileText,
  Loader2,
  Folder,
  FolderOpen,
  Maximize2,
  Minimize2,
} from 'lucide-react';
import React, {
  forwardRef,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { useAppSelector } from '@/app/store/hooks';
import {
  ChatMessage,
  Content,
  AgentRun,
  TranscriptGroup,
} from '@/app/types/transcriptTypes';
import { Card } from '@/components/ui/card';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import UuidPill from '@/components/UuidPill';
import { useDebounce } from '@/hooks/use-debounce';

import MetadataDialog from './MetadataDialog';
import { cn } from '@/lib/utils';

// Export interface for use in other components
export interface AgentRunViewerHandle {
  scrollToBlock: (
    blockIdx: number,
    transcriptIdx: number,
    agentRunIdx: number
  ) => void;
}

// Add props interface
interface AgentRunViewerProps {
  secondary: boolean;
  otherAgentRunRef?: React.RefObject<AgentRunViewerHandle>;
}

// Add this helper function near the top of the file
const formatMetadataValue = (value: any): string => {
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

// Interface for hierarchical transcript group structure
interface TranscriptGroupNode {
  group: TranscriptGroup;
  transcripts: string[];
  children: TranscriptGroupNode[];
  level: number;
}

// Component for rendering a single transcript group node (recursive)
const TranscriptGroupNode: React.FC<{
  node: TranscriptGroupNode;
  selectedTranscriptKey: string | null;
  selectedTranscriptGroupId: string | null;
  expandedGroups: Set<string>;
  onTranscriptSelect: (transcriptKey: string) => void;
  onGroupToggle: (groupId: string) => void;
  agentRun: AgentRun;
}> = ({
  node,
  selectedTranscriptKey,
  selectedTranscriptGroupId,
  expandedGroups,
  onTranscriptSelect,
  onGroupToggle,
  agentRun,
}) => {
  const isExpanded = expandedGroups.has(node.group.id);
  const isSelected = selectedTranscriptGroupId === node.group.id;

  return (
    <div className="space-y-1">
      {/* Group Header */}
      <div
        className={cn(
          'flex items-center text-xs rounded border transition-colors cursor-pointer min-w-0',
          isSelected
            ? 'bg-indigo-bg border-indigo-border text-primary'
            : 'bg-secondary border-border text-primary hover:bg-muted'
        )}
        onClick={() => onGroupToggle(node.group.id)}
        style={{ marginLeft: `${node.level * 12}px` }}
      >
        <div className="flex items-center flex-1 px-2 py-1 min-w-0">
          {isExpanded ? (
            <FolderOpen className="h-3 w-3 mr-1 flex-shrink-0" />
          ) : (
            <Folder className="h-3 w-3 mr-1 flex-shrink-0" />
          )}
          <span className="text-ellipsis whitespace-nowrap overflow-hidden min-w-0">
            {node.group.name || node.group.id}
          </span>
        </div>
      </div>

      {/* Group Transcripts */}
      {isExpanded && (
        <div className="space-y-1">
          {node.transcripts.map((transcriptKey) => (
            <div
              key={transcriptKey}
              className={cn(
                'flex items-center text-xs rounded border transition-colors min-w-0',
                selectedTranscriptKey === transcriptKey
                  ? 'bg-blue-bg border-blue-border text-primary'
                  : 'bg-secondary border-border text-primary hover:bg-muted'
              )}
              style={{ marginLeft: `${(node.level + 1) * 12}px` }}
            >
              <button
                onClick={() => onTranscriptSelect(transcriptKey)}
                className="flex-1 text-left px-2 py-1 text-ellipsis whitespace-nowrap overflow-hidden min-w-0"
                title={transcriptKey}
              >
                {transcriptKey}
              </button>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex h-full items-center">
                    <MetadataDialog
                      metadata={
                        agentRun?.transcripts[transcriptKey]?.metadata || {}
                      }
                      title={`Transcript Metadata - ${transcriptKey}`}
                      trigger={
                        <button
                          className={cn(
                            'p-0.5 mr-1 rounded transition-colors',
                            selectedTranscriptKey === transcriptKey
                              ? 'hover:bg-blue-bg text-primary'
                              : 'hover:bg-accent text-muted-foreground'
                          )}
                        >
                          <FileText className="h-3 w-3" />
                        </button>
                      }
                    />
                  </div>
                </TooltipTrigger>
                <TooltipContent side="left" align="center">
                  <p>View transcript metadata</p>
                </TooltipContent>
              </Tooltip>
            </div>
          ))}
        </div>
      )}

      {/* Child Groups (recursive) */}
      {isExpanded &&
        node.children.map((childNode) => (
          <TranscriptGroupNode
            key={childNode.group.id}
            node={childNode}
            selectedTranscriptKey={selectedTranscriptKey}
            selectedTranscriptGroupId={selectedTranscriptGroupId}
            expandedGroups={expandedGroups}
            onTranscriptSelect={onTranscriptSelect}
            onGroupToggle={onGroupToggle}
            agentRun={agentRun}
          />
        ))}
    </div>
  );
};

const AgentRunViewer = forwardRef<AgentRunViewerHandle, AgentRunViewerProps>(
  ({ secondary, otherAgentRunRef }, ref) => {
    const agentRun = useAppSelector((state) =>
      secondary ? state.transcript.altAgentRun : state.transcript?.curAgentRun
    );

    // Add state for selected transcript key and transcript group
    const [selectedTranscriptKey, setSelectedTranscriptKey] = useState<
      string | null
    >(null);
    const [selectedTranscriptGroupId, setSelectedTranscriptGroupId] = useState<
      string | null
    >(null);
    const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
      new Set()
    );

    // Initialize expanded groups when transcript groups are available
    useEffect(() => {
      if (
        agentRun?.transcript_groups &&
        Object.keys(agentRun.transcript_groups).length > 0
      ) {
        // Expand all groups by default
        const allGroupIds = Object.keys(agentRun.transcript_groups);
        setExpandedGroups(new Set(allGroupIds));
      }
    }, [agentRun?.transcript_groups]);

    // Build hierarchical transcript group structure
    const { transcriptGroupTree, ungroupedTranscripts, transcriptKeys } =
      useMemo(() => {
        if (!agentRun || Object.keys(agentRun.transcripts).length === 0) {
          return {
            transcriptGroupTree: [],
            ungroupedTranscripts: [],
            transcriptKeys: [],
          };
        }

        const transcriptGroups = agentRun.transcript_groups || {};
        const allTranscriptKeys: string[] = [];
        const groupToTranscripts: Record<string, string[]> = {};
        const groupToNode: Record<string, TranscriptGroupNode> = {};

        // Debug logging
        console.log('AgentRun:', {
          id: agentRun.id,
          transcriptCount: Object.keys(agentRun.transcripts).length,
          hasTranscriptGroups: !!agentRun.transcript_groups,
          transcriptGroupsCount: agentRun.transcript_groups
            ? Object.keys(agentRun.transcript_groups).length
            : 0,
        });
        console.log('AgentRun transcripts:', Object.keys(agentRun.transcripts));
        console.log(
          'AgentRun transcript_groups:',
          Object.keys(transcriptGroups)
        );

        // First pass: collect all transcripts and their groups
        Object.entries(agentRun.transcripts).forEach(
          ([transcriptId, transcript]) => {
            allTranscriptKeys.push(transcriptId);

            console.log(`Transcript ${transcriptId}:`, {
              transcript_group_id: transcript.transcript_group_id,
              hasGroup:
                transcript.transcript_group_id &&
                transcriptGroups[transcript.transcript_group_id],
              groupExists: transcript.transcript_group_id
                ? transcriptGroups[transcript.transcript_group_id]
                : false,
            });

            if (
              transcript.transcript_group_id &&
              transcriptGroups[transcript.transcript_group_id]
            ) {
              const groupId = transcript.transcript_group_id;
              if (!groupToTranscripts[groupId]) {
                groupToTranscripts[groupId] = [];
              }
              groupToTranscripts[groupId].push(transcriptId);
              console.log(
                `Assigned transcript ${transcriptId} to group ${groupId}`
              );
            } else {
              console.log(
                `Transcript ${transcriptId} has no valid group assignment`
              );
            }
          }
        );

        console.log('Group to transcripts mapping:', groupToTranscripts);

        // Debug transcript groups structure
        console.log('Transcript groups details:');
        Object.entries(transcriptGroups).forEach(([groupId, group]) => {
          console.log(`Group ${groupId}:`, {
            name: group.name,
            parent: group.parent_transcript_group_id,
            hasTranscripts: groupToTranscripts[groupId]?.length || 0,
          });
        });

        // Second pass: build nodes for all groups
        Object.entries(transcriptGroups).forEach(([groupId, group]) => {
          groupToNode[groupId] = {
            group,
            transcripts: groupToTranscripts[groupId] || [],
            children: [],
            level: 0, // Will be calculated in the next pass
          };
        });

        // Third pass: build the tree structure and calculate levels
        const rootNodes: TranscriptGroupNode[] = [];
        const processedGroups = new Set<string>();

        const calculateLevel = (groupId: string, level: number): number => {
          if (processedGroups.has(groupId)) {
            return level;
          }

          processedGroups.add(groupId);
          const node = groupToNode[groupId];
          if (!node) return level;

          node.level = level;

          // Find children (groups that have this group as parent)
          const children = Object.values(transcriptGroups).filter(
            (g) => g.parent_transcript_group_id === groupId
          );

          node.children = children
            .map((child) => {
              const childNode = groupToNode[child.id];
              if (childNode) {
                calculateLevel(child.id, level + 1);
                return childNode;
              }
              return null;
            })
            .filter((n): n is TranscriptGroupNode => n !== null);

          return level;
        };

        // Find root groups (no parent) and build the tree
        Object.values(transcriptGroups).forEach((group) => {
          if (!group.parent_transcript_group_id) {
            const node = groupToNode[group.id];
            if (node) {
              calculateLevel(group.id, 0);
              rootNodes.push(node);
            }
          }
        });

        // Sort transcripts within each group by created_at timestamp
        const sortTranscripts = (node: TranscriptGroupNode) => {
          node.transcripts.sort((a, b) => {
            const timestampA = agentRun.transcripts[a].created_at;
            const timestampB = agentRun.transcripts[b].created_at;
            if (!timestampA && !timestampB) return 0;
            if (!timestampA) return 1;
            if (!timestampB) return -1;
            return (
              new Date(timestampA).getTime() - new Date(timestampB).getTime()
            );
          });

          // Recursively sort children
          node.children.forEach(sortTranscripts);
        };

        rootNodes.forEach(sortTranscripts);

        // Find ungrouped transcripts
        const ungroupedTranscripts = allTranscriptKeys.filter(
          (transcriptId) =>
            !agentRun.transcripts[transcriptId].transcript_group_id
        );

        // Sort ungrouped transcripts by created_at timestamp
        ungroupedTranscripts.sort((a, b) => {
          const timestampA = agentRun.transcripts[a].created_at;
          const timestampB = agentRun.transcripts[b].created_at;
          if (!timestampA && !timestampB) return 0;
          if (!timestampA) return 1;
          if (!timestampB) return -1;
          return (
            new Date(timestampA).getTime() - new Date(timestampB).getTime()
          );
        });

        console.log(
          'Final tree structure:',
          rootNodes.map((node) => ({
            id: node.group.id,
            name: node.group.name,
            level: node.level,
            transcriptCount: node.transcripts.length,
            childCount: node.children.length,
          }))
        );
        console.log('Ungrouped transcripts:', ungroupedTranscripts);

        // If no transcript groups are available, treat all transcripts as ungrouped
        if (Object.keys(transcriptGroups).length === 0) {
          console.log(
            'No transcript groups available, treating all transcripts as ungrouped'
          );
          return {
            transcriptGroupTree: [],
            ungroupedTranscripts: allTranscriptKeys,
            transcriptKeys: allTranscriptKeys,
          };
        }

        return {
          transcriptGroupTree: rootNodes,
          ungroupedTranscripts,
          transcriptKeys: allTranscriptKeys,
        };
      }, [agentRun]);

    const [transcript, transcriptIdx] = useMemo(() => {
      if (!agentRun || transcriptKeys.length === 0) {
        return [null, 0];
      }

      // If no transcript is selected, default to the first one
      const targetId =
        selectedTranscriptKey && transcriptKeys.includes(selectedTranscriptKey)
          ? selectedTranscriptKey
          : transcriptKeys[0];

      // Update selected transcript key if it was null
      if (!selectedTranscriptKey && transcriptKeys.length > 0) {
        setSelectedTranscriptKey(transcriptKeys[0]);
      }

      return [agentRun.transcripts[targetId], transcriptKeys.indexOf(targetId)];
    }, [agentRun, selectedTranscriptKey, transcriptKeys]);

    // Handler for toggling group expansion
    const handleGroupToggle = useCallback((groupId: string) => {
      setExpandedGroups((prev) => {
        const newSet = new Set(prev);
        if (newSet.has(groupId)) {
          newSet.delete(groupId);
        } else {
          newSet.add(groupId);
        }
        return newSet;
      });
    }, []);

    // Handler for expanding/collapsing all groups
    const handleToggleAllGroups = useCallback(() => {
      if (!agentRun?.transcript_groups) return;

      const allGroupIds = Object.keys(agentRun.transcript_groups);
      const allExpanded = allGroupIds.every((id) => expandedGroups.has(id));

      if (allExpanded) {
        // Collapse all groups
        setExpandedGroups(new Set());
      } else {
        // Expand all groups
        setExpandedGroups(new Set(allGroupIds));
      }
    }, [agentRun?.transcript_groups, expandedGroups]);

    // Check if all groups are expanded
    const allGroupsExpanded = useMemo(() => {
      if (!agentRun?.transcript_groups) return false;
      const allGroupIds = Object.keys(agentRun.transcript_groups);
      return (
        allGroupIds.length > 0 &&
        allGroupIds.every((id) => expandedGroups.has(id))
      );
    }, [agentRun?.transcript_groups, expandedGroups]);

    // Handler for transcript selection
    const handleTranscriptSelect = useCallback((transcriptKey: string) => {
      setSelectedTranscriptKey(transcriptKey);
    }, []);

    /**
     * Scrolling
     */
    const [scrollPosition, setScrollPosition] = useState(0);
    const debouncedScrollPosition = useDebounce(scrollPosition, 100);
    const [scrollNode, setScrollNode] = useState<HTMLDivElement | null>(null);
    const [currentBlockIndex, setCurrentBlockIndex] = useState<number | null>(
      null
    );

    const [highlightedBlock, setHighlightedBlock] = useState<string | null>(
      null
    );

    const scrollContainerRef = useCallback((node: HTMLDivElement) => {
      if (!node) return;
      // Store the node reference
      setScrollNode(node);

      // Update scroll position on scroll
      const handleScroll = () => {
        setScrollPosition(node.scrollTop);
      };
      node.addEventListener('scroll', handleScroll);
      return () => {
        node.removeEventListener('scroll', handleScroll);
      };
    }, []);

    // Compute the current block index based on scroll position
    useEffect(() => {
      // Skip if no transcript or no scroll node
      if (!transcript || !scrollNode) return;

      // Get all block elements
      const blockElements = Array.from(
        document.querySelectorAll(
          `[id*="r-${secondary ? 1 : 0}_t-${transcriptIdx}_b-"]`
        )
      );
      if (blockElements.length === 0) return;

      // Use the stored node reference directly
      const containerRect = scrollNode.getBoundingClientRect();
      const viewportTop = containerRect.top;
      const viewportHeight = containerRect.height;

      // Calculate visibility for each block
      const visibilityScores = blockElements.map((element) => {
        const rect = element.getBoundingClientRect();

        // Calculate how much of the element is visible in the viewport
        const top = Math.max(rect.top, viewportTop);
        const bottom = Math.min(rect.bottom, viewportTop + viewportHeight);
        const visibleHeight = Math.max(0, bottom - top);

        // Calculate visibility as a percentage of the element's height
        const visibilityScore = visibleHeight / rect.height;

        // Extract block index from the id
        const blockIdx = parseInt(
          element.id.replace('b-', '').split('_')[2],
          10
        );

        return { blockIndex: blockIdx, visibilityScore };
      });

      // Find the block with the highest visibility score
      const mostVisibleBlock = visibilityScores.reduce(
        (prev, current) =>
          current.visibilityScore > prev.visibilityScore ? current : prev,
        { blockIndex: -1, visibilityScore: 0 }
      );

      // Only update if we found a visible block
      if (
        mostVisibleBlock.blockIndex >= 0 &&
        mostVisibleBlock.visibilityScore > 0
      ) {
        setCurrentBlockIndex(mostVisibleBlock.blockIndex);
        console.log('Current block index:', mostVisibleBlock.blockIndex);
      }
    }, [debouncedScrollPosition, transcript, scrollNode]);

    /**
     * Scroll to block function - now with cross-scrolling support
     */
    const scrollToBlock = useCallback(
      (
        toBlockIdx: number,
        toTranscriptIdx: number = 0,
        toAgentRunIdx: number = 0
      ) => {
        // Determine which transcript should handle this scroll
        const currentAgentRunIdx = secondary ? 1 : 0;

        if (toAgentRunIdx !== currentAgentRunIdx && otherAgentRunRef?.current) {
          // Cross-scroll to the other agent run
          otherAgentRunRef.current.scrollToBlock(
            toBlockIdx,
            toTranscriptIdx,
            (toAgentRunIdx + 1) % 2
          );
          return;
        }

        // Handle scrolling within this agent run
        // First, change the selected transcript if needed
        const targetTranscriptKey = transcriptKeys[toTranscriptIdx];
        const needsTranscriptChange =
          targetTranscriptKey && targetTranscriptKey !== selectedTranscriptKey;

        if (needsTranscriptChange) {
          setSelectedTranscriptKey(targetTranscriptKey);
        }

        const tryScrolling = (attempts = 0, maxAttempts = 3) => {
          const blockId = `r-${toAgentRunIdx}_t-${toTranscriptIdx}_b-${toBlockIdx}`;
          const blockElement = document.getElementById(blockId);
          if (blockElement && scrollNode) {
            const containerRect = scrollNode.getBoundingClientRect();
            const elementRect = blockElement.getBoundingClientRect();
            const relativeTop =
              elementRect.top - containerRect.top + scrollNode.scrollTop;

            scrollNode.scrollTo({
              top: relativeTop,
              behavior: 'smooth',
            });

            // Update current block index
            setCurrentBlockIndex(toBlockIdx);

            // Add highlighting effect
            setHighlightedBlock(blockId);

            // Remove highlight after animation duration
            setTimeout(() => {
              setHighlightedBlock(null);
            }, 0);

            return true;
          }

          // If element not found and we haven't exceeded max attempts
          if (attempts < maxAttempts) {
            // Try again after a short delay
            setTimeout(() => tryScrolling(attempts + 1, maxAttempts), 50);
            return false;
          }

          console.warn(
            `Failed to scroll to block ${toBlockIdx} after ${maxAttempts} attempts`
          );
          return false;
        };

        // If we changed the transcript, wait a bit for the UI to update before scrolling
        if (needsTranscriptChange) {
          setTimeout(() => tryScrolling(), 100);
        } else {
          tryScrolling();
        }
      },
      [
        scrollNode,
        secondary,
        otherAgentRunRef,
        transcriptKeys,
        selectedTranscriptKey,
      ]
    );

    React.useImperativeHandle(
      ref,
      () => ({
        scrollToBlock,
      }),
      [scrollToBlock]
    );

    /**
     * Block navigation
     */

    const goToNextBlock = useCallback(() => {
      if (!transcript) return;

      const nextIndex =
        currentBlockIndex !== null
          ? Math.min(currentBlockIndex + 1, transcript.messages.length - 1)
          : 0;

      scrollToBlock(nextIndex, secondary ? 1 : 0);
    }, [currentBlockIndex, transcript, scrollToBlock]);
    const goToPrevBlock = useCallback(() => {
      if (!transcript) return;

      const prevIndex =
        currentBlockIndex !== null ? Math.max(currentBlockIndex - 1, 0) : 0;

      scrollToBlock(prevIndex, secondary ? 1 : 0);
    }, [currentBlockIndex, transcript, scrollToBlock]);

    return (
      <Card className="h-full flex-1 p-3 min-h-0 min-w-0 flex flex-col space-y-3">
        {/* Header area Content */}
        {agentRun && (
          <>
            <div className="flex flex-col gap-1">
              <div className="flex items-center space-x-1">
                <div className="font-semibold text-sm">Agent Run</div>
                <UuidPill uuid={agentRun?.id} />
                {agentRun && (
                  <MetadataDialog
                    metadata={agentRun.metadata}
                    title="Agent Run Metadata"
                  />
                )}
              </div>
              <div className="text-xs text-muted-foreground flex items-center overflow-hidden truncate">
                {Object.entries(agentRun.metadata).map(([key, value]) => (
                  <span key={key} className="mr-3">
                    <span className="font-medium text-muted-foreground">
                      {key}:
                    </span>{' '}
                    {formatMetadataValue(value)}
                  </span>
                ))}
                ...
              </div>
            </div>
            <div className="flex flex-1 min-h-0 w-full space-x-2 overflow-hidden relative">
              {/* Transcript Groups and Transcripts Sidebar */}
              {transcriptKeys.length >= 1 && (
                <>
                  <div className="w-48 flex-shrink-0 flex flex-col">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-xs font-medium text-primary">
                        Transcripts
                      </div>
                      {/* Expand/Collapse All Button - only show if there are transcript groups */}
                      {transcriptGroupTree.length > 0 && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              onClick={handleToggleAllGroups}
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
                    <div className="space-y-1 flex-1 overflow-y-auto min-h-0">
                      {/* Hierarchical Transcript Groups */}
                      {transcriptGroupTree.map((node) => (
                        <TranscriptGroupNode
                          key={node.group.id}
                          node={node}
                          selectedTranscriptKey={selectedTranscriptKey}
                          selectedTranscriptGroupId={selectedTranscriptGroupId}
                          expandedGroups={expandedGroups}
                          onTranscriptSelect={handleTranscriptSelect}
                          onGroupToggle={handleGroupToggle}
                          agentRun={agentRun}
                        />
                      ))}

                      {/* Root Level Transcripts (ungrouped) */}
                      {ungroupedTranscripts.map((transcriptKey) => (
                        <div
                          key={transcriptKey}
                          className={cn(
                            'flex items-center w-full text-xs rounded border transition-colors',
                            selectedTranscriptKey === transcriptKey
                              ? 'bg-blue-bg border-blue-border text-primary'
                              : 'bg-secondary border-border text-primary hover:bg-muted'
                          )}
                        >
                          <button
                            onClick={() =>
                              handleTranscriptSelect(transcriptKey)
                            }
                            className="flex-1 text-left px-2 py-1 text-ellipsis whitespace-nowrap overflow-hidden"
                            title={transcriptKey}
                          >
                            {transcriptKey}
                          </button>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <div className="flex h-full items-center">
                                <MetadataDialog
                                  metadata={
                                    agentRun?.transcripts[transcriptKey]
                                      ?.metadata || {}
                                  }
                                  title={`Transcript Metadata - ${transcriptKey}`}
                                  trigger={
                                    <button
                                      className={cn(
                                        'p-0.5 mr-1 rounded transition-colors',
                                        selectedTranscriptKey === transcriptKey
                                          ? 'hover:bg-blue-bg text-primary'
                                          : 'hover:bg-accent text-muted-foreground'
                                      )}
                                    >
                                      <FileText className="h-3 w-3" />
                                    </button>
                                  }
                                />
                              </div>
                            </TooltipTrigger>
                            <TooltipContent side="left" align="center">
                              <p>View transcript metadata</p>
                            </TooltipContent>
                          </Tooltip>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="border-r border-border " />
                </>
              )}

              {transcript && (
                <>
                  {/* Transcript content */}
                  <div
                    className="space-y-2 overflow-y-auto custom-scrollbar flex-1"
                    ref={scrollContainerRef}
                  >
                    {transcript.messages.map((message, index) => {
                      const blockId = `r-${secondary ? 1 : 0}_t-${transcriptIdx}_b-${index}`;
                      return (
                        <MessageBox
                          key={index}
                          message={message}
                          index={index}
                          id={blockId}
                          agentRun={agentRun}
                          scrollToBlock={scrollToBlock}
                          transcriptIdx={transcriptIdx}
                          isHighlighted={highlightedBlock === blockId}
                        />
                      );
                    })}
                  </div>

                  {/* Navigation buttons inside the ScrollArea (relative to parent container) */}
                  <div className="absolute bottom-3 right-6 flex flex-col gap-1">
                    <div className="bg-muted border border-border rounded-md shadow-sm flex flex-col">
                      <button
                        onClick={goToPrevBlock}
                        className="p-1.5 hover:bg-accent transition-colors rounded-t-md"
                        title="Previous block"
                      >
                        <ChevronUp className="h-4 w-4 text-muted-foreground" />
                      </button>
                      <div className="h-px bg-accent" />
                      <button
                        onClick={goToNextBlock}
                        className="p-1.5 hover:bg-accent transition-colors rounded-b-md"
                        title="Next block"
                      >
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </>
        )}
        {!agentRun && (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}
      </Card>
    );
  }
);

// Add display name for forwardRef
AgentRunViewer.displayName = 'AgentRunViewer';

export default AgentRunViewer;

const roleColorMap: Record<string, string> = {
  assistant: 'blue',
  user: 'gray',
  system: 'orange',
  tool: 'green',
};

const MessageBox: React.FC<{
  message: ChatMessage;
  index: number;
  id?: string;
  agentRun: AgentRun;
  scrollToBlock: (blockIndex: number, transcriptIdx?: number) => void;
  transcriptIdx: number;
  isHighlighted: boolean;
}> = ({
  message,
  index,
  id,
  agentRun,
  scrollToBlock,
  transcriptIdx,
  isHighlighted,
}) => {
  const agentRunId = agentRun.id;

  const getRoleStyle = (role: string, isHighlighted: boolean) => {
    const color = roleColorMap[role] || 'gray';

    if (role === 'user') {
      if (isHighlighted) {
        return `bg-secondary/50 border-l-4 border-primary`;
      }
      return `bg-secondary border-l-4 border-primary`;
    }

    if (isHighlighted) {
      return `bg-${color}-bg/50 border-l-4 border-${color}-border`;
    }
    return `bg-${color}-bg border-l-4 border-${color}-border`;
  };

  const getMessageContent = (content: string | Content[]): string => {
    if (typeof content === 'string') {
      return content;
    }
    // If content is an array of Content objects
    return content
      .filter(
        (item): item is Content & { text: string } =>
          item.type === 'text' && typeof item.text === 'string'
      )
      .map((item) => item.text)
      .join('\n');
  };

  // Add a new function to extract reasoning content
  const getReasoningContent = (content: string | Content[]): string | null => {
    if (typeof content === 'string') {
      return null;
    }
    // Find the first reasoning content item
    const reasoningItem = content.find(
      (item): item is Content & { reasoning: string } =>
        item.type === 'reasoning' && typeof item.reasoning === 'string'
    );
    return reasoningItem ? reasoningItem.reasoning : null;
  };

  // Helper to render tool-specific information
  const renderToolInfo = () => {
    if (message.role === 'tool') {
      return (
        <div className="mt-1 text-[10px] text-muted-foreground">
          {message.tool_call_id && (
            <span>Tool Call ID: {message.tool_call_id}</span>
          )}
          {message.function && (
            <span className="ml-2">Function: {message.function}</span>
          )}
          {message.error && (
            <div className="mt-1 text-destructive">
              Error: {message.error.message}
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  // Helper to render tool calls for assistant messages
  const renderToolCalls = () => {
    if (message.role === 'assistant' && message.tool_calls) {
      return message.tool_calls.map((tool, i) => (
        <div
          key={i}
          className="mt-1 p-1.5 bg-secondary/85 rounded text-xs break-all whitespace-pre-wrap"
        >
          <div className="text-[10px] text-muted-foreground mb-0.5">
            Tool Call ID: {tool.id}
          </div>
          {tool.view ? (
            <span className="font-mono">{tool.view.content}</span>
          ) : (
            <div className="font-mono">
              <span className="font-semibold">{tool.function}</span>
              <span className="text-muted-foreground">
                (
                {Object.entries(tool.arguments || {})
                  .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                  .join(', ')}
                )
              </span>
            </div>
          )}
        </div>
      ));
    }
    return null;
  };

  return (
    <div className="mb-1">
      <div
        id={id}
        className={cn(
          'p-2 rounded-md text-sm',
          !isHighlighted && 'transition-all duration-1500',
          getRoleStyle(message.role, isHighlighted)
        )}
      >
        <div className="text-[10px] text-muted-foreground flex justify-between mb-1">
          <span>
            Block {index} |{' '}
            {message.role.charAt(0).toUpperCase() + message.role.slice(1)}
          </span>
        </div>

        {typeof message.content !== 'string' && (
          <>
            {message.role === 'assistant' &&
              getReasoningContent(message.content) && (
                <div className="mb-2 px-2 py-2 bg-muted border-l-2 border-border text-xs text-primary italic whitespace-pre-wrap [overflow-wrap:anywhere] max-w-full overflow-x-auto font-mono rounded">
                  {getReasoningContent(message.content)}
                </div>
              )}
          </>
        )}
        <div className="whitespace-pre-wrap [overflow-wrap:anywhere] max-w-full text-xs overflow-x-auto font-mono">
          {getMessageContent(message.content)}
        </div>
        {renderToolInfo()}
        {renderToolCalls()}
      </div>
    </div>
  );
};
