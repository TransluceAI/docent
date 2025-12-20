import {
  ChevronDown,
  ChevronUp,
  Loader2,
  FolderTree,
  ChevronRight,
  AlertCircle,
  MessageSquarePlus,
} from 'lucide-react';
import {
  forwardRef,
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useImperativeHandle,
} from 'react';
import { TranscriptBlockContentItem } from '@/app/types/citationTypes';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  selectRunCitationsById,
  addCitationToDraft,
  setSelectedCommentId,
  setCommentSidebarCollapsed,
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
import { useCitationNavigation } from '@/providers/CitationNavigationProvider';

import { MetadataPopover } from '@/components/metadata/MetadataPopover';
import { MetadataBlock } from '@/components/metadata/MetadataBlock';
import { cn } from '@/lib/utils';
import {
  CitationTarget,
  CitationTargetTextRange,
} from '@/app/types/citationTypes';
import { citationTargetToId } from '@/lib/citationId';
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable';
import { MessageBox, hasJsonContent } from './MessageBox';
import { useGetAgentRunWithTreeQuery } from '@/app/api/collectionApi';
import { skipToken } from '@reduxjs/toolkit/query';
import { useSearchParams } from 'next/navigation';
import { Comment, useGetCommentsForAgentRunQuery } from '@/app/api/labelApi';
import {
  CommentSidebarHeader,
  CommentTab,
} from '@/app/components/annotations/CommentSidebarHeader';
import { CommentSidebarContent } from '@/app/components/annotations/CommentSidebarContent';
import { useTextSelection } from '@/providers/use-text-selection';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

// Export interface for use in other components
interface ScrollToBlockParams {
  blockIdx: number;
  transcriptId: string;
  highlightDuration?: number;
  citationTargetId?: string; // Encoded citation target ID for highlighting
}
export interface AgentRunViewerHandle {
  scrollToBlock: (params: ScrollToBlockParams) => void;
  focusCitationTarget: (target: CitationTarget) => void;
}

// Add props interface
interface AgentRunViewerProps {
  agentRunId: string;
  collectionId?: string;
  allConversationCitations?: CitationTarget[];
  headerLeftActions?: React.ReactNode;
  headerRightActions?: React.ReactNode;
}

// Controlled metadata intent (run/transcript/message) for opening dialogs
type MetadataIntent =
  | { type: 'run'; citedKey?: string; textRange?: CitationTargetTextRange }
  | {
      type: 'transcript';
      transcriptId: string;
      citedKey?: string;
      textRange?: CitationTargetTextRange;
    }
  | {
      type: 'message';
      transcriptId: string;
      blockIdx: number;
      citedKey?: string;
      textRange?: CitationTargetTextRange;
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

// Helper to filter citations for a specific block and add selectedCitation if it matches
const getCitationsForBlock = (
  allCitations: CitationTarget[],
  selectedCitation: CitationTarget | null,
  blockIdx: number,
  transcriptId: string
): CitationTarget[] => {
  // Filter to citations for this block
  const blockCitations = allCitations.filter(
    (citation) =>
      citation.item.item_type === 'block_content' &&
      citation.item.transcript_id === transcriptId &&
      citation.item.block_idx === blockIdx
  );

  // Add selectedCitation if it matches this block
  const matchesThisBlock =
    selectedCitation &&
    selectedCitation.item.item_type === 'block_content' &&
    selectedCitation.item.transcript_id === transcriptId &&
    selectedCitation.item.block_idx === blockIdx;

  return matchesThisBlock
    ? [...blockCitations, selectedCitation]
    : blockCitations;
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
          <Fragment key={item.id}>
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
          </Fragment>
        ))}
      </div>
    </div>
  );
};

const AgentRunViewer = forwardRef<AgentRunViewerHandle, AgentRunViewerProps>(
  (
    {
      agentRunId,
      collectionId: collectionIdProp,
      allConversationCitations,
      headerLeftActions,
      headerRightActions,
    },
    ref
  ) => {
    const dispatch = useAppDispatch();

    const collectionIdFromRedux = useAppSelector(
      (state) => state.collection?.collectionId
    );

    // Use prop if provided, otherwise fall back to Redux
    const collectionId = collectionIdProp ?? collectionIdFromRedux;

    const searchParams = useSearchParams();
    const initialCommentId = searchParams.get('comment_id');

    const hasWritePermission = useHasCollectionWritePermission();

    // Full tree toggle (default off)
    const [fullTree, setFullTree] = useState(false);

    // Fetch agent run with tree (respect fullTree)
    const queryResult = useGetAgentRunWithTreeQuery(
      collectionId ? { collectionId, agentRunId, fullTree } : skipToken
    );
    const { error, isError } = queryResult;
    const dataArray = Array.isArray(queryResult.data)
      ? (queryResult.data as [any, any])
      : undefined;
    const agentRun: AgentRun = dataArray?.[0];
    const agentRunTree = dataArray?.[1];

    const isNotFound = useMemo(() => {
      const e = error as any;
      return e && typeof e === 'object' && 'status' in e && e.status === 404;
    }, [error]);

    //**********************
    // Comment State & API *
    //**********************

    // Fetch comments for this agent run
    const { data: comments = [] } = useGetCommentsForAgentRunQuery(
      collectionId && agentRunId ? { collectionId, agentRunId } : skipToken
    );

    // State for the draft comment
    const draftComment = useAppSelector(
      (state) => state.transcript.draftComment
    );

    // The currently selected / clicked comment
    const selectedCommentId = useAppSelector(
      (state) => state.transcript.selectedCommentId
    );

    // Comment sidebar state
    const commentSidebarCollapsed = useAppSelector(
      (state) => state.transcript.commentSidebarCollapsed
    );

    // Whether to display comments inline or in a scrollable list
    const [activeCommentTab, setActiveCommentTab] =
      useState<CommentTab>('inline');

    // Whether to show comments for all transcripts in the sidebar
    const [showAllTranscripts, setShowAllTranscripts] = useState(false);

    // Ref for boundary container (scrollNode)
    const boundaryRef = useRef<HTMLDivElement | null>(null);

    //*********************************
    // Transcript Data Transformation *
    //*********************************

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
    // transcript_id_to_idx maps transcript IDs to their index in the canonical order
    const transcriptIdToIdx = useMemo(() => {
      return agentRunTree?.transcript_id_to_idx || {};
    }, [agentRunTree]);

    // Derive the ordered list of transcript IDs from transcript_id_to_idx
    const transcriptIdxToId = useMemo(() => {
      const entries = Object.entries(transcriptIdToIdx) as [string, number][];
      const sorted = entries.sort((a, b) => a[1] - b[1]);
      return sorted.map(([id]) => id);
    }, [transcriptIdToIdx]);

    const transcriptCount = transcriptIdxToId.length;
    const hasTranscriptGroups = Boolean(agentRun?.transcript_groups?.length);
    const shouldShowTranscriptNavigator =
      transcriptCount >= 2 || hasTranscriptGroups;

    const runCitations = useAppSelector((state) =>
      selectRunCitationsById(state, agentRun?.id)
    );

    // Agent run and judge result pages store citations in Redux, but the new /chat route passes citations as a prop.
    const allCitations = allConversationCitations
      ? allConversationCitations
      : runCitations.map((c) => c.target);

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

    // Build unified node tree from backend tree
    const { nodes: nodeTree } = useMemo(() => {
      // Fallback if missing data
      if (!agentRun || !agentRun.transcripts || !agentRunTree) {
        return {
          nodes: [] as TreeNode[],
        };
      }

      const transcripts = transcriptsById;
      const transcriptGroups = transcriptGroupsById;
      const tree = (agentRunTree?.nodes || {}) as Record<
        string,
        {
          id: string;
          node_type: 'ar' | 't' | 'tg';
          children_ids: string[];
          has_transcript_in_subtree: boolean;
        }
      >;

      const buildGroupNode = (groupId: string, level: number): TreeNode => {
        const childrenNodes: TreeNode[] = [];
        const node = tree[groupId];
        if (!node) return { type: 'group', id: groupId, level, children: [] };

        for (const childId of node.children_ids) {
          const childNode = tree[childId];
          if (!childNode) continue;

          if (childNode.node_type === 't') {
            if (transcripts[childId]) {
              childrenNodes.push({
                type: 'transcript',
                id: childId,
                level: level + 1,
              });
            }
          } else if (childNode.node_type === 'tg') {
            if (transcriptGroups[childId]) {
              childrenNodes.push(buildGroupNode(childId, level + 1));
            }
          }
        }
        return { type: 'group', id: groupId, level, children: childrenNodes };
      };

      // Get root node
      const rootNode = tree['__global_root'];
      if (!rootNode) {
        return { nodes: [] as TreeNode[] };
      }

      const rootNodes: TreeNode[] = [];
      for (const childId of rootNode.children_ids) {
        const childNode = tree[childId];
        if (!childNode) continue;

        if (childNode.node_type === 'tg') {
          if (transcriptGroups[childId]) {
            rootNodes.push(buildGroupNode(childId, 0));
          }
        } else if (childNode.node_type === 't') {
          if (transcripts[childId]) {
            rootNodes.push({ type: 'transcript', id: childId, level: 0 });
          }
        }
      }

      return {
        nodes: rootNodes,
      };
    }, [agentRun, agentRunTree, transcriptsById, transcriptGroupsById]);

    // Upon initial load, if no transcript has been selected, select the first one
    const initTranscriptSelected = useRef(false);

    // Reset transcript selection when agent run changes
    useEffect(() => {
      initTranscriptSelected.current = false;
      setSelectedTranscriptId(null);
    }, [agentRunId]);

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

    const telemetryMessageIds = useMemo(() => {
      if (!selectedTranscriptId) return new Set<string>();
      const ids =
        agentRunTree?.otel_message_ids_by_transcript_id?.[selectedTranscriptId];
      if (!Array.isArray(ids)) return new Set<string>();
      const out = new Set<string>();
      for (const id of ids) {
        if (typeof id === 'string' && id.length > 0) out.add(id);
      }
      return out;
    }, [agentRunTree, selectedTranscriptId]);

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
        setPendingScrollTarget(null);
        // Close floating sidebar when transcript is selected
        if (!sidebarVisible) {
          setSidebarHovering(false);
        }
      },
      [sidebarVisible]
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
      boundaryRef.current = node;
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
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedTranscriptId, scrollNode]);

    // Compute the current block index based on scroll position
    useEffect(() => {
      // Skip if no transcript or no scroll node
      if (!transcript || transcriptIdx === undefined || !scrollNode) return;

      // Get all block elements
      const blockElements = Array.from(
        document.querySelectorAll(`[id*="t-${transcriptIdx}_b-"]`)
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

        // Extract block index from the id (format: t-{transcriptIdx}_b-{blockIdx})
        const blockIdx = parseInt(element.id.split('_b-')[1], 10);

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
    }, [debouncedScrollPosition, transcript, scrollNode, transcriptIdx]);

    // Fulfill pending scroll with simple retries instead of MutationObserver
    useEffect(() => {
      if (!pendingScrollTarget) return;

      const { blockIdx, transcriptId, highlightDuration, citationTargetId } =
        pendingScrollTarget;

      // Switch transcript first if needed - this triggers re-render and scrollNode to be set
      if (transcriptId !== selectedTranscriptId) {
        console.log('scroll: changing transcript to', transcriptId);
        setSelectedTranscriptId(transcriptId);
        return; // Effect will re-run after transcript renders
      }

      // Now check if scrollNode exists - transcript should be rendered at this point
      if (!scrollNode) return;

      const tryScrollNow = (): boolean => {
        // Convert transcriptId to transcriptIdx for DOM lookup
        const transcriptIdx = transcriptIdToIdx[transcriptId];
        if (transcriptIdx === undefined) {
          console.error('scroll: transcript not found', transcriptId);
          return false;
        }

        let blockId = `t-${transcriptIdx}_b-${blockIdx}`;

        let blockElement = document.getElementById(blockId);
        if (!blockElement) {
          // It's possible this is an invalid blockIdx; check if 0 exists
          const testBlockId = `t-${transcriptIdx}_b-0`;
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

        // Use citationTargetId for highlighting specific text within the block
        if (citationTargetId) {
          const targetSpan = (blockElement as HTMLElement).querySelector(
            `span[data-citation-ids*="${citationTargetId}"]`
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

        scrollNode.scrollTo({ top, behavior: 'instant' });
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
    }, [
      pendingScrollTarget,
      scrollNode,
      selectedTranscriptId,
      transcriptIdToIdx,
    ]);

    // Scroll to block function
    const scrollToBlock = setPendingScrollTarget;

    const [metadataIntent, setMetadataIntent] = useState<MetadataIntent | null>(
      null
    );

    const citationNav = useCitationNavigation();
    const selectedCitation = citationNav?.selectedCitation ?? null;

    const focusCitationTarget = useCallback(
      (target: CitationTarget) => {
        const { item, text_range } = target;
        const textRange: CitationTargetTextRange | undefined =
          text_range ?? undefined;

        // Handle based on item type
        switch (item.item_type) {
          case 'agent_run_metadata':
            // Run-level metadata
            setMetadataIntent({
              type: 'run',
              citedKey: item.metadata_key,
              textRange,
            });
            setActiveCommentTab('list');
            break;

          case 'transcript_metadata':
            // Transcript-level metadata
            if (item.transcript_id !== selectedTranscriptId) {
              setSelectedTranscriptId(item.transcript_id);
            }
            setMetadataIntent({
              type: 'transcript',
              transcriptId: item.transcript_id,
              citedKey: item.metadata_key,
              textRange,
            });
            setActiveCommentTab('list');
            break;

          case 'block_metadata':
            // Block-level metadata
            scrollToBlock({
              blockIdx: item.block_idx,
              transcriptId: item.transcript_id,
              highlightDuration: 500,
            });
            setMetadataIntent({
              type: 'message',
              transcriptId: item.transcript_id,
              blockIdx: item.block_idx,
              citedKey: item.metadata_key,
              textRange,
            });
            setActiveCommentTab('list');
            break;

          case 'block_content':
            // Block content citation
            scrollToBlock({
              blockIdx: item.block_idx,
              transcriptId: item.transcript_id,
              highlightDuration: 500,
              citationTargetId: text_range
                ? citationTargetToId(target)
                : undefined,
            });
            setMetadataIntent(null);
            break;
        }
      },
      [scrollToBlock, selectedTranscriptId]
    );

    /**
     * Block navigation
     */

    useImperativeHandle(
      ref,
      () => ({
        scrollToBlock,
        focusCitationTarget,
      }),
      [scrollToBlock, focusCitationTarget]
    );

    const goToNextBlock = useCallback(() => {
      if (!transcript || !selectedTranscriptId) return;

      const nextIndex =
        currentBlockIndex !== null
          ? Math.min(currentBlockIndex + 1, transcript.messages.length - 1)
          : 0;

      scrollToBlock({
        blockIdx: nextIndex,
        transcriptId: selectedTranscriptId,
      });
    }, [currentBlockIndex, transcript, scrollToBlock, selectedTranscriptId]);
    const goToPrevBlock = useCallback(() => {
      if (!transcript || !selectedTranscriptId) return;

      const prevIndex =
        currentBlockIndex !== null ? Math.max(currentBlockIndex - 1, 0) : 0;

      scrollToBlock({
        blockIdx: prevIndex,
        transcriptId: selectedTranscriptId,
      });
    }, [currentBlockIndex, transcript, scrollToBlock, selectedTranscriptId]);

    //********************
    // Comment Handlers *
    //********************

    // Focus the comment in the query parameter on load
    const hasFocusedComment = useRef(false);
    useEffect(() => {
      if (
        initialCommentId &&
        comments.length > 0 &&
        !hasFocusedComment.current
      ) {
        // Select the comment and open the sidebar
        dispatch(setSelectedCommentId(initialCommentId));
        dispatch(setCommentSidebarCollapsed(false));

        // Find the comment object
        const initialFocusedComment = comments.find(
          (c) => c.id === initialCommentId
        );

        // Scroll to the comment citation within the transcript
        if (
          initialFocusedComment &&
          initialFocusedComment.citations.length > 0
        ) {
          focusCitationTarget(initialFocusedComment.citations[0].target);
        }

        hasFocusedComment.current = true;
      }
    }, [initialCommentId, dispatch, comments, focusCitationTarget]);

    // Global click handler to deselect comments when clicking outside
    useEffect(() => {
      if (!selectedCommentId) return;

      const handleDocumentClick = (e: MouseEvent) => {
        const target = e.target as HTMLElement;
        // Check if click is inside a comment card
        const clickedInsideCard = target.closest('[data-comment-card]');

        // If click is outside any comment card, deselect
        if (!clickedInsideCard) {
          dispatch(setSelectedCommentId(null));
        }
      };

      // Use mousedown instead of click to avoid conflicts with card onClick handlers
      document.addEventListener('mousedown', handleDocumentClick);
      return () => {
        document.removeEventListener('mousedown', handleDocumentClick);
      };
    }, [selectedCommentId, dispatch]);

    // Text selection hook for citation creation and menu
    const { menuElement } = useTextSelection({
      containerRef: boundaryRef,
      triggers: { mouseup: true, hotkey: true },
      renderMenu: ({ citation, dismiss }) => {
        return (
          <button
            onClick={() => {
              dispatch(addCitationToDraft(citation));
              dispatch(setCommentSidebarCollapsed(false));
              dismiss();
            }}
            className="flex items-center gap-2 px-3 py-2 text-sm text-primary bg-background border border-border rounded-md shadow-lg hover:bg-accent transition-colors"
          >
            <MessageSquarePlus className="h-4 w-4" />
            Comment
          </button>
        );
      },
    });

    // List mode comments: all comment types for current transcript (or all transcripts if showAllTranscripts is true)
    const filteredComments = useMemo(() => {
      const checkInTranscript = (transcriptId: string) => {
        const commentTranscriptIdx = transcriptIdToIdx[transcriptId];
        return commentTranscriptIdx === transcriptIdx;
      };

      const shouldIncludeComment = (comment: Comment) => {
        // Check if any citation matches the filter criteria
        const citations = comment.citations;
        if (!citations || citations.length === 0) return false;

        if (activeCommentTab === 'inline') {
          return citations.some((citation) => {
            if (citation.target.item.item_type === 'block_content') {
              return checkInTranscript(citation.target.item.transcript_id);
            }
            return false;
          });
        } else if (activeCommentTab === 'list') {
          // Include all comments when showing all transcripts
          if (showAllTranscripts) {
            return true;
          }
          return citations.some((citation) => {
            // Include comments on the agent run metadata
            if (citation.target.item.item_type === 'agent_run_metadata') {
              return true;
            }
            // There are only four item_types, safe to assume that these three have a transcript_id
            return checkInTranscript(citation.target.item.transcript_id);
          });
        }
        return false;
      };

      const filtered: Comment[] = comments.filter(shouldIncludeComment);

      if (draftComment && shouldIncludeComment(draftComment)) {
        filtered.push(draftComment);
      }

      return filtered;
    }, [
      comments,
      draftComment,
      showAllTranscripts,
      transcriptIdToIdx,
      transcriptIdx,
      activeCommentTab,
    ]);

    // Memoize what comments are assigned to what message blocks
    // so we know where to render highlights
    const blockIdxToCommentsMap = useMemo(() => {
      // Build a map from blockIdxs --> comments
      // A comment can appear in multiple blocks if it has multiple citations
      const map: Record<number, Comment[]> = {};
      for (const comment of filteredComments) {
        for (const citation of comment.citations) {
          if (citation.target.item.item_type !== 'block_content') continue;
          // Only show highlights for comments on the current transcript
          if (citation.target.item.transcript_id !== selectedTranscriptId)
            continue;
          const blockIdx = citation.target.item.block_idx;
          if (!map[blockIdx]) map[blockIdx] = [];
          // Avoid adding the same comment twice to the same block
          if (!map[blockIdx].includes(comment)) {
            map[blockIdx].push(comment);
          }
        }
      }
      return map;
    }, [filteredComments, selectedTranscriptId]);

    const handleAddComment = useCallback(
      (
        params:
          | { type: 'agent_run'; metadataKey?: string }
          | { type: 'transcript'; metadataKey?: string }
          | { type: 'block_metadata'; blockIdx: number; metadataKey: string }
          | { type: 'block_content'; blockIdx: number }
      ) => {
        if (!collectionId || !agentRunId) return;

        let target: CitationTarget;
        let tab: CommentTab = 'list';

        switch (params.type) {
          case 'agent_run':
            target = {
              item: {
                item_type: 'agent_run_metadata',
                agent_run_id: agentRunId,
                collection_id: collectionId,
                metadata_key: params.metadataKey || '',
              },
              text_range: null,
            };
            break;
          case 'transcript':
            if (!selectedTranscriptId) return;
            target = {
              item: {
                item_type: 'transcript_metadata',
                agent_run_id: agentRunId,
                collection_id: collectionId,
                transcript_id: selectedTranscriptId,
                metadata_key: params.metadataKey || '',
              },
              text_range: null,
            };
            break;
          case 'block_metadata':
            if (!selectedTranscriptId) return;
            target = {
              item: {
                item_type: 'block_metadata',
                agent_run_id: agentRunId,
                collection_id: collectionId,
                transcript_id: selectedTranscriptId,
                block_idx: params.blockIdx,
                metadata_key: params.metadataKey,
              },
              text_range: null,
            };
            break;
          case 'block_content':
            if (!selectedTranscriptId) return;
            target = {
              item: {
                item_type: 'block_content',
                agent_run_id: agentRunId,
                collection_id: collectionId,
                transcript_id: selectedTranscriptId,
                block_idx: params.blockIdx,
              },
              text_range: null,
            };
            tab = 'inline';
            break;
        }

        dispatch(addCitationToDraft(target));
        setActiveCommentTab(tab);
        dispatch(setCommentSidebarCollapsed(false));
      },
      [collectionId, agentRunId, selectedTranscriptId, dispatch]
    );

    // Handle clicking on a block title for comments created on transcript blocks
    const handleBlockClick = useCallback(
      (blockIdx: number) => {
        // Find the first comment for this block
        const blockComments = filteredComments.filter((c) =>
          c.citations.some(
            (citation) =>
              citation.target.item.item_type === 'block_content' &&
              citation.target.item.block_idx === blockIdx
          )
        );

        if (blockComments.length > 0) {
          // Sort by text position and select the first one
          const sorted = [...blockComments].sort((a, b) => {
            const aCitation = a.citations.find(
              (citation) =>
                citation.target.item.item_type === 'block_content' &&
                citation.target.item.block_idx === blockIdx
            );
            const bCitation = b.citations.find(
              (citation) =>
                citation.target.item.item_type === 'block_content' &&
                citation.target.item.block_idx === blockIdx
            );
            const aStart = aCitation?.target.text_range?.target_start_idx ?? -1;
            const bStart = bCitation?.target.text_range?.target_start_idx ?? -1;
            return aStart - bStart;
          });
          dispatch(setSelectedCommentId(sorted[0].id));
          setActiveCommentTab('inline');
          dispatch(setCommentSidebarCollapsed(false));
        }
      },
      [filteredComments, dispatch]
    );

    // Determine if we should show comments area
    const hasComments = comments.length > 0 || draftComment !== null;

    return (
      <div className="h-full flex flex-col min-h-0">
        {/* Header area Content */}
        {agentRun && (
          <>
            <div className="flex flex-col gap-1 agent-run-viewer">
              <div className="flex items-center justify-between space-x-1">
                <div className="flex items-center space-x-1">
                  {headerLeftActions}
                  <span className="font-semibold text-sm shrink-0">
                    Agent Run
                  </span>
                  <UuidPill uuid={agentRun?.id} />
                  {agentRun && (
                    <MetadataPopover.Root
                      open={metadataIntent?.type === 'run'}
                      onOpenChange={(open) => {
                        setMetadataIntent(open ? { type: 'run' } : null);
                      }}
                    >
                      <MetadataPopover.DefaultTrigger />
                      <MetadataPopover.Content title="Agent Run Metadata">
                        <MetadataPopover.Body metadata={agentRun.metadata}>
                          {(md) => (
                            <MetadataBlock
                              metadata={md}
                              showSearchControls={true}
                              citedKey={
                                metadataIntent?.type === 'run'
                                  ? metadataIntent.citedKey
                                  : undefined
                              }
                              textRange={
                                metadataIntent?.type === 'run'
                                  ? metadataIntent.textRange
                                  : undefined
                              }
                              onAddComment={
                                hasWritePermission
                                  ? (key) =>
                                      handleAddComment({
                                        type: 'agent_run',
                                        metadataKey: key,
                                      })
                                  : undefined
                              }
                            />
                          )}
                        </MetadataPopover.Body>
                      </MetadataPopover.Content>
                    </MetadataPopover.Root>
                  )}
                </div>
                {headerRightActions}
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
              {shouldShowTranscriptNavigator &&
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
              {shouldShowTranscriptNavigator && (
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
                  {/* Fixed Headers Row */}
                  <div className="flex flex-row border-border flex-shrink-0">
                    {/* Transcript header */}
                    <div
                      className={cn(
                        'flex-1 min-w-0 space-y-1',
                        hasComments &&
                          !commentSidebarCollapsed &&
                          'border-r border-border'
                      )}
                    >
                      <div className="flex items-center justify-between min-w-0">
                        {selectedTranscriptId && (
                          <div className="flex items-center space-x-1 min-w-0 overflow-hidden">
                            {/* Only show toggle button if there are multiple transcripts and sidebar is hidden */}
                            {shouldShowTranscriptNavigator &&
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
                            <span className="font-semibold text-sm">
                              Transcript
                            </span>
                            <UuidPill uuid={selectedTranscriptId} />
                            {(() => {
                              const isTranscriptIntent =
                                metadataIntent?.type === 'transcript' &&
                                metadataIntent.transcriptId ===
                                  selectedTranscriptId;
                              const citedKey = isTranscriptIntent
                                ? metadataIntent?.citedKey
                                : undefined;
                              const textRange = isTranscriptIntent
                                ? metadataIntent?.textRange
                                : undefined;
                              return (
                                <MetadataPopover.Root
                                  open={Boolean(isTranscriptIntent)}
                                  onOpenChange={(open) => {
                                    setMetadataIntent(
                                      open && selectedTranscriptId
                                        ? {
                                            type: 'transcript',
                                            transcriptId: selectedTranscriptId,
                                          }
                                        : null
                                    );
                                  }}
                                >
                                  <MetadataPopover.DefaultTrigger />
                                  <MetadataPopover.Content
                                    title={`Transcript Metadata`}
                                  >
                                    <MetadataPopover.Body
                                      metadata={
                                        (selectedTranscriptId
                                          ? transcriptsById[
                                              selectedTranscriptId
                                            ]
                                          : undefined
                                        )?.metadata || {}
                                      }
                                    >
                                      {(md) => (
                                        <MetadataBlock
                                          metadata={md}
                                          showSearchControls={true}
                                          citedKey={citedKey}
                                          textRange={textRange}
                                          onAddComment={
                                            hasWritePermission
                                              ? (key) =>
                                                  handleAddComment({
                                                    type: 'transcript',
                                                    metadataKey: key,
                                                  })
                                              : undefined
                                          }
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

                    {/* Comment header (conditionally rendered) */}
                    <div className="w-80">
                      <CommentSidebarHeader
                        isCollapsed={commentSidebarCollapsed}
                        onToggleCollapsed={() =>
                          dispatch(
                            setCommentSidebarCollapsed(!commentSidebarCollapsed)
                          )
                        }
                        activeTab={activeCommentTab}
                        onTabChange={setActiveCommentTab}
                        showAllTranscripts={showAllTranscripts}
                        onSetShowAllTranscripts={setShowAllTranscripts}
                        commentCount={filteredComments.length}
                      />
                    </div>
                  </div>

                  {/* Relative wrapper for scroll container and fixed buttons */}
                  <div className="relative flex-1 min-h-0">
                    {/* Shared Scroll Container */}
                    <div
                      ref={scrollContainerRef}
                      className="absolute inset-0 overflow-y-auto custom-scrollbar"
                      // Disable browser scroll anchoring, which was causing the viewport to jump when creating a new draft comment
                      style={{ overflowAnchor: 'none' }}
                    >
                      <div className="flex flex-row items-stretch">
                        {/* Messages column */}
                        <div
                          className={cn(
                            'flex-1 space-y-2',
                            hasComments &&
                              !commentSidebarCollapsed &&
                              'pr-1 border-r border-border'
                          )}
                        >
                          {transcript.messages.map((message, index) => {
                            const blockId = `t-${transcriptIdx}_b-${index}`;
                            const messageId = (message as any)?.id as
                              | string
                              | undefined;
                            const hasTelemetry =
                              typeof messageId === 'string' &&
                              messageId.length > 0 &&
                              telemetryMessageIds.has(messageId);
                            const isMsgIntent =
                              metadataIntent?.type === 'message' &&
                              metadataIntent.transcriptId ===
                                selectedTranscriptId &&
                              metadataIntent.blockIdx === index;
                            const msgCitedKey = isMsgIntent
                              ? metadataIntent?.citedKey
                              : undefined;
                            const msgCitedRange = isMsgIntent
                              ? metadataIntent?.textRange
                              : undefined;

                            const citedTargets = getCitationsForBlock(
                              allCitations,
                              selectedCitation,
                              index,
                              selectedTranscriptId!
                            );

                            if (
                              !selectedTranscriptId ||
                              !collectionId ||
                              !agentRunId
                            )
                              return null;

                            const blockComments =
                              blockIdxToCommentsMap[index] ?? [];

                            const transcriptBlockContentItem: TranscriptBlockContentItem =
                              {
                                item_type: 'block_content',
                                agent_run_id: agentRunId,
                                collection_id: collectionId,
                                transcript_id: selectedTranscriptId,
                                block_idx: index,
                              };

                            return (
                              <MessageBox
                                key={index}
                                message={message}
                                index={index}
                                blockId={blockId}
                                isHighlighted={highlightedBlock === blockId}
                                comments={blockComments}
                                citedTargets={citedTargets}
                                prettyPrintJsonMessages={
                                  prettyPrintJsonMessages
                                }
                                setPrettyPrintJsonMessages={
                                  setPrettyPrintJsonMessages
                                }
                                hasTelemetry={hasTelemetry}
                                metadataDialogControl={{
                                  open: Boolean(isMsgIntent),
                                  onOpenChange: (open) => {
                                    setMetadataIntent(
                                      open && selectedTranscriptId
                                        ? {
                                            type: 'message',
                                            transcriptId: selectedTranscriptId,
                                            blockIdx: index,
                                          }
                                        : null
                                    );
                                  },
                                  citedKey: msgCitedKey,
                                  citedTextRange: msgCitedRange,
                                }}
                                dataContext={transcriptBlockContentItem}
                                onAddMetadataComment={
                                  hasWritePermission
                                    ? (key) =>
                                        handleAddComment({
                                          type: 'block_metadata',
                                          blockIdx: index,
                                          metadataKey: key,
                                        })
                                    : undefined
                                }
                                onAddBlockComment={
                                  hasWritePermission
                                    ? () =>
                                        handleAddComment({
                                          type: 'block_content',
                                          blockIdx: index,
                                        })
                                    : undefined
                                }
                                onBlockClick={() =>
                                  hasComments
                                    ? handleBlockClick(index)
                                    : undefined
                                }
                              />
                            );
                          })}
                          {/* Text selection menu for creating comments */}
                          {hasWritePermission && menuElement}
                        </div>

                        {/* Comments column */}
                        {!commentSidebarCollapsed && (
                          <div
                            className={cn(
                              'w-80 bg-muted/50',
                              activeCommentTab === 'list'
                                ? 'sticky top-0 self-start h-[calc(100vh-8rem)] overflow-y-auto  custom-scrollbar'
                                : 'self-stretch'
                            )}
                          >
                            <CommentSidebarContent
                              commentsForTranscript={filteredComments}
                              listModeComments={filteredComments}
                              scrollContainer={scrollNode}
                              scrollToCitation={focusCitationTarget}
                              activeTab={activeCommentTab}
                              collectionId={collectionId}
                              agentRunId={agentRunId}
                            />
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Navigation buttons - fixed relative to wrapper */}
                    <div
                      className="absolute bottom-3 flex flex-col gap-1 pointer-events-none"
                      style={{
                        right: !commentSidebarCollapsed
                          ? 'calc(320px + 12px)'
                          : '12px',
                      }}
                    >
                      <div className="bg-muted border border-border rounded-md shadow-sm flex flex-col pointer-events-auto">
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
      </div>
    );
  }
);

// Add display name for forwardRef
AgentRunViewer.displayName = 'AgentRunViewer';

export default AgentRunViewer;
