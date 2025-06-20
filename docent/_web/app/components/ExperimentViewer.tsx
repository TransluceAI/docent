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
import GraphArea from './GraphArea';

import { useAppDispatch, useAppSelector } from '../store/hooks';

import DimensionSelector from './DimensionSelector';

import AgentRunCard from './AgentRunCard';
import { useDebounce } from '@/hooks/use-debounce';
import {
  setExperimentViewerScrollPosition,
  setChartType,
} from '../store/experimentViewerSlice';
import { getAgentRunMetadata } from '../store/frameSlice';
import TableArea from './TableArea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { TranscriptFilterControls } from './TranscriptFilterControls';

// Constants for magic numbers
const PAGINATION_LIMIT = 100;

export default function ExperimentViewer() {
  const dispatch = useAppDispatch();

  // Frame state
  const frameGridId = useAppSelector((state) => state.frame.frameGridId);
  const innerDimId = useAppSelector((state) => state.frame.innerDimId);
  const outerDimId = useAppSelector((state) => state.frame.outerDimId);

  // Search state
  const loadingSearchQuery = useAppSelector(
    (state) => state.search.loadingSearchQuery
  );
  const curSearchQuery = useAppSelector((state) => state.search.curSearchQuery);
  const searchResultMap = useAppSelector(
    (state) => state.search.searchResultMap
  );

  // EV state
  const experimentViewerScrollPosition = useAppSelector(
    (state) => state.experimentViewer.experimentViewerScrollPosition
  );
  const chartType = useAppSelector((state) => state.experimentViewer.chartType);
  const rawStatMarginals = useAppSelector(
    (state) => state.experimentViewer.statMarginals
  );
  const rawIdMarginals = useAppSelector(
    (state) => state.experimentViewer.idMarginals
  );

  /**
   * Scrolling
   */

  const scrolledOnceRef = useRef(false);
  const [scrollPosition, setScrollPosition] = useState<number | undefined>(
    undefined
  );
  const debouncedScrollPosition = useDebounce(scrollPosition, 100);

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

  // Create a function to get the marginal key - safe to use even if data is null
  const getMarginalKey = useCallback(
    (innerId: string | null, outerId: string | null) => {
      if (innerId !== null && outerId !== null) {
        return `${innerDimId},${innerId}|${outerDimId},${outerId}`;
      } else if (innerId !== null) {
        return `${innerDimId},${innerId}`;
      } else if (outerId !== null) {
        return `${outerDimId},${outerId}`;
      } else {
        return '';
      }
    },
    [innerDimId, outerDimId]
  );

  // Filter to IDs to ones that have the attribute query
  const idMarginals = useMemo(() => {
    if (!rawIdMarginals) return rawIdMarginals;
    if (!curSearchQuery) return rawIdMarginals;

    // Filter the keys and their datapoints based on attribute query
    const filtered = Object.entries(rawIdMarginals).reduce(
      (result, [key, datapointsList]) => {
        // Filter datapoints to ones that have the attributes
        const filteredAgentRuns = datapointsList.filter((datapointId) => {
          if (curSearchQuery) {
            const attrs = searchResultMap?.[datapointId]?.[curSearchQuery];
            return attrs && attrs.length && attrs[0].value !== null;
          }
          return true;
        });

        // Only include keys that have at least one datapoint after filtering
        if (filteredAgentRuns.length > 0) {
          result[key] = filteredAgentRuns;
        }

        return result;
      },
      {} as typeof rawIdMarginals
    );

    return filtered;
  }, [rawIdMarginals, curSearchQuery, searchResultMap]);

  // Only keep stat marginals that have datapoints, after filtering by attribute query
  const statMarginals = useMemo(() => {
    if (!rawStatMarginals) return rawStatMarginals;
    if (!curSearchQuery) return rawStatMarginals;
    return Object.fromEntries(
      Object.entries(rawStatMarginals).filter(([key, _]) => {
        return idMarginals && key in idMarginals;
      })
    );
  }, [rawStatMarginals, curSearchQuery, idMarginals]);

  // FLAT LIST: Collect all agent runs (datapoint IDs) from idMarginals
  const allAgentRunEntries: [string, string[]][] = useMemo(() => {
    if (!idMarginals) return [];
    return Object.entries(idMarginals);
  }, [idMarginals]);

  // Flatten agent run entries for pagination
  const flatAgentRuns = useMemo(() => {
    const result: { agentRunId: string; marginalKey: string }[] = [];
    allAgentRunEntries.forEach(([marginalKey, agentRunIds]) => {
      agentRunIds.forEach((agentRunId) => {
        result.push({ agentRunId, marginalKey });
      });
    });
    return result;
  }, [allAgentRunEntries]);

  // Add pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = PAGINATION_LIMIT; // Use constant instead of hardcoded value

  // Calculate pagination values (memoized)
  const totalPages = useMemo(
    () => Math.ceil(flatAgentRuns.length / itemsPerPage),
    [flatAgentRuns.length, itemsPerPage]
  );
  const startIndex = useMemo(
    () => (currentPage - 1) * itemsPerPage,
    [currentPage, itemsPerPage]
  );
  const endIndex = useMemo(
    () => Math.min(startIndex + itemsPerPage, flatAgentRuns.length),
    [startIndex, itemsPerPage, flatAgentRuns.length]
  );
  const currentPageItems = useMemo(
    () => flatAgentRuns.slice(startIndex, endIndex),
    [flatAgentRuns, startIndex, endIndex]
  );

  // When the page changes, request metadata for the new page
  useEffect(() => {
    if (!frameGridId) return;
    dispatch(
      getAgentRunMetadata(currentPageItems.map(({ agentRunId }) => agentRunId))
    );
  }, [currentPageItems, dispatch, frameGridId]);

  // Pagination controls
  const goToPage = useCallback(
    (page: number) => {
      setCurrentPage(Math.max(1, Math.min(page, totalPages)));

      // Recompute in this function so we can figure out which IDs to request metadata for
      // TODO(mengk): refactor this.
      const startIndex = (currentPage - 1) * itemsPerPage;
      const endIndex = Math.min(
        startIndex + itemsPerPage,
        flatAgentRuns.length
      );
      const currentPageItems = flatAgentRuns.slice(startIndex, endIndex);

      dispatch(
        getAgentRunMetadata(
          currentPageItems.map(({ agentRunId }) => agentRunId)
        )
      );
    },
    [currentPage, dispatch, flatAgentRuns, itemsPerPage, totalPages]
  );

  // If data isn't available, show a loading spinner
  if (!statMarginals || !idMarginals) {
    return (
      <Card className="h-full flex-1 p-3">
        <div className="flex-1 flex flex-col items-center justify-center space-y-2 h-full">
          <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
        </div>
      </Card>
    );
  }

  return (
    <Card className="flex-1 p-3 flex flex-col min-w-0 space-y-3">
      {/* Header with organization dropdown - always visible */}
      <div className="flex justify-between items-center shrink-0">
        <div>
          <div className="text-sm font-semibold">Grouped Visualization</div>
          <div className="text-xs">Select fields to group by</div>
        </div>
        {/* Place dimension selector and chart type selector in the header */}
        <div className="flex items-center gap-4">
          <DimensionSelector />
          <div className="flex items-center space-x-1">
            <span className="text-xs text-gray-500">Chart:</span>
            <Select
              value={chartType || 'bar'}
              onValueChange={(value: 'bar' | 'line' | 'table') =>
                dispatch(setChartType(value))
              }
            >
              <SelectTrigger className="h-6 w-16 text-xs border-gray-200 bg-transparent hover:bg-gray-50 px-2 font-normal">
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
          </div>
        </div>
      </div>
      {chartType === 'table' && <TableArea />}
      {(chartType === 'bar' || chartType === 'line') && <GraphArea />}

      {/* Agent run list */}
      <div>
        <div className="text-sm font-semibold">Agent Run List</div>
        <div className="text-xs">
          {flatAgentRuns.length} agent runs matching the current view
        </div>
      </div>
      <TranscriptFilterControls />
      <div
        className="flex-1 space-y-1 custom-scrollbar min-w-0 overflow-y-auto ml-3"
        ref={containerRef}
      >
        {currentPageItems.map(({ agentRunId }) => (
          <AgentRunCard key={agentRunId} agentRunId={agentRunId} />
        ))}
        {flatAgentRuns.length === 0 && (
          <div className="text-xs text-gray-500 min-h-[24px]">
            {loadingSearchQuery ? (
              <div className="flex items-center space-x-2">
                <span>Loading results...</span>
                <Loader2 className="h-3 w-3 animate-spin text-gray-500" />
              </div>
            ) : (
              'No results found'
            )}
          </div>
        )}
      </div>

      {/* Pagination controls */}
      <div className="flex items-center justify-between shrink-0 ml-2">
        <div className="flex items-center gap-1">
          <button
            onClick={() => goToPage(1)}
            disabled={currentPage === 1}
            className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronFirst className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage === 1}
            className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <span className="text-xs font-mono px-1">
            {currentPage}/{totalPages}
          </span>
          <button
            onClick={() => goToPage(currentPage + 1)}
            disabled={currentPage === totalPages}
            className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => goToPage(totalPages)}
            disabled={currentPage === totalPages}
            className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLast className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="text-[11px] text-gray-500">
          {startIndex + 1}-{endIndex} of {flatAgentRuns.length}
        </div>
      </div>
    </Card>
  );
}
