import {
  ChevronRight,
  ChevronLeft,
  ChevronFirst,
  ChevronLast,
  Upload,
  Loader2,
} from 'lucide-react';
import React, {
  useMemo,
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react';
import { skipToken } from '@reduxjs/toolkit/query';

import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { useAppDispatch, useAppSelector } from '../store/hooks';

import { ChartsArea } from './ChartsArea';
import AgentRunCard from './AgentRunCard';
import UploadRunsButton from './UploadRunsButton';
import UploadRunsDialog from './UploadRunsDialog';

import { TranscriptFilterControls } from './TranscriptFilterControls';

import { setExperimentViewerScrollPosition } from '../store/experimentViewerSlice';
import { useDebounce } from '@/hooks/use-debounce';
import { useDragAndDrop } from '@/hooks/use-drag-drop';
import {
  useGetAgentRunIdsQuery,
  useGetAgentRunMetadataQuery,
  collectionApi,
} from '../api/collectionApi';

// Constants for magic numbers
const PAGINATION_LIMIT = 100;

export default function ExperimentViewer() {
  const dispatch = useAppDispatch();

  // Get all state at the top level
  const collectionId = useAppSelector((state) => state.collection.collectionId);

  const experimentViewerScrollPosition = useAppSelector(
    (state) => state.experimentViewer.experimentViewerScrollPosition
  );

  // Fetch agent run IDs using RTK skipToken
  const { data: rawAgentRunIds, isLoading: isLoadingAgentRunIds } =
    useGetAgentRunIdsQuery(collectionId ? { collectionId } : skipToken);

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

  // Upload state
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [draggedFile, setDraggedFile] = useState<File | null>(null);

  // Drag and drop functionality
  const handleFileDropped = useCallback((file: File) => {
    setDraggedFile(file);
    setUploadDialogOpen(true);
  }, []);

  const { isDragActive, isOverDropZone, dropZoneHandlers } =
    useDragAndDrop(handleFileDropped);

  const handleUploadDialogClose = useCallback(() => {
    setUploadDialogOpen(false);
    setDraggedFile(null);
  }, []);

  const handleUploadSuccess = useCallback(() => {
    fetchedAgentRunIdsRef.current.clear();
    dispatch(
      collectionApi.util.invalidateTags([
        'AgentRunIds',
        'AgentRunMetadataFields',
      ])
    );
  }, [dispatch]);

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
    return rawAgentRunIds;
  }, [rawAgentRunIds]);

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

  // Fetch agent run metadata when the agent run IDs change
  const { data: agentRunMetadata } = useGetAgentRunMetadataQuery(
    {
      collectionId: collectionId!,
      agent_run_ids: currentPageItems,
    },
    { skip: !collectionId }
  );

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

  return (
    <Card className="flex-1 flex flex-col h-full min-w-0">
      {/* Header with organization dropdown - always visible */}
      <div className="flex justify-between items-center shrink-0">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Chart Visualization</div>
          <div className="text-xs text-muted-foreground">
            Plot trends in your data
          </div>
        </div>
      </div>

      <ChartsArea />

      {/* Agent run list */}
      <div className="flex flex-row items-center justify-between">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Agent Run List</div>
          <div className="text-xs text-muted-foreground">
            {agentRunIds?.length || 0} agent runs matching the current view
          </div>
        </div>

        <UploadRunsButton onImportSuccess={handleUploadSuccess} />
      </div>
      <TranscriptFilterControls />

      <div className="flex-1 custom-scrollbar min-w-0 overflow-y-auto relative">
        <div
          ref={containerRef}
          className="h-full space-y-1"
          {...dropZoneHandlers}
        >
          {isDragActive && (
            <div
              className={cn(
                'absolute inset-0 flex flex-col items-center justify-center z-50 transition-all duration-200 border-2 rounded',
                isOverDropZone
                  ? 'bg-blue-100 bg-opacity-95 border-blue-text border-solid'
                  : 'bg-blue-100 bg-opacity-80 border-blue-text border-dashed'
              )}
              style={{
                pointerEvents: 'none',
              }}
            >
              <Upload className="h-8 w-8 text-blue-text" />
              <div
                className={cn(
                  'mt-2 text-sm font-medium transition-all duration-200 text-blue-text',
                  isOverDropZone ? 'scale-105' : ''
                )}
              >
                Drop Inspect logs to upload
              </div>
            </div>
          )}

          {agentRunIds === undefined && (
            <div className="h-full flex items-center justify-center text-center min-h-[200px] text-xs items-center">
              <Loader2 size={16} className="animate-spin" />
            </div>
          )}

          {agentRunIds !== undefined && agentRunIds.length > 0 ? (
            currentPageItems.map((agentRunId) => (
              <AgentRunCard
                key={agentRunId}
                agentRunId={agentRunId}
                metadata={agentRunMetadata?.[agentRunId]}
              />
            ))
          ) : (
            <div className="h-full flex items-center justify-center text-center min-h-[200px] text-xs">
              <div className="flex flex-col items-center space-y-3">
                <Upload className="h-12 w-12 text-muted-foreground" />
                <div className="text-muted-foreground">No agent runs found</div>
                <Button asChild variant="outline" size="sm">
                  <a
                    href="https://docs.transluce.org/en/latest/quickstart/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    See quickstart guide
                  </a>
                </Button>
              </div>
            </div>
          )}
        </div>
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

      <UploadRunsDialog
        isOpen={uploadDialogOpen}
        onClose={handleUploadDialogClose}
        file={draggedFile}
        onImportSuccess={handleUploadSuccess}
      />
    </Card>
  );
}
