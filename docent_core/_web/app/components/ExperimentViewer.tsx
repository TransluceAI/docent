import {
  ChevronRight,
  Loader2,
  ChevronLeft,
  ChevronFirst,
  ChevronLast,
} from 'lucide-react';
import React, {
  useMemo,
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react';

import { Card } from '@/components/ui/card';

import { useAppDispatch, useAppSelector } from '../store/hooks';

import DimensionSelector from './DimensionSelector';
import GraphArea from './GraphArea';
import TableArea from './TableArea';
import AgentRunCard from './AgentRunCard';

import { getAgentRunMetadata } from '../store/collectionSlice';
import { TranscriptFilterControls } from './TranscriptFilterControls';

import { setExperimentViewerScrollPosition } from '../store/experimentViewerSlice';
import { useDebounce } from '@/hooks/use-debounce';

// Constants for magic numbers
const PAGINATION_LIMIT = 100;

export default function ExperimentViewer() {
  const dispatch = useAppDispatch();

  // Get all state at the top level
  const { innerBinKey, outerBinKey, collectionId } = useAppSelector(
    (state) => state.collection
  );

  const {
    loadingSearchQuery,
    curSearchQuery,
    currentSearchHitCount,
    searchResultMap: attributeMap,
  } = useAppSelector((state) => state.search);

  const {
    experimentViewerScrollPosition,
    binStats: rawBinStats,
    agentRunIds: rawAgentRunIds,
    chartType,
  } = useAppSelector((state) => state.experimentViewer);

  /**
   * Scrolling
   */
  const scrolledOnceRef = useRef(false);
  const [scrollPosition, setScrollPosition] = useState<number | undefined>(
    undefined
  );
  const debouncedScrollPosition = useDebounce(scrollPosition, 100);

  // Track which agent run IDs have already been fetched to prevent duplicate calls
  const fetchedAgentRunIdsRef = useRef<Set<string>>(new Set());

  // Use debouncing to prevent too many updates
  useEffect(() => {
    if (debouncedScrollPosition) {
      dispatch(setExperimentViewerScrollPosition(debouncedScrollPosition));
    }
  }, [debouncedScrollPosition, dispatch]);

  const containerRef = useCallback(
    (node: HTMLDivElement) => {
      if (!node) return;

      // If there is an existing scroll position, set it
      if (experimentViewerScrollPosition && !scrolledOnceRef.current) {
        node.scrollTop = experimentViewerScrollPosition;
        scrolledOnceRef.current = true;
      }

      // Save scroll position when user scrolls
      const handleScroll = () => setScrollPosition(node.scrollTop);
      node.addEventListener('scroll', handleScroll);
      return () => {
        node.removeEventListener('scroll', handleScroll);
      };
    },
    [experimentViewerScrollPosition]
  );

  // Filter agent run IDs to ones that have the attribute query
  const agentRunIds = useMemo(() => {
    if (!rawAgentRunIds) return rawAgentRunIds;
    if (!curSearchQuery) return rawAgentRunIds;

    // Filter agent runs to ones that have the attributes
    const filteredAgentRuns = rawAgentRunIds.filter((agentRunId) => {
      if (curSearchQuery) {
        const attrs = attributeMap?.[agentRunId]?.[curSearchQuery];
        return attrs && attrs.length && attrs[0].value !== null;
      }
      return true;
    });

    return filteredAgentRuns;
  }, [rawAgentRunIds, curSearchQuery, attributeMap]);

  // Add pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = PAGINATION_LIMIT; // Use constant instead of hardcoded value

  // Calculate pagination values
  const totalPages = Math.ceil((agentRunIds?.length || 0) / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = Math.min(
    startIndex + itemsPerPage,
    agentRunIds?.length || 0
  );
  const currentPageItems = useMemo(
    () => agentRunIds?.slice(startIndex, endIndex) || [],
    [agentRunIds, startIndex, endIndex]
  );

  // When the page changes, request metadata for the new page
  useEffect(() => {
    if (!collectionId || !currentPageItems.length) return;

    // Only fetch metadata for agent run IDs that haven't been fetched before
    const agentRunIdsToFetch = currentPageItems.filter(
      (id) => id && !fetchedAgentRunIdsRef.current.has(id)
    );

    if (agentRunIdsToFetch.length === 0) return;

    // Mark these IDs as fetched
    agentRunIdsToFetch.forEach((id) => fetchedAgentRunIdsRef.current.add(id));

    dispatch(getAgentRunMetadata(agentRunIdsToFetch));
  }, [currentPageItems, dispatch, collectionId]);

  // Clear fetched IDs when the overall agent run list changes
  useEffect(() => {
    fetchedAgentRunIdsRef.current.clear();
  }, [agentRunIds]);

  // Pagination controls
  const goToPage = useCallback(
    (page: number) => {
      setCurrentPage(Math.max(1, Math.min(page, totalPages)));
    },
    [totalPages]
  );

  // If data isn't available, show a loading spinner
  // But if both dimensions are None, we don't need stats, so we can show the agent run list
  if (!rawBinStats && (outerBinKey || innerBinKey)) {
    return (
      <Card className="h-full flex-1 p-3">
        <div className="flex-1 flex flex-col items-center justify-center space-y-2 h-full">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      </Card>
    );
  }

  return (
    <Card className="flex-1 p-3 flex flex-col min-w-0 space-y-3">
      {/* Header with organization dropdown - always visible */}
      <div className="flex justify-between items-center shrink-0">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Grouped Visualization</div>
          <div className="text-xs text-muted-foreground">
            Select fields to group by, and click to filter
          </div>
        </div>
        {/* Place dimension selector and chart type selector in the header */}
        <div className="flex items-center gap-4">
          <DimensionSelector />
          {/* <div className="flex items-center space-x-1">
            <span className="text-xs text-muted-foreground">Chart:</span>
            <Select
              value={chartType || 'table'}
              onValueChange={(value: 'bar' | 'line' | 'table') =>
                dispatch(setChartType(value))
              }
            >
              <SelectTrigger className="h-7 w-16 text-xs border-border bg-transparent hover:bg-secondary px-2 font-normal">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="table" className="text-xs">
                  Table
                </SelectItem>
                <SelectItem value="bar" className="text-xs">
                  Bar
                </SelectItem>
                <SelectItem value="line" className="text-xs">
                  Line
                </SelectItem>
              </SelectContent>
            </Select>
          </div> */}
        </div>
      </div>

      {/* Dimension scores table or graph - conditional based on chart type */}
      {chartType === 'table' ? (
        <TableArea />
      ) : chartType === 'bar' || chartType === 'line' ? (
        <GraphArea />
      ) : null}

      {/* Agent run list */}
      <div className="flex flex-col">
        <div className="text-sm font-semibold">Agent Run List</div>
        <div className="text-xs text-muted-foreground">
          {agentRunIds?.length || 0} agent runs matching the current view
          {curSearchQuery && (
            <span>, {currentSearchHitCount} hits for current query</span>
          )}
        </div>
      </div>
      <TranscriptFilterControls />
      <div
        className="flex-1 space-y-1 custom-scrollbar min-w-0 overflow-y-auto"
        ref={containerRef}
      >
        {currentPageItems.map((agentRunId) => (
          <AgentRunCard key={agentRunId} agentRunId={agentRunId} />
        ))}
        {(agentRunIds?.length || 0) === 0 && (
          <div className="text-xs text-muted-foreground min-h-[24px]">
            {loadingSearchQuery ? (
              <div className="flex items-center space-x-2">
                <span>Loading results...</span>
                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
              </div>
            ) : (
              'No results found'
            )}
          </div>
        )}
      </div>

      {/* Pagination controls */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-1">
          <button
            onClick={() => goToPage(1)}
            disabled={currentPage === 1}
            className="p-0.5 rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronFirst className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage === 1}
            className="p-0.5 rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <span className="text-xs font-mono px-1">
            {currentPage}/{totalPages}
          </span>
          <button
            onClick={() => goToPage(currentPage + 1)}
            disabled={currentPage === totalPages}
            className="p-0.5 rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => goToPage(totalPages)}
            disabled={currentPage === totalPages}
            className="p-0.5 rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLast className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="text-[11px] text-muted-foreground">
          {startIndex + 1}-{endIndex} of {agentRunIds?.length || 0}
        </div>
      </div>
    </Card>
  );
}
