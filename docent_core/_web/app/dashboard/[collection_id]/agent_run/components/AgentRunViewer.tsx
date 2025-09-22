import {
  ChevronDown,
  ChevronUp,
  Loader2,
  FolderTree,
  ChevronRight,
  PanelRightClose,
  PanelRightOpen,
  AlertCircle,
} from 'lucide-react';
import React, {
  forwardRef,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  clearHighlightedCitation,
  selectRunCitationsById,
  toggleRightSidebar,
} from '@/app/store/transcriptSlice';
import {
  AgentRun,
  Content,
  Transcript,
  TranscriptGroup,
} from '@/app/types/transcriptTypes';
import { TranscriptNavigator, TreeNode } from './TranscriptNavigator';
import UuidPill from '@/components/UuidPill';
import { useDebounce } from '@/hooks/use-debounce';

import { MetadataPopover } from '@/components/metadata/MetadataPopover';
import { MetadataBlock } from '@/components/metadata/MetadataBlock';
import { cn } from '@/lib/utils';
import { Citation } from '@/app/types/experimentViewerTypes';
import { generateCitationId } from '@/lib/citationUtils';
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable';
import { MessageBox, hasJsonContent } from './MessageBox';
import { Button } from '@/components/ui/button';
import { useGetAgentRunWithCanonicalTreeQuery } from '@/app/api/collectionApi';
import { skipToken } from '@reduxjs/toolkit/query';

// Export interface for use in other components
interface ScrollToBlockParams {
  blockIdx: number;
  transcriptIdx: number;
  agentRunIdx: number;
  highlightDuration?: number;
  citation?: Citation;
}
export interface AgentRunViewerHandle {
  scrollToBlock: (params: ScrollToBlockParams) => void;
  focusCitation: (citation: Citation) => void;
}

// Add props interface
interface AgentRunViewerProps {
  agentRunId: string;
}

// Controlled metadata intent (run/transcript/message) for opening dialogs
type MetadataIntent =
  | { type: 'run'; citedKey?: string; citedTextRange?: string }
  | {
      type: 'transcript';
      transcriptIdx: number;
      citedKey?: string;
      citedTextRange?: string;
    }
  | {
      type: 'message';
      transcriptIdx: number;
      blockIdx: number;
      citedKey?: string;
      citedTextRange?: string;
    };

// Add this helper function near the top of the file
const formatMetadataValue = (value: any): string => {
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

// No client-side sorting: rely on backend canonical tree order

// Unified node tree: groups and transcripts share a single node type

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
  transcriptId: string,
  transcriptsById: Record<string, Transcript>,
  transcriptGroupsById: Record<string, TranscriptGroup>
): Array<{ id: string; name: string; type: 'group' | 'transcript' }> => {
  const path: Array<{
    id: string;
    name: string;
    type: 'group' | 'transcript';
  }> = [];

  if (!transcriptId) {
    return path;
  }

  const transcript = transcriptsById[transcriptId];

  // Add the transcript itself at the end (use transcriptKey like in sidebar)
  path.unshift({
    id: transcriptId,
    name: transcriptId,
    type: 'transcript',
  });

  // Build the path from the transcript's group up to the root
  let currentGroupId = transcript?.transcript_group_id || null;
  while (currentGroupId && transcriptGroupsById[currentGroupId]) {
    const group = transcriptGroupsById[currentGroupId];

    // Check if there are multiple groups with the same name in the same parent
    let displayName = group.name || currentGroupId;
    if (group.parent_transcript_group_id) {
      const siblings = Object.values(transcriptGroupsById).filter(
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
  ({ agentRunId }, ref) => {
    const dispatch = useAppDispatch();

    const collectionId = useAppSelector(
      (state) => state.collection?.collectionId
    );

    // Full tree toggle (default off)
    const [fullTree, setFullTree] = useState(false);

    // Fetch canonical tree (respect fullTree)
    const queryResult = useGetAgentRunWithCanonicalTreeQuery(
      collectionId ? { collectionId, agentRunId, fullTree } : skipToken
    );
    const { error, isError } = queryResult;
    const dataArray = Array.isArray(queryResult.data)
      ? (queryResult.data as [any, any])
      : undefined;
    const agentRun: AgentRun = dataArray?.[0];
    const canonicalTree = dataArray?.[1];

    const isNotFound = useMemo(() => {
      const e = error as any;
      return e && typeof e === 'object' && 'status' in e && e.status === 404;
    }, [error]);
    const transcriptsById = useMemo(() => {
      const m: Record<string, Transcript> = {};
      if (agentRun?.transcripts)
        for (const t of agentRun.transcripts) m[t.id] = t;
      return m;
    }, [agentRun]);
    const transcriptGroupsById = useMemo(() => {
      const m: Record<string, TranscriptGroup> = {};
      if (agentRun?.transcript_groups)
        for (const tg of agentRun.transcript_groups) m[tg.id] = tg;
      return m;
    }, [agentRun]);
    const transcriptIdxToId = useMemo(() => {
      return canonicalTree?.transcript_ids_ordered || [];
    }, [canonicalTree]);

    const transcriptIdToIdx = useMemo(() => {
      const map: Record<string, number> = {};
      const ordered = canonicalTree?.transcript_ids_ordered || [];
      ordered.forEach((id: string, idx: number) => {
        map[id] = idx;
      });
      return map;
    }, [canonicalTree]);

    const runCitations = useAppSelector((state) =>
      selectRunCitationsById(state, agentRun?.id)
    );

    // Add state for selected transcript id and transcript group
    const [selectedTranscriptId, setSelectedTranscriptId] = useState<
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
    const rightSidebarOpen = useAppSelector(
      (state) => state.transcript?.rightSidebarOpen
    );
    const [sidebarHovering, setSidebarHovering] = useState(false);

    // Helper for sidebar-aware styling
    const getSidebarStyles = (baseClasses: string, sidebarClasses?: string) =>
      cn(baseClasses, sidebarVisible && sidebarClasses);

    // Initialize expanded groups when transcript groups are available
    useEffect(() => {
      if (
        agentRun?.transcript_groups &&
        agentRun.transcript_groups.length > 0
      ) {
        const allGroupIds = agentRun.transcript_groups.map((g) => g.id);
        setExpandedGroups(new Set(allGroupIds));
      }
    }, [agentRun?.transcript_groups]);

    // Build unified node tree from backend canonical tree
    const { nodes: nodeTree } = useMemo(() => {
      // Fallback if missing data
      if (!agentRun || !agentRun.transcripts || !canonicalTree) {
        return {
          nodes: [] as TreeNode[],
        };
      }

      const transcripts = transcriptsById;
      const transcriptGroups = transcriptGroupsById;
      const tree = (canonicalTree?.tree || {}) as Record<string, any[]>;

      // Helper to parse a canonical child which might be encoded as
      // [type, id] or as a string like 't:<id>' / 'tg:<id>'
      const parseChild = (
        child: any
      ): { type: 't' | 'tg'; id: string } | null => {
        if (!child) return null;
        if (Array.isArray(child) && child.length === 2) {
          const [t, id] = child as ['t' | 'tg', string];
          if ((t === 't' || t === 'tg') && typeof id === 'string') {
            return { type: t, id };
          }
          return null;
        }
        if (typeof child === 'string') {
          if (child.startsWith('t:')) return { type: 't', id: child.slice(2) };
          if (child.startsWith('tg:'))
            return { type: 'tg', id: child.slice(3) };
        }
        return null;
      };

      const buildGroupNode = (groupId: string, level: number): TreeNode => {
        const childrenNodes: TreeNode[] = [];
        const children = tree[groupId] || [];
        for (const ch of children) {
          const parsed = parseChild(ch);
          if (!parsed) continue;
          if (parsed.type === 't') {
            if (transcripts[parsed.id])
              childrenNodes.push({
                type: 'transcript',
                id: parsed.id,
                level: level + 1,
              });
          } else if (parsed.type === 'tg') {
            if (transcriptGroups[parsed.id]) {
              childrenNodes.push(buildGroupNode(parsed.id, level + 1));
            }
          }
        }
        return { type: 'group', id: groupId, level, children: childrenNodes };
      };

      // Roots
      const rootChildren = tree['__global_root'] || [];
      const rootNodes: TreeNode[] = [];
      const collectFromGroup = (groupId: string) => {
        for (const ch of tree[groupId] || []) {
          const parsed = parseChild(ch);
          if (!parsed) continue;
          if (parsed.type === 't') {
            // ordering is defined by backend via transcript_idx_map
          } else if (parsed.type === 'tg') {
            if (transcriptGroups[parsed.id]) collectFromGroup(parsed.id);
          }
        }
      };

      for (const ch of rootChildren) {
        const parsed = parseChild(ch);
        if (!parsed) continue;
        if (parsed.type === 'tg') {
          if (transcriptGroups[parsed.id]) {
            rootNodes.push(buildGroupNode(parsed.id, 0));
            collectFromGroup(parsed.id);
          }
        } else if (parsed.type === 't') {
          if (transcripts[parsed.id]) {
            rootNodes.push({ type: 'transcript', id: parsed.id, level: 0 });
          }
        }
      }

      return {
        nodes: rootNodes,
      };
    }, [agentRun, canonicalTree, transcriptsById, transcriptGroupsById]);

    // Upon initial load, if no transcript has been selected, select the first one
    const initTranscriptSelected = useRef(false);
    useEffect(() => {
      if (
        !initTranscriptSelected.current &&
        selectedTranscriptId === null &&
        transcriptIdxToId.length > 0
      ) {
        initTranscriptSelected.current = true;
        setSelectedTranscriptId(transcriptIdxToId[0] ?? null);
      }
    }, [selectedTranscriptId, transcriptIdxToId]);

    // Resolve selected transcript and its index
    const transcript = selectedTranscriptId
      ? transcriptsById[selectedTranscriptId]
      : undefined;
    const transcriptIdx = selectedTranscriptId
      ? transcriptIdToIdx[selectedTranscriptId]
      : undefined;

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

      const allGroupIds = agentRun.transcript_groups.map((g) => g.id);
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
      const allGroupIds = agentRun.transcript_groups.map((g) => g.id);
      return (
        allGroupIds.length > 0 &&
        allGroupIds.every((id) => expandedGroups.has(id))
      );
    }, [agentRun?.transcript_groups, expandedGroups]);

    // Handler for transcript selection
    const handleTranscriptSelect = useCallback(
      (transcriptId: string) => {
        setSelectedTranscriptId(transcriptId);
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
      selectedTranscriptId
        ? transcriptScrollPositions[selectedTranscriptId] || 0
        : 0,
      100
    );

    // Pending scroll target to resolve when DOM/content is ready
    const [pendingScrollTarget, setPendingScrollTarget] =
      useState<ScrollToBlockParams | null>(null);

    const scrollContainerRef = useCallback((node: HTMLDivElement | null) => {
      // Always reflect the latest node (including null on unmount)
      setScrollNode(node);
    }, []);

    // Attach/detach scroll listener when the scroll node changes
    useEffect(() => {
      if (!scrollNode) return;
      const handleScroll = () => {
        if (selectedTranscriptId) {
          setTranscriptScrollPositions((prev) => ({
            ...prev,
            [selectedTranscriptId]: scrollNode.scrollTop,
          }));
        }
      };
      scrollNode.addEventListener('scroll', handleScroll);
      return () => {
        scrollNode.removeEventListener('scroll', handleScroll);
      };
    }, [scrollNode, selectedTranscriptId]);

    // Restore scroll position when transcript changes
    useEffect(() => {
      if (scrollNode && selectedTranscriptId) {
        const savedPosition =
          transcriptScrollPositions[selectedTranscriptId] || 0;
        scrollNode.scrollTop = savedPosition;
      }
    }, [selectedTranscriptId, scrollNode]);

    // Compute the current block index based on scroll position
    useEffect(() => {
      // Skip if no transcript or no scroll node
      if (!transcript || transcriptIdx === undefined || !scrollNode) return;

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

    // Fulfill pending scroll with simple retries instead of MutationObserver
    useEffect(() => {
      if (!pendingScrollTarget || !scrollNode) return;

      const {
        blockIdx,
        transcriptIdx,
        agentRunIdx,
        highlightDuration,
        citation,
      } = pendingScrollTarget;
      let blockId = `r-${agentRunIdx}_t-${transcriptIdx}_b-${blockIdx}`;

      const tryScrollNow = (): boolean => {
        // First, change the selected transcript if needed
        const targetTranscriptId = transcriptIdxToId[transcriptIdx];
        if (!targetTranscriptId) return false;
        if (targetTranscriptId !== selectedTranscriptId) {
          console.log('scroll: changing transcript to', targetTranscriptId);
          setSelectedTranscriptId(targetTranscriptId);
        }

        let blockElement = document.getElementById(blockId);
        if (!blockElement) {
          // It's possible this is an invalid blockIdx; check if 0 exists
          const testBlockId = `r-${agentRunIdx}_t-${transcriptIdx}_b-0`;
          const testBlockElement = document.getElementById(testBlockId);
          if (testBlockElement) {
            console.error(
              'scroll: found invalid citation. did not find',
              blockId,
              'but found',
              testBlockId,
              'to scroll to'
            );
            blockElement = testBlockElement;
            blockId = testBlockId;
          } else {
            console.log(
              `scroll: no block element found for transcript ${transcriptIdx}`
            );
            return false;
          }
        }

        const containerRect = scrollNode.getBoundingClientRect();
        let top: number | null = null;

        if (citation) {
          const citationId = generateCitationId(citation);
          const targetSpan = (blockElement as HTMLElement).querySelector(
            `span[data-citation-ids*="${citationId}"]`
          ) as HTMLElement | null;
          if (targetSpan) {
            const spanRect = targetSpan.getBoundingClientRect();
            top =
              spanRect.top -
              containerRect.top +
              scrollNode.scrollTop -
              Math.max(0, (containerRect.height - spanRect.height) / 2);
          }
        }

        if (top == null) {
          const rect = blockElement.getBoundingClientRect();
          top = rect.top - containerRect.top + scrollNode.scrollTop;
        }

        scrollNode.scrollTo({ top, behavior: 'auto' });
        setCurrentBlockIndex(blockIdx);
        setHighlightedBlock(blockId);
        setTimeout(() => setHighlightedBlock(null), highlightDuration);
        setPendingScrollTarget(null);
        return true;
      };

      // Try immediately; else retry a few times with delay
      if (tryScrollNow()) return;

      let attempts = 0;
      const maxAttempts = 6; // ~1.2s total at 200ms
      const delayMs = 200;
      const intervalId = window.setInterval(() => {
        attempts += 1;
        if (tryScrollNow()) {
          window.clearInterval(intervalId);
        } else if (attempts >= maxAttempts) {
          window.clearInterval(intervalId);
          setPendingScrollTarget(null);
        }
      }, delayMs);

      return () => {
        window.clearInterval(intervalId);
      };
    }, [pendingScrollTarget, scrollNode]);

    // Scroll to block function
    const scrollToBlock = setPendingScrollTarget;

    const [metadataIntent, setMetadataIntent] = useState<MetadataIntent | null>(
      null
    );

    const focusCitation = useCallback(
      (citation: Citation) => {
        const citedKey = citation.metadata_key;
        const citedTextRange = citation.start_pattern;

        // Run-level metadata
        if (citation.transcript_idx == undefined && citedKey != undefined) {
          setMetadataIntent({ type: 'run', citedKey, citedTextRange });
          return;
        }

        const tIdx = citation.transcript_idx ?? 0;

        // Transcript-level metadata
        if (citation.block_idx == undefined && citedKey != undefined) {
          const targetTranscriptId = transcriptIdxToId[tIdx];
          if (
            targetTranscriptId &&
            targetTranscriptId !== selectedTranscriptId
          ) {
            setSelectedTranscriptId(targetTranscriptId);
          }
          setMetadataIntent({
            type: 'transcript',
            transcriptIdx: tIdx,
            citedKey,
            citedTextRange,
          });
          return;
        }

        // Message-level citation (possibly metadata)
        const blockIdx = citation.block_idx ?? 0;
        scrollToBlock({
          blockIdx,
          transcriptIdx: tIdx,
          agentRunIdx: 0,
          highlightDuration: 500,
          citation,
        });
        if (citedKey != undefined) {
          setMetadataIntent({
            type: 'message',
            transcriptIdx: tIdx,
            blockIdx,
            citedKey,
            citedTextRange,
          });
        }
      },
      [scrollToBlock, transcriptIdxToId, selectedTranscriptId]
    );

    /**
     * Block navigation
     */

    React.useImperativeHandle(
      ref,
      () => ({
        scrollToBlock,
        focusCitation,
      }),
      [scrollToBlock, focusCitation]
    );

    const goToNextBlock = useCallback(() => {
      if (!transcript || transcriptIdx === undefined) return;

      const nextIndex =
        currentBlockIndex !== null
          ? Math.min(currentBlockIndex + 1, transcript.messages.length - 1)
          : 0;

      scrollToBlock({ blockIdx: nextIndex, transcriptIdx, agentRunIdx: 0 });
    }, [currentBlockIndex, transcript, scrollToBlock, transcriptIdx]);
    const goToPrevBlock = useCallback(() => {
      if (!transcript || transcriptIdx === undefined) return;

      const prevIndex =
        currentBlockIndex !== null ? Math.max(currentBlockIndex - 1, 0) : 0;

      scrollToBlock({ blockIdx: prevIndex, transcriptIdx, agentRunIdx: 0 });
    }, [currentBlockIndex, transcript, scrollToBlock, transcriptIdx]);

    return (
      <>
        {/* Header area Content */}
        {agentRun && (
          <>
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between space-x-1">
                <div className="flex items-center space-x-1">
                  <div className="font-semibold text-sm shrink-0">
                    Agent Run
                  </div>
                  <UuidPill uuid={agentRun?.id} />
                  {agentRun && (
                    <MetadataPopover.Root
                      open={metadataIntent?.type === 'run'}
                      onOpenChange={(open) =>
                        setMetadataIntent(open ? { type: 'run' } : null)
                      }
                    >
                      <MetadataPopover.DefaultTrigger />
                      <MetadataPopover.Content title="Agent Run Metadata">
                        <MetadataPopover.Body metadata={agentRun.metadata}>
                          {(md) => (
                            <MetadataBlock
                              metadata={md}
                              citedKey={
                                metadataIntent?.type === 'run'
                                  ? metadataIntent.citedKey
                                  : undefined
                              }
                              citedTextRange={
                                metadataIntent?.type === 'run'
                                  ? metadataIntent.citedTextRange
                                  : undefined
                              }
                            />
                          )}
                        </MetadataPopover.Body>
                      </MetadataPopover.Content>
                    </MetadataPopover.Root>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 cursor-default"
                  onClick={() => dispatch(toggleRightSidebar())}
                >
                  {rightSidebarOpen ? (
                    <PanelRightClose className="h-4 w-4" />
                  ) : (
                    <PanelRightOpen className="h-4 w-4" />
                  )}
                </Button>
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
              {canonicalTree?.transcript_ids_ordered &&
                canonicalTree.transcript_ids_ordered.length >= 2 &&
                !sidebarVisible &&
                sidebarHovering && (
                  <div
                    className="absolute -top-3 -left-3 w-1/4 min-w-[250px] max-w-[400px] bg-background border border-border rounded-lg shadow-lg z-10 flex flex-col max-h-[80vh] overflow-y-auto custom-scrollbar"
                    onMouseEnter={() => setSidebarHovering(true)}
                    onMouseLeave={() => setSidebarHovering(false)}
                  >
                    <TranscriptNavigator
                      nodes={nodeTree}
                      selectedTranscriptId={selectedTranscriptId}
                      selectedTranscriptGroupId={selectedTranscriptGroupId}
                      expandedGroups={expandedGroups}
                      agentRun={agentRun}
                      transcriptsById={transcriptsById}
                      transcriptGroupsById={transcriptGroupsById}
                      onTranscriptSelect={handleTranscriptSelect}
                      onGroupToggle={handleGroupToggle}
                      className="overflow-y-auto px-3 pb-3 flex-shrink-0"
                      showHeader
                      headerLeft={
                        <div className="p-1 w-6 h-6 flex-shrink-0"></div>
                      }
                      headerClassName="p-3 pb-1"
                      fullTree={fullTree}
                      onFullTreeChange={(v) => setFullTree(!!v)}
                      onToggleAllGroups={handleToggleAllGroups}
                      allGroupsExpanded={allGroupsExpanded}
                    />
                  </div>
                )}
              {/* Transcript Groups and Transcripts Sidebar */}
              {canonicalTree?.transcript_ids_ordered &&
                canonicalTree.transcript_ids_ordered.length >= 2 && (
                  <>
                    <ResizablePanel
                      defaultSize={sidebarVisible ? 25 : 0}
                      minSize={sidebarVisible ? 20 : 0}
                      maxSize={sidebarVisible ? 50 : 0}
                      className={
                        sidebarVisible ? 'flex flex-col min-h-0' : 'hidden'
                      }
                    >
                      <TranscriptNavigator
                        nodes={nodeTree}
                        selectedTranscriptId={selectedTranscriptId}
                        selectedTranscriptGroupId={selectedTranscriptGroupId}
                        expandedGroups={expandedGroups}
                        agentRun={agentRun}
                        transcriptsById={transcriptsById}
                        transcriptGroupsById={transcriptGroupsById}
                        onTranscriptSelect={handleTranscriptSelect}
                        onGroupToggle={handleGroupToggle}
                        className="flex-1 overflow-y-auto min-h-0 pr-1"
                        showHeader
                        headerLeft={
                          <button
                            onClick={() => setSidebarVisible(false)}
                            className="p-1 rounded text-muted-foreground hover:text-primary hover:bg-muted transition-colors"
                            aria-label="Hide transcript hierarchy"
                          >
                            <FolderTree className="h-4 w-4" />
                          </button>
                        }
                        fullTree={fullTree}
                        onFullTreeChange={(v) => setFullTree(!!v)}
                        onToggleAllGroups={handleToggleAllGroups}
                        allGroupsExpanded={allGroupsExpanded}
                      />
                    </ResizablePanel>
                    <ResizableHandle
                      withHandle={false}
                      className={cn('mx-2', sidebarVisible ? '' : 'hidden')}
                    />
                  </>
                )}

              {transcript && (
                <ResizablePanel
                  defaultSize={75}
                  className="flex flex-col min-h-0"
                >
                  {/* Transcript content */}
                  <div className={getSidebarStyles('space-y-1 mb-2 pr-1')}>
                    <div className="flex items-center justify-between">
                      {selectedTranscriptId && (
                        <div className="flex items-center space-x-1">
                          {/* Only show toggle button if there are multiple transcripts and sidebar is hidden */}
                          {canonicalTree?.transcript_ids_ordered &&
                            canonicalTree.transcript_ids_ordered.length >= 2 &&
                            !sidebarVisible && (
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
                          <UuidPill uuid={selectedTranscriptId} />
                          {(() => {
                            const isTranscriptIntent =
                              metadataIntent?.type === 'transcript' &&
                              metadataIntent.transcriptIdx === transcriptIdx;
                            const citedKey = isTranscriptIntent
                              ? metadataIntent?.citedKey
                              : undefined;
                            const citedTextRange = isTranscriptIntent
                              ? metadataIntent?.citedTextRange
                              : undefined;
                            return (
                              <MetadataPopover.Root
                                open={Boolean(isTranscriptIntent)}
                                onOpenChange={(open) =>
                                  setMetadataIntent(
                                    open
                                      ? {
                                          type: 'transcript',
                                          transcriptIdx: transcriptIdx ?? 0,
                                        }
                                      : null
                                  )
                                }
                              >
                                <MetadataPopover.DefaultTrigger />
                                <MetadataPopover.Content
                                  title={`Transcript Metadata`}
                                >
                                  <MetadataPopover.Body
                                    metadata={
                                      (selectedTranscriptId
                                        ? transcriptsById[selectedTranscriptId]
                                        : undefined
                                      )?.metadata || {}
                                    }
                                  >
                                    {(md) => (
                                      <MetadataBlock
                                        metadata={md}
                                        citedKey={citedKey}
                                        citedTextRange={citedTextRange}
                                      />
                                    )}
                                  </MetadataPopover.Body>
                                </MetadataPopover.Content>
                              </MetadataPopover.Root>
                            );
                          })()}
                        </div>
                      )}
                    </div>
                    {selectedTranscriptId &&
                      (selectedTranscriptId
                        ? transcriptsById[selectedTranscriptId]
                        : undefined
                      )?.transcript_group_id && (
                        <TranscriptPath
                          className={getSidebarStyles('')}
                          path={buildTranscriptPath(
                            selectedTranscriptId,
                            transcriptsById,
                            transcriptGroupsById
                          )}
                        />
                      )}
                  </div>
                  <div
                    className="space-y-2 overflow-y-auto custom-scrollbar flex-1 min-h-0"
                    ref={scrollContainerRef}
                  >
                    {transcript.messages.map((message, index) => {
                      const blockId = `r-0_t-${transcriptIdx}_b-${index}`;
                      const isMsgIntent =
                        metadataIntent?.type === 'message' &&
                        metadataIntent.transcriptIdx === (transcriptIdx ?? 0) &&
                        metadataIntent.blockIdx === index;
                      const msgCitedKey = isMsgIntent
                        ? metadataIntent?.citedKey
                        : undefined;
                      const msgCitedRange = isMsgIntent
                        ? metadataIntent?.citedTextRange
                        : undefined;
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
                          metadataDialogControl={{
                            open: Boolean(isMsgIntent),
                            onOpenChange: (open) =>
                              setMetadataIntent(
                                open
                                  ? {
                                      type: 'message',
                                      transcriptIdx: transcriptIdx ?? 0,
                                      blockIdx: index,
                                    }
                                  : null
                              ),
                            citedKey: msgCitedKey,
                            citedTextRange: msgCitedRange,
                          }}
                          transcriptIdx={transcriptIdx}
                        />
                      );
                    })}
                  </div>

                  {/* Navigation buttons inside the ScrollArea (relative to parent container) */}
                  <div className="absolute bottom-3 right-3 flex flex-col gap-1">
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
        {isError && (
          <div className="flex items-center justify-center h-full">
            <div className="p-3 space-y-2 text-center">
              <div className="flex items-center justify-center gap-2 text-red-text">
                <AlertCircle className="h-4 w-4" />
                <span className="text-sm font-medium">
                  {isNotFound
                    ? 'Agent run not found'
                    : 'Failed to load agent run'}
                </span>
              </div>
              <div className="text-xs text-muted-foreground">
                {isNotFound
                  ? 'The requested agent run does not exist or you do not have access.'
                  : 'Please try again.'}
              </div>
            </div>
          </div>
        )}
        {!agentRun && !isError && (
          <div className="flex items-center justify-center h-full">
            <Loader2 size={16} className="animate-spin text-muted-foreground" />
          </div>
        )}
      </>
    );
  }
);

// Add display name for forwardRef
AgentRunViewer.displayName = 'AgentRunViewer';

export default AgentRunViewer;
