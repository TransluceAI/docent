import {
  ChevronDown,
  ChevronUp,
  Loader2,
  FolderTree,
  ChevronRight,
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

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  clearHighlightedCitation,
  selectRunCitationsById,
} from '@/app/store/transcriptSlice';
import {
  Content,
  AgentRun,
  TranscriptGroup,
} from '@/app/types/transcriptTypes';
import { TranscriptNavigator } from './TranscriptNavigator';
import { Card } from '@/components/ui/card';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import UuidPill from '@/components/UuidPill';
import { useDebounce } from '@/hooks/use-debounce';

import { MetadataDialog } from './MetadataDialog';
import { cn } from '@/lib/utils';
import { Citation } from '@/app/types/experimentViewerTypes';
import { generateCitationId } from '@/lib/citationUtils';
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable';
import { MessageBox, hasJsonContent } from './MessageBox';

// Export interface for use in other components
export interface AgentRunViewerHandle {
  scrollToBlock: (
    blockIdx: number,
    transcriptIdx: number,
    agentRunIdx: number,
    highlightDuration?: number,
    citation?: Citation
  ) => void;
}

// Add props interface
interface AgentRunViewerProps {
  agentRun?: AgentRun;
  initialTranscriptIdx?: number;
}

// Add this helper function near the top of the file
const formatMetadataValue = (value: any): string => {
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

// Helper function to sort transcripts by created_at timestamp
const sortTranscriptsByTimestamp = (
  transcriptIds: string[],
  transcripts: Record<string, any>
): string[] => {
  return [...transcriptIds].sort((a, b) => {
    const timestampA = transcripts[a].created_at;
    const timestampB = transcripts[b].created_at;
    if (!timestampA && !timestampB) return 0;
    if (!timestampA) return 1;
    if (!timestampB) return -1;
    return new Date(timestampA).getTime() - new Date(timestampB).getTime();
  });
};

// Interface for hierarchical transcript group structure
interface TranscriptGroupNode {
  group: TranscriptGroup;
  transcripts: string[];
  children: TranscriptGroupNode[];
  level: number;
}

// Helper function to get message content as string
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

// Helper function to build transcript path
const buildTranscriptPath = (
  transcriptKey: string,
  agentRun: AgentRun
): Array<{ id: string; name: string; type: 'group' | 'transcript' }> => {
  const path: Array<{
    id: string;
    name: string;
    type: 'group' | 'transcript';
  }> = [];

  if (!agentRun || !agentRun.transcripts[transcriptKey]) {
    return path;
  }

  const transcript = agentRun.transcripts[transcriptKey];
  const transcriptGroups = agentRun.transcript_groups || {};

  // Add the transcript itself at the end (use transcriptKey like in sidebar)
  path.unshift({
    id: transcriptKey,
    name: transcriptKey,
    type: 'transcript',
  });

  // Build the path from the transcript's group up to the root
  let currentGroupId = transcript.transcript_group_id;
  while (currentGroupId && transcriptGroups[currentGroupId]) {
    const group = transcriptGroups[currentGroupId];

    // Check if there are multiple groups with the same name in the same parent
    let displayName = group.name || currentGroupId;
    if (group.parent_transcript_group_id) {
      const siblings = Object.values(transcriptGroups).filter(
        (g) =>
          g.parent_transcript_group_id === group.parent_transcript_group_id &&
          g.name === group.name
      );

      if (siblings.length > 1) {
        // Sort siblings by created_at timestamp to match sidebar order
        const sortedSiblings = siblings.sort((a, b) => {
          const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
          const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
          return aTime - bTime;
        });

        const index = sortedSiblings.findIndex((g) => g.id === group.id);
        if (index >= 0) {
          displayName = `${displayName} - ${index + 1}`;
        }
      }
    }

    path.unshift({
      id: currentGroupId,
      name: displayName,
      type: 'group',
    });
    currentGroupId = group.parent_transcript_group_id || null;
  }

  return path;
};

// Component for displaying transcript path
const TranscriptPath: React.FC<{
  path: Array<{ id: string; name: string; type: 'group' | 'transcript' }>;
  className?: string;
}> = ({ path, className }) => {
  if (path.length === 0) return null;

  return (
    <div
      className={cn(
        'flex items-center text-xs text-muted-foreground/70 mb-1 pr-1 overflow-hidden',
        className
      )}
    >
      <div className="flex items-center space-x-0.5 min-w-0 flex-1 overflow-x-auto custom-scrollbar">
        {path.map((item, index) => (
          <React.Fragment key={item.id}>
            {index > 0 && (
              <ChevronRight className="h-2.5 w-2.5 text-muted-foreground/40 flex-shrink-0" />
            )}
            <span
              className={cn(
                'px-1 py-0.5 rounded text-xs whitespace-nowrap flex-shrink-0',
                item.type === 'group'
                  ? 'bg-muted/30 text-muted-foreground/80'
                  : 'bg-muted/40 text-muted-foreground'
              )}
            >
              {item.name}
            </span>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

const AgentRunViewer = forwardRef<AgentRunViewerHandle, AgentRunViewerProps>(
  ({ agentRun, initialTranscriptIdx }, ref) => {
    const dispatch = useAppDispatch();
    agentRun = useAppSelector(
      (state) => agentRun || state.transcript?.curAgentRun
    );

    const runCitations = useAppSelector((state) =>
      selectRunCitationsById(state, agentRun?.id)
    );

    // Add state for selected transcript key and transcript group
    const [selectedTranscriptKey, setSelectedTranscriptKey] = useState<
      string | null
    >(null);
    const [selectedTranscriptGroupId] = useState<string | null>(null);
    const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
      new Set()
    );
    const [prettyPrintJsonMessages, setPrettyPrintJsonMessages] = useState<
      Set<number>
    >(new Set());

    // State for sidebar toggle and hover functionality
    const [sidebarVisible, setSidebarVisible] = useState(true);
    const [sidebarHovering, setSidebarHovering] = useState(false);

    // Helper for sidebar-aware styling
    const getSidebarStyles = (baseClasses: string, sidebarClasses?: string) =>
      cn(baseClasses, sidebarVisible && sidebarClasses);

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

        // First pass: collect all transcripts and their groups
        Object.entries(agentRun.transcripts).forEach(
          ([transcriptId, transcript]) => {
            allTranscriptKeys.push(transcriptId);

            if (
              transcript.transcript_group_id &&
              transcriptGroups[transcript.transcript_group_id]
            ) {
              const groupId = transcript.transcript_group_id;
              if (!groupToTranscripts[groupId]) {
                groupToTranscripts[groupId] = [];
              }
              groupToTranscripts[groupId].push(transcriptId);
            }
          }
        );

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
          node.transcripts = sortTranscriptsByTimestamp(
            node.transcripts,
            agentRun.transcripts
          );

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
        const sortedUngroupedTranscripts = sortTranscriptsByTimestamp(
          ungroupedTranscripts,
          agentRun.transcripts
        );

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
          ungroupedTranscripts: sortedUngroupedTranscripts,
          transcriptKeys: allTranscriptKeys,
        };
      }, [agentRun]);

    const [transcript, transcriptIdx] = useMemo(() => {
      if (!agentRun || transcriptKeys.length === 0) {
        return [null, 0];
      }

      // Determine target transcript ID based on selection, initial index, or default
      let targetId: string;

      if (
        selectedTranscriptKey &&
        transcriptKeys.includes(selectedTranscriptKey)
      ) {
        // Use currently selected transcript
        targetId = selectedTranscriptKey;
      } else if (
        initialTranscriptIdx !== undefined &&
        transcriptKeys[initialTranscriptIdx]
      ) {
        // Use initial transcript index if provided and valid
        targetId = transcriptKeys[initialTranscriptIdx];
      } else {
        // Default to first transcript
        targetId = transcriptKeys[0];
      }

      // Update selected transcript key if it was null or if we're using initial index
      if (
        !selectedTranscriptKey ||
        (initialTranscriptIdx !== undefined &&
          transcriptKeys[initialTranscriptIdx])
      ) {
        setSelectedTranscriptKey(targetId);
      }

      return [agentRun.transcripts[targetId], transcriptKeys.indexOf(targetId)];
    }, [agentRun, selectedTranscriptKey, transcriptKeys, initialTranscriptIdx]);

    // Initialize pretty print for messages with JSON content when transcript changes
    useEffect(() => {
      if (transcript && transcript.messages.length > 0) {
        const jsonMessageIndices = new Set<number>();

        transcript.messages.forEach((message, index) => {
          const content = getMessageContent(message.content);
          if (hasJsonContent(content)) {
            jsonMessageIndices.add(index);
          }
        });

        setPrettyPrintJsonMessages(jsonMessageIndices);
      }
    }, [transcript]);

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
    const handleTranscriptSelect = useCallback(
      (transcriptKey: string) => {
        setSelectedTranscriptKey(transcriptKey);
        // Clear any highlighted citations when switching transcripts
        dispatch(clearHighlightedCitation());
        // Close floating sidebar when transcript is selected
        if (!sidebarVisible) {
          setSidebarHovering(false);
        }
      },
      [dispatch, sidebarVisible]
    );

    /**
     * Scrolling
     */
    // Scroll container node for calculating relative positions
    const [scrollNode, setScrollNode] = useState<HTMLDivElement | null>(null);
    // Viewport state: index of the block most visible to the user (drives prev/next)
    const [currentBlockIndex, setCurrentBlockIndex] = useState<number | null>(
      null
    );

    // Transient UI state: id of the block being flash-highlighted after a jump
    const [highlightedBlock, setHighlightedBlock] = useState<string | null>(
      null
    );

    // Store scroll positions per transcript
    const [transcriptScrollPositions, setTranscriptScrollPositions] = useState<
      Record<string, number>
    >({});

    // Debounced scroll position for the current transcript
    const debouncedScrollPosition = useDebounce(
      selectedTranscriptKey
        ? transcriptScrollPositions[selectedTranscriptKey] || 0
        : 0,
      100
    );

    const scrollContainerRef = useCallback(
      (node: HTMLDivElement) => {
        if (!node) return;
        // Store the node reference
        setScrollNode(node);

        // Update scroll position on scroll
        const handleScroll = () => {
          // Save scroll position for current transcript
          if (selectedTranscriptKey) {
            setTranscriptScrollPositions((prev) => ({
              ...prev,
              [selectedTranscriptKey]: node.scrollTop,
            }));
          }
        };
        node.addEventListener('scroll', handleScroll);
        return () => {
          node.removeEventListener('scroll', handleScroll);
        };
      },
      [selectedTranscriptKey]
    );

    // Restore scroll position when transcript changes
    useEffect(() => {
      if (scrollNode && selectedTranscriptKey) {
        const savedPosition =
          transcriptScrollPositions[selectedTranscriptKey] || 0;
        scrollNode.scrollTop = savedPosition;
      }
    }, [selectedTranscriptKey]);

    // Compute the current block index based on scroll position
    useEffect(() => {
      // Skip if no transcript or no scroll node
      if (!transcript || !scrollNode) return;

      // Get all block elements
      const blockElements = Array.from(
        document.querySelectorAll(`[id*="r-0_t-${transcriptIdx}_b-"]`)
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
      }
    }, [debouncedScrollPosition, transcript, scrollNode]);

    /**
     * Scroll to block function - now with cross-scrolling support
     */
    const scrollToBlock = useCallback(
      (
        toBlockIdx: number,
        toTranscriptIdx: number = 0,
        toAgentRunIdx: number = 0,
        highlightDuration: number = 0,
        citation?: Citation
      ) => {
        // Handle scrolling within this agent run
        // First, change the selected transcript if needed
        const targetTranscriptKey = transcriptKeys[toTranscriptIdx];
        const needsTranscriptChange =
          targetTranscriptKey && targetTranscriptKey !== selectedTranscriptKey;

        if (needsTranscriptChange) {
          setSelectedTranscriptKey(targetTranscriptKey);
        }

        const tryScrolling = (attempts = 0, maxAttempts = 6) => {
          const blockId = `r-${toAgentRunIdx}_t-${toTranscriptIdx}_b-${toBlockIdx}`;
          const blockElement = document.getElementById(blockId);
          if (blockElement && scrollNode) {
            const containerRect = scrollNode.getBoundingClientRect();

            // If a specific citation is provided, try to center its span
            if (citation) {
              const citationId = generateCitationId(citation);
              const targetSpan = document.querySelector(
                `span[data-citation-ids*="${citationId}"]`
              ) as HTMLElement | null;
              if (targetSpan) {
                const spanRect = targetSpan.getBoundingClientRect();
                const desiredTop =
                  spanRect.top -
                  containerRect.top +
                  scrollNode.scrollTop -
                  Math.max(0, (containerRect.height - spanRect.height) / 2);
                scrollNode.scrollTo({ top: desiredTop, behavior: 'auto' });

                setCurrentBlockIndex(toBlockIdx);
                setHighlightedBlock(blockId);
                setTimeout(() => {
                  setHighlightedBlock(null);
                }, highlightDuration);
                return true;
              }
              // Citation not found yet; fall through to retry logic below
            }

            // Fallback: align the block to the top
            const elementRect = blockElement.getBoundingClientRect();
            const relativeTop =
              elementRect.top - containerRect.top + scrollNode.scrollTop;
            scrollNode.scrollTo({ top: relativeTop, behavior: 'auto' });

            setCurrentBlockIndex(toBlockIdx);
            setHighlightedBlock(blockId);
            setTimeout(() => {
              setHighlightedBlock(null);
            }, highlightDuration);
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
      [scrollNode, transcriptKeys, selectedTranscriptKey]
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

      scrollToBlock(nextIndex, transcriptIdx, 0);
    }, [currentBlockIndex, transcript, scrollToBlock, transcriptIdx]);
    const goToPrevBlock = useCallback(() => {
      if (!transcript) return;

      const prevIndex =
        currentBlockIndex !== null ? Math.max(currentBlockIndex - 1, 0) : 0;

      scrollToBlock(prevIndex, transcriptIdx, 0);
    }, [currentBlockIndex, transcript, scrollToBlock, transcriptIdx]);

    return (
      <Card
        className="h-full basis-1/2 p-3 min-h-0 min-w-0 flex flex-col space-y-2"
        style={{ flexGrow: '2' }}
      >
        {/* Header area Content */}
        {agentRun && (
          <>
            <div className="flex flex-col gap-1">
              <div className="flex items-center space-x-1">
                <div className="font-semibold text-sm shrink-0">Agent Run</div>
                <UuidPill uuid={agentRun?.id} />
                {agentRun && (
                  <MetadataDialog
                    metadata={agentRun.metadata}
                    title="Agent Run Metadata"
                    id={agentRun.id}
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
            <ResizablePanelGroup
              direction="horizontal"
              className="flex flex-1 min-h-0 w-full relative"
              style={{ overflow: 'visible' }} // need style attr to override style attr
            >
              {/* Floating Sidebar - shows when sidebar is hidden and hovering */}
              {transcriptKeys.length >= 2 &&
                !sidebarVisible &&
                sidebarHovering && (
                  <div
                    className="absolute -top-3 -left-3 w-1/4 min-w-[250px] max-w-[400px] bg-background border border-border rounded-lg shadow-lg z-10 flex flex-col max-h-[80vh] overflow-y-auto custom-scrollbar"
                    onMouseEnter={() => setSidebarHovering(true)}
                    onMouseLeave={() => setSidebarHovering(false)}
                  >
                    {/* Header */}
                    <div className="flex items-center justify-between mb-2 p-3 pb-1">
                      <div className="flex items-center space-x-1">
                        <div className="p-1 w-6 h-6 flex-shrink-0"></div>
                        <div className="text-xs font-medium text-primary">
                          Transcripts
                        </div>
                      </div>
                      {/* Expand/Collapse All Button */}
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
                    {/* Navigation */}
                    <TranscriptNavigator
                      transcriptGroupTree={transcriptGroupTree}
                      ungroupedTranscripts={ungroupedTranscripts}
                      selectedTranscriptKey={selectedTranscriptKey}
                      selectedTranscriptGroupId={selectedTranscriptGroupId}
                      expandedGroups={expandedGroups}
                      agentRun={agentRun}
                      onTranscriptSelect={handleTranscriptSelect}
                      onGroupToggle={handleGroupToggle}
                      className="overflow-y-auto px-3 pb-3 flex-shrink-0"
                    />
                  </div>
                )}
              {/* Transcript Groups and Transcripts Sidebar */}
              {transcriptKeys.length >= 2 && (
                <>
                  <ResizablePanel
                    defaultSize={sidebarVisible ? 25 : 0}
                    minSize={sidebarVisible ? 20 : 0}
                    maxSize={sidebarVisible ? 50 : 0}
                    className={sidebarVisible ? 'flex flex-col' : 'hidden'}
                  >
                    {/* Header */}
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center space-x-1">
                        <button
                          onClick={() => setSidebarVisible(false)}
                          className="p-1 rounded text-muted-foreground hover:text-primary hover:bg-muted transition-colors"
                          aria-label="Hide transcript hierarchy"
                        >
                          <FolderTree className="h-4 w-4" />
                        </button>
                        <div className="text-xs font-medium text-primary">
                          Transcripts
                        </div>
                      </div>
                      {/* Expand/Collapse All Button */}
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
                    {/* Navigation */}
                    <TranscriptNavigator
                      transcriptGroupTree={transcriptGroupTree}
                      ungroupedTranscripts={ungroupedTranscripts}
                      selectedTranscriptKey={selectedTranscriptKey}
                      selectedTranscriptGroupId={selectedTranscriptGroupId}
                      expandedGroups={expandedGroups}
                      agentRun={agentRun}
                      onTranscriptSelect={handleTranscriptSelect}
                      onGroupToggle={handleGroupToggle}
                      className="flex-1 overflow-y-auto min-h-0 pr-1"
                    />
                  </ResizablePanel>
                  <ResizableHandle
                    withHandle={false}
                    className={cn('mx-2', sidebarVisible ? '' : 'hidden')}
                  />
                </>
              )}

              {transcript && (
                <ResizablePanel defaultSize={75} className="flex flex-col">
                  {/* Transcript content */}
                  <div className={getSidebarStyles('space-y-1 mb-2 pr-1')}>
                    <div className="flex items-center justify-between">
                      {selectedTranscriptKey && (
                        <div className="flex items-center space-x-1">
                          {/* Only show toggle button if there are multiple transcripts and sidebar is hidden */}
                          {transcriptKeys.length >= 2 && !sidebarVisible && (
                            <div
                              onMouseEnter={() => setSidebarHovering(true)}
                              onMouseLeave={() => setSidebarHovering(false)}
                              className="relative z-20"
                            >
                              <button
                                onClick={() =>
                                  setSidebarVisible(!sidebarVisible)
                                }
                                className="p-1 rounded text-muted-foreground hover:text-primary hover:bg-muted transition-colors"
                                aria-label="Show transcript hierarchy"
                              >
                                <FolderTree className="h-4 w-4" />
                              </button>
                            </div>
                          )}
                          <div className="font-semibold text-sm">
                            Transcript
                          </div>
                          <UuidPill uuid={selectedTranscriptKey} />
                          <MetadataDialog
                            metadata={
                              agentRun?.transcripts[selectedTranscriptKey]
                                ?.metadata || {}
                            }
                            title={`Transcript Metadata - ${selectedTranscriptKey}`}
                            id={selectedTranscriptKey}
                          />
                        </div>
                      )}
                    </div>
                    {selectedTranscriptKey &&
                      agentRun?.transcripts[selectedTranscriptKey]
                        ?.transcript_group_id && (
                        <TranscriptPath
                          className={getSidebarStyles('')}
                          path={buildTranscriptPath(
                            selectedTranscriptKey,
                            agentRun
                          )}
                        />
                      )}
                  </div>
                  <div
                    className="space-y-2 overflow-y-auto custom-scrollbar flex-1"
                    ref={scrollContainerRef}
                  >
                    {transcript.messages.map((message, index) => {
                      const blockId = `r-0_t-${transcriptIdx}_b-${index}`;
                      return (
                        <MessageBox
                          key={index}
                          message={message}
                          index={index}
                          blockId={blockId}
                          isHighlighted={highlightedBlock === blockId}
                          citedRanges={runCitations.filter(
                            (c) =>
                              c.transcript_idx === transcriptIdx &&
                              c.block_idx === index
                          )}
                          prettyPrintJsonMessages={prettyPrintJsonMessages}
                          setPrettyPrintJsonMessages={
                            setPrettyPrintJsonMessages
                          }
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
                </ResizablePanel>
              )}
            </ResizablePanelGroup>
          </>
        )}
        {!agentRun && (
          <div className="flex items-center justify-center h-full">
            <Loader2 size={16} className="animate-spin text-muted-foreground" />
          </div>
        )}
      </Card>
    );
  }
);

// Add display name for forwardRef
AgentRunViewer.displayName = 'AgentRunViewer';

export default AgentRunViewer;
