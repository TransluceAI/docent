'use client';

import {
  AlertTriangle,
  CornerDownLeft,
  Earth,
  HelpCircle,
  Loader2,
  Pencil,
  RefreshCw,
  Share2,
  Sparkles,
  Trash,
  Play,
  EyeOff,
  Square,
  Pause,
  Check,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { toast } from '@/hooks/use-toast';

import { deleteSearch } from '../store/collectionSlice';
import { useAppDispatch } from '../store/hooks';
import {
  clearSearch,
  clearClusteredSearchResults,
  computeSearch,
  requestClusters,
  setSearchQueryTextboxValue,
  setPaused,
} from '../store/searchSlice';
import { RootState } from '../store/store';

import ClusterViewer from './ClusterViewer';
import { ProgressBar } from './ProgressBar';
import { apiRestClient } from '../services/apiService';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import { copyToClipboard } from '@/lib/utils';

// Preset search queries with custom icons
const PRESET_QUERIES = [
  {
    id: 'env',
    label: 'Environment issues',
    query: 'potential issues with the environment the agent is operating in',
    icon: Earth,
    color: 'text-blue-text',
  },
  {
    id: 'strange',
    label: 'Strange behaviors',
    query: 'cases where the agent acted in a strange or unexpected way',
    icon: HelpCircle,
    color: 'text-orange-text',
  },
  {
    id: 'unfollow',
    label: 'Not following instructions',
    query:
      'cases where the agent did not follow instructions given to it or directly disobeyed them',
    icon: AlertTriangle,
    color: 'text-red-text',
  },
];

const DEFAULT_PLACEHOLDER_TEXT =
  "Describe what you're looking for in detail, or try a sample preset above";

const SearchArea = () => {
  const dispatch = useAppDispatch();
  const router = useRouter();

  const { collectionId, dimensionsMap } = useSelector(
    (state: RootState) => state.collection
  );
  const {
    curSearchQuery,
    activeClusterTaskId,
    loadingSearchQuery,
    loadingProgress,
    searchesWithStats,
    searchQueryTextboxValue,
    activeSearchTaskId,
    clusteredSearchResults,
    paused,
  } = useSelector((state: RootState) => state.search);

  // Pull out the search query associated with the current search query
  const activeSearchQuery = useMemo(() => {
    if (!curSearchQuery || !dimensionsMap) return undefined;
    return Object.values(dimensionsMap).find(
      (dim) => dim.search_query === curSearchQuery
    );
  }, [dimensionsMap, curSearchQuery]);

  // State variables to control cluster button behavior
  const hasClusters = useMemo(() => {
    return (
      clusteredSearchResults && Object.keys(clusteredSearchResults).length > 0
    );
  }, [clusteredSearchResults]);

  const isProcessingClusters = useMemo(() => {
    return !!activeClusterTaskId;
  }, [activeClusterTaskId]);

  const isLoadingSearch = useMemo(() => {
    return loadingSearchQuery !== undefined;
  }, [loadingSearchQuery]);

  useEffect(() => {
    if (activeSearchQuery && activeClusterTaskId == null) {
      dispatch(
        requestClusters({
          searchQuery: activeSearchQuery.search_query || activeSearchQuery.id,
          feedback: '',
        })
      );
    }
  }, [activeSearchQuery, dispatch, activeClusterTaskId]);

  /**
   * Local state for UI components
   */

  // Search box hints
  const [placeholderText, setPlaceholderText] = useState(
    DEFAULT_PLACEHOLDER_TEXT
  );
  // Cluster feedback
  const [clusterFeedback, setClusterFeedback] = useState('');
  const showFeedbackInput = useMemo(() => {
    return curSearchQuery && hasClusters;
  }, [curSearchQuery, hasClusters]);

  // Max results and paused state
  const [maxResults, setMaxResults] = useState<number | null>(10);
  const [pausedSearchQuery, setPausedSearchQuery] = useState<string | null>(
    null
  );

  const handleClearSearch = useCallback(() => {
    if (curSearchQuery) {
      dispatch(setSearchQueryTextboxValue(curSearchQuery || ''));
      setClusterFeedback('');
      dispatch(clearSearch());
    }
  }, [curSearchQuery, dispatch]);

  const handleStopSearch = useCallback(
    (job_id: string = '') => {
      const idToDelete = job_id !== '' ? job_id : activeSearchTaskId;

      if (idToDelete) {
        apiRestClient.post(`/${idToDelete}/cancel_compute_search`).then(() => {
          dispatch(setPaused(true));
        });
      }
    },
    [activeSearchTaskId, dispatch]
  );

  /**
   * Requesting searches and clusters
   */

  const handleSearch = async (query?: string) => {
    if (!query?.trim()) {
      toast({
        title: 'Missing search query',
        description: 'Please enter a search query',
        variant: 'destructive',
      });
      return;
    }

    // If paused, resume from the paused query
    let currentMaxResults = maxResults;
    if (paused && pausedSearchQuery !== null) {
      query = pausedSearchQuery;
      setPausedSearchQuery(null);
      dispatch(setPaused(false));
      setMaxResults(null);
      currentMaxResults = null;
    } else {
      setPausedSearchQuery(query);
    }

    // Reset form
    dispatch(setSearchQueryTextboxValue(''));

    // Search
    const trimmedQuery = query.trim();
    dispatch(
      computeSearch({
        searchQuery: trimmedQuery,
        maxResults: currentMaxResults,
        bringToTop: true,
      })
    );
  };

  const resumeSearchFromHistory = async (query?: string) => {
    if (!query?.trim()) {
      toast({
        title: 'Missing search query',
        description: 'Please enter a search query',
        variant: 'destructive',
      });
      return;
    }

    // Search
    const trimmedQuery = query.trim();
    dispatch(
      computeSearch({
        searchQuery: trimmedQuery,
        maxResults: null,
        bringToTop: false,
      })
    );
  };

  const handleRequestClusters = async () => {
    if (!curSearchQuery) {
      toast({
        title: 'Could not cluster data',
        description: 'Could not find curSearchQuery',
        variant: 'destructive',
      });
      return;
    }

    // Clear existing clusters when new clustering is requested
    dispatch(clearClusteredSearchResults());

    dispatch(
      requestClusters({
        searchQuery: curSearchQuery,
        feedback: clusterFeedback,
        readOnly: false,
      })
    );
  };

  /**
   * Presets in the search interface
   */

  const [isPresetHovered, setIsPresetHovered] = useState(false);

  const handleSelectPreset = (query: string) => {
    dispatch(setSearchQueryTextboxValue(query));
    setIsPresetHovered(false);
  };

  const handlePresetHover = (query: string) => {
    setIsPresetHovered(true);
    setPlaceholderText(query);
  };

  const handlePresetLeave = () => {
    setIsPresetHovered(false);
    setPlaceholderText(DEFAULT_PLACEHOLDER_TEXT);
  };

  const hasWritePermission = useHasCollectionWritePermission();

  const handleMaxResultsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    if (value === '') {
      setMaxResults(null);
    } else if (!isNaN(Number(value))) {
      setMaxResults(parseInt(value));
    } else {
      setMaxResults(null);
    }
  };

  /**
   * Handle share button
   */
  const handleShare = async (searchQuery: string) => {
    const response = await apiRestClient.post(
      `/${collectionId}/clone_own_view`
    );
    const success = await copyToClipboard(
      `${window.location.origin}${window.location.pathname}?viewId=${response.data.view_id}&searchQuery=${encodeURIComponent(searchQuery)}`
    );
    if (success) {
      toast({
        title: 'Search URL copied',
        description: 'Copied a shareable link to the clipboard',
        variant: 'default',
      });
    } else {
      toast({
        title: 'Failed to copy',
        description: 'Could not copy to clipboard',
        variant: 'destructive',
      });
    }
  };

  const shouldDisableClusterButton = useMemo(() => {
    return !hasWritePermission || isProcessingClusters || isLoadingSearch;
  }, [hasWritePermission, isProcessingClusters, isLoadingSearch]);

  return (
    <Card className="h-full flex overflow-y-auto flex-col flex-1 p-3 custom-scrollbar space-y-3">
      {/* Global search */}
      <div className="space-y-2">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Global Search</div>
          <div className="text-xs text-muted-foreground">
            Look for complex qualitative patterns, errors, or other interesting
            phenomena
          </div>
        </div>

        <div className="border rounded-sm bg-secondary p-2 space-y-1">
          <div className="flex items-center justify-between text-xs text-primary">
            Enter search query here
          </div>
          {curSearchQuery && loadingProgress && !loadingSearchQuery && (
            <div className="flex items-center justify-between text-xs">
              <div className="text-secondary">
                {loadingProgress[0]} searches finished
                {loadingProgress[1] - loadingProgress[0] > 0 && (
                  <>
                    , {loadingProgress[1] - loadingProgress[0]} had API issues{' '}
                    <span
                      className="cursor-pointer text-primary hover:text-primary"
                      onClick={() => handleSearch(curSearchQuery)}
                    >
                      (retry)
                    </span>
                  </>
                )}
              </div>
            </div>
          )}
          {curSearchQuery ? (
            <div className="space-y-2">
              <div className="flex items-center">
                <div className="flex-1">
                  <div className="px-2 py-1 bg-indigo-bg border border-indigo-border rounded text-xs font-mono whitespace-pre-wrap text-primary">
                    {curSearchQuery}
                  </div>
                </div>
                <div className="flex flex-col xl:flex-row ml-2 space-y-1 xl:space-y-0 xl:space-x-1">
                  <button
                    onClick={async () => await handleShare(curSearchQuery)}
                    className="inline-flex items-center gap-x-1 text-xs bg-blue-bg text-accent-foreground border border-blue-border px-2 py-1 rounded-md disabled:opacity-50 hover:bg-blue-muted transition-colors"
                    title="Share this search"
                    disabled={!hasWritePermission}
                  >
                    <Share2 className="h-3 w-3" />
                    Share
                  </button>
                  {loadingSearchQuery ? (
                    <>
                      <button
                        onClick={() => handleClearSearch()}
                        className="inline-flex items-center gap-x-1 text-xs bg-secondary text-muted-foreground border border-primary/80 px-1.5 py-1 rounded-md hover:bg-primary/10 transition-colors"
                        title="Clear display (search continues in background)"
                      >
                        <EyeOff className="h-3 w-3" />
                        {paused ? 'Exit view' : 'Run in background'}
                      </button>

                      {paused ? (
                        <button
                          onClick={() => handleSearch(curSearchQuery)}
                          className="inline-flex items-center gap-x-1 text-xs bg-green-bg text-green-foreground border border-green-border px-1.5 py-1 rounded-md hover:bg-green-muted transition-colors"
                          title="Resume search to get more results"
                        >
                          <Play className="h-3 w-3" />
                          Resume
                        </button>
                      ) : (
                        <button
                          onClick={() => handleStopSearch()}
                          className="inline-flex items-center gap-x-1 text-xs bg-red-bg text-primary border border-red-border px-1.5 py-1 rounded-md hover:bg-red-muted transition-colors"
                          title="Stop search and clear results"
                        >
                          <Square className="h-3 w-3" />
                          Stop
                        </button>
                      )}
                    </>
                  ) : (
                    <button
                      onClick={() => handleClearSearch()}
                      className="inline-flex items-center gap-x-1 text-xs bg-red-bg text-primary border border-red-border px-1.5 py-1 rounded-md hover:bg-red-bg transition-colors"
                      title="Stop search and clear results"
                    >
                      <RefreshCw className="h-3 w-3 mr" />
                      Clear
                    </button>
                  )}
                </div>
              </div>

              {/* Progress bar for updates */}
              {loadingSearchQuery &&
                loadingSearchQuery === curSearchQuery &&
                loadingProgress && (
                  <ProgressBar
                    current={loadingProgress[0]}
                    total={loadingProgress[1]}
                    paused={paused}
                  />
                )}
              <Button
                size="sm"
                variant="outline"
                className="text-xs w-full h-7 border border-border hover:bg-background/30"
                onClick={handleRequestClusters}
                disabled={shouldDisableClusterButton}
              >
                {activeSearchQuery && activeSearchQuery.loading_clusters ? (
                  <Loader2 className="h-3 w-3 mr-2 animate-spin" />
                ) : (
                  <Sparkles className="text-indigo-text/70 h-3 w-3 mr-2" />
                )}
                {activeSearchQuery &&
                activeSearchQuery.bins &&
                activeSearchQuery.bins.length > 0
                  ? 'Re-cluster with feedback'
                  : 'Cluster matching results'}
              </Button>

              {/* Feedback input for re-clustering - only show when requested */}
              {showFeedbackInput && (
                <div className="space-y-0.5">
                  <div className="text-xs text-primary mb-1">
                    Feedback for re-clustering
                  </div>
                  <div className="flex space-x-1 items-center">
                    <Input
                      autoFocus
                      value={clusterFeedback}
                      onChange={(e) => setClusterFeedback(e.target.value)}
                      placeholder="Describe how clusters should be improved..."
                      className="text-xs bg-background font-mono text-muted-foreground flex-1 h-7"
                      disabled={shouldDisableClusterButton}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleRequestClusters();
                        }
                      }}
                    />
                    <Button
                      size="sm"
                      onClick={() => handleRequestClusters()}
                      disabled={shouldDisableClusterButton}
                      className="text-xs h-7 px-2"
                    >
                      Submit
                    </Button>
                  </div>
                </div>
              )}

              {/* Display search result clusters if they exist */}
              {curSearchQuery && <ClusterViewer searchQuery={curSearchQuery} />}
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <div className="flex flex-wrap gap-1">
                  {PRESET_QUERIES.map((preset) => {
                    const IconComponent = preset.icon;
                    return (
                      <button
                        key={preset.id}
                        onClick={() => handleSelectPreset(preset.query)}
                        onMouseEnter={() => handlePresetHover(preset.query)}
                        onMouseLeave={handlePresetLeave}
                        className="inline-flex items-center gap-1.5 px-2 py-1 bg-background border border-border rounded-md text-xs font-medium text-primary disabled:opacity-50 hover:bg-secondary hover:border-border transition-colors"
                        disabled={!hasWritePermission}
                      >
                        <IconComponent className={`h-3 w-3 ${preset.color}`} />
                        {preset.label}
                      </button>
                    );
                  })}
                </div>
                <div className="flex items-center text-xs gap-2">
                  Stop after
                  <Input
                    value={maxResults ?? ''}
                    onChange={handleMaxResultsChange}
                    className="text-xs bg-background shadow-none font-mono rounded-sm w-[5rem] text-muted-foreground flex-1 h-7 px-1"
                    type="number"
                    min="0"
                  />
                  hits
                </div>
              </div>
              <div className="relative overflow-hidden rounded-md border bg-background focus-within:ring-1 focus-within:ring-ring">
                <fieldset>
                  <Textarea
                    className="h-[10rem] resize-none border-0 p-2 shadow-none focus-visible:ring-0 text-xs font-mono"
                    placeholder={placeholderText}
                    value={isPresetHovered ? '' : searchQueryTextboxValue}
                    onChange={(e) =>
                      dispatch(setSearchQueryTextboxValue(e.target.value))
                    }
                    onKeyDown={(
                      e: React.KeyboardEvent<HTMLTextAreaElement>
                    ) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSearch(searchQueryTextboxValue);
                      }
                    }}
                    disabled={!hasWritePermission}
                  />
                  <div className="flex items-center justify-end p-2">
                    <Button
                      type="button"
                      size="sm"
                      className="gap-1 h-7 text-xs"
                      onClick={() => handleSearch(searchQueryTextboxValue)}
                      disabled={
                        !hasWritePermission || !searchQueryTextboxValue?.trim()
                      }
                    >
                      Search
                      <CornerDownLeft className="size-3" />
                    </Button>
                  </div>
                </fieldset>
              </div>

              {/* Search History Section - Updated with consistent colors */}
              {searchesWithStats && searchesWithStats.length > 0 && (
                <div className="max-h-[20rem] overflow-y-auto pr-1">
                  <div className="flex justify-between mt-2 items-center mb-1">
                    <div className="text-xs font-medium text-primary">
                      Saved Searches
                    </div>
                  </div>
                  {searchesWithStats.map((search, index) => {
                    const completionPercentage =
                      search.num_total > 0
                        ? Math.min(
                            (search.num_judgments_computed / search.num_total) *
                              100,
                            100
                          )
                        : 0;
                    const isComplete = completionPercentage === 100;
                    // Extract first 8 characters of UUID for display
                    const shortDimId = search.search_id.split('-')[0];

                    const statusButton = {
                      running: (
                        <button
                          onClick={() => handleStopSearch(search.job.id)}
                          className="hover:bg-red-bg rounded p-0.5 text-red-text hover:text-primary  transition-colors"
                          title="Pause search"
                        >
                          <Pause className="h-3 w-3" />
                        </button>
                      ),
                      pending: (
                        <button
                          disabled
                          className="rounded p-0.5 text-primary-foreground transition-colors"
                        >
                          <Loader2 className="h-3 w-3 animate-spin" />
                        </button>
                      ),
                      completed: (
                        <button
                          disabled
                          className="rounded p-0.5 text-green-text transition-colors"
                        >
                          <Check className="h-3 w-3" />
                        </button>
                      ),
                      canceled: (
                        <button
                          onClick={() =>
                            resumeSearchFromHistory(search.search_query)
                          }
                          className="hover:bg-green-bg rounded p-0.5 text-green-text hover:text-green-foreground transition-colors"
                          title="Resume search"
                        >
                          <Play className="h-3 w-3" />
                        </button>
                      ),
                    };

                    return (
                      <div
                        key={index}
                        className="group mb-1 border border-border rounded hover:border-indigo-border hover:bg-indigo-bg transition-all"
                      >
                        <div className="flex items-center py-1.5 rounded px-2 text-xs bg-background">
                          <code
                            className="px-1 bg-secondary border border-border rounded text-[10px] text-muted-foreground mr-2 flex-shrink-0"
                            title={search.search_id}
                          >
                            {shortDimId}
                          </code>
                          <div
                            className="font-mono text-primary truncate flex-1 cursor-pointer"
                            title={search.search_query}
                            onClick={() => {
                              handleSearch(search.search_query);
                            }}
                          >
                            {search.search_query}
                          </div>
                          <div className="flex items-center ml-2 space-x-1.5 flex-shrink-0">
                            <div className="flex items-center gap-1.5 border-r pr-2">
                              <div
                                className="relative w-12 h-1.5 bg-secondary rounded-full overflow-hidden flex-shrink-0"
                                title={`${search.num_judgments_computed} of ${search.num_total} processed`}
                              >
                                <div
                                  className={`absolute top-0 left-0 h-full ${isComplete ? 'bg-indigo-500' : 'bg-blue-500'}`}
                                  style={{
                                    width: `${completionPercentage}%`,
                                  }}
                                ></div>
                              </div>
                              <span className="text-[11px] text-muted-foreground whitespace-nowrap">
                                {/* This is so jank but im proud of it */}
                                {Math.round(completionPercentage) < 100 && (
                                  <span className="text-transparent">_</span>
                                )}
                                {Math.round(completionPercentage)}% computed
                              </span>
                            </div>
                            {hasWritePermission && (
                              <>
                                {
                                  statusButton[
                                    search.job
                                      .status as keyof typeof statusButton
                                  ]
                                }
                                <button
                                  className="hover:bg-indigo-bg rounded p-0.5 text-indigo-text transition-colors"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    dispatch(
                                      setSearchQueryTextboxValue(
                                        search.search_query
                                      )
                                    );
                                    dispatch(clearSearch());
                                  }}
                                  title="Edit this search query"
                                >
                                  <Pencil className="h-3 w-3" />
                                </button>
                                <button
                                  className="hover:bg-red-bg rounded p-0.5 text-red-text transition-colors"
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    await dispatch(
                                      deleteSearch({
                                        searchQueryId: search.search_id,
                                        job: search.job,
                                      })
                                    )
                                      .unwrap()
                                      .then(() => {
                                        toast({
                                          title: 'Deleted saved search',
                                          description:
                                            'Your saved search has been deleted successfully',
                                          variant: 'default',
                                        });
                                      });
                                  }}
                                  title="Delete this saved search"
                                >
                                  <Trash className="h-3 w-3" />
                                </button>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Paired search */}
      {/* <div className="space-y-2">
        <div>
          <div className="text-sm font-semibold">Paired Search</div>
          <div className="text-xs">
            Compare pairs of agent runs for behavioral differences
          </div>
        </div>
        Not implemented yet
      </div> */}

      {/* Diffing */}
      {/* <DiffSelector /> */}
    </Card>
  );
};

export default SearchArea;
