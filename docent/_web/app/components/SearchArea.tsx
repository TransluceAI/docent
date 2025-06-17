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
  XOctagon,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { toast } from '@/hooks/use-toast';

import { addSearchDimension, deleteSearch } from '../store/frameSlice';
import { useAppDispatch } from '../store/hooks';
import {
  clearSearch,
  computeSearch,
  getExistingClusters,
  requestClusters,
  setSearchQueryTextboxValue,
} from '../store/searchSlice';
import { RootState } from '../store/store';

import BinEditor from './BinEditor';
import { ProgressBar } from './ProgressBar';
import { requestDiffs } from '../store/diffSlice';
import { TranscriptFilterControls } from './TranscriptFilterControls';

// Preset search queries with custom icons
const PRESET_QUERIES = [
  {
    id: 'env',
    label: 'Environment issues',
    query: 'potential issues with the environment the agent is operating in',
    icon: Earth,
  },
  {
    id: 'strange',
    label: 'Strange behaviors',
    query: 'cases where the agent acted in a strange or unexpected way',
    icon: HelpCircle,
  },
  {
    id: 'unfollow',
    label: 'Not following instructions',
    query:
      'cases where the agent did not follow instructions given to it or directly disobeyed them',
    icon: AlertTriangle,
  },
];

const DEFAULT_PLACEHOLDER_TEXT =
  "Describe what you're looking for in detail, or try a sample preset above";

const SearchArea = () => {
  const dispatch = useAppDispatch();
  const router = useRouter();

  const { frameGridId, marginals, dimensionsMap } = useSelector(
    (state: RootState) => state.frame
  );
  const {
    curSearchQuery,
    activeClusterTaskId,
    loadingSearchQuery,
    loadingProgress,
    searchesWithStats,
    searchQueryTextboxValue,
  } = useSelector((state: RootState) => state.search);
  const { diffLoadingProgress } = useSelector((state: RootState) => state.diff);

  // Pull out the dimension associated with the current search query
  const activeDim = useMemo(() => {
    if (!curSearchQuery || !dimensionsMap) return undefined;
    return Object.values(dimensionsMap).find(
      (dim) => dim.search_query === curSearchQuery
    );
  }, [dimensionsMap, curSearchQuery]);

  useEffect(() => {
    if (activeDim && activeDim.bins && activeDim.bins.length > 0) {
      if (marginals == null && activeClusterTaskId == null) {
        // if we have bins for a search result and no ongoing clustering task, then we've already
        // computed the marginals in an earlier query and just need to request them
        dispatch(getExistingClusters({ dimensionId: activeDim.id}));
      }
    }
  }, [activeDim, marginals, dispatch, activeClusterTaskId]);

  /**
   * Local state for UI components
   */

  // Search box hints
  const [placeholderText, setPlaceholderText] = useState(
    DEFAULT_PLACEHOLDER_TEXT
  );
  // Cluster feedback
  const [clusterFeedback, setClusterFeedback] = useState('');
  const [showFeedbackInput, setShowFeedbackInput] = useState(false);
  const [experimentId1, setExperimentId1] = useState('');
  const [experimentId2, setExperimentId2] = useState('');
  const [loadingDiffs, setLoadingDiffs] = useState(false);
  const [diffsAttribute, setDiffsAttribute] = useState<string | null>(null);

  const handleClearSearch = useCallback(() => {
    if (curSearchQuery) {
      dispatch(setSearchQueryTextboxValue(curSearchQuery || ''));
      dispatch(clearSearch());
    }
  }, [curSearchQuery, dispatch]);

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

    // Reset form
    dispatch(setSearchQueryTextboxValue(''));

    // Search
    const trimmedQuery = query.trim();
    dispatch(computeSearch({ searchQuery: trimmedQuery }));
  };

  const handleRequestClusters = async () => {
    let dimId: string;
    if (!activeDim) {
      if (!curSearchQuery) {
        toast({
          title: 'Could not cluster data',
          description: 'Could not find curSearchQuery',
          variant: 'destructive',
        });
        return;
      }
      dimId = await dispatch(addSearchDimension(curSearchQuery)).unwrap();
    } else {
      dimId = activeDim.id;
    }

    // If bins exist and feedback is not being shown yet, show the feedback input
    if (
      activeDim &&
      activeDim.bins &&
      activeDim.bins.length > 0 &&
      !showFeedbackInput
    ) {
      setShowFeedbackInput(true);
      return;
    }
    // Use the context's requestClusters function
    dispatch(
      requestClusters({ dimensionId: dimId, feedback: clusterFeedback })
    );
    // Clear feedback after sending and hide the input
    setShowFeedbackInput(false);
  };

  const handleCancelFeedback = () => {
    setShowFeedbackInput(false);
    setClusterFeedback('');
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

  const handleRequestDiffs = async () => {
    if (!experimentId1 || !experimentId2) {
      toast({
        title: 'Missing experiment IDs',
        description: 'Please enter both experiment IDs',
        variant: 'destructive',
      });
      return;
    }

    setLoadingDiffs(true);
    const { payload: diffsReportId } = await dispatch(
      requestDiffs({
        experimentId1,
        experimentId2,
      })
    );

    setLoadingDiffs(false);
    // Set the diffs attribute to enable clustering
    setDiffsAttribute('diffs');
    // Navigate to the diff reports page
    router.push(
      `/dashboard/${frameGridId}/diffs_reports?diffsReportId=${diffsReportId}`
    );
  };

  const handleCancelDiffs = () => {
    setLoadingDiffs(false);
    setDiffsAttribute(null);
  };

  /**
   * Handle share button
   */
  const handleShare = (searchQuery: string) => {
    navigator.clipboard
      .writeText(`${window.location.href}?searchQuery=${searchQuery}`)
      .then(() => {
        toast({
          title: 'Search URL copied',
          description: 'Copied a shareable link to the clipboard',
          variant: 'default',
        });
      })
      .catch(() => {
        toast({
          title: 'Failed to copy',
          description: 'Could not copy to clipboard',
          variant: 'destructive',
        });
      });
  };

  return (
    <Card className="h-full flex overflow-y-auto flex-col flex-1 p-3">
      <div className="space-y-4">
        <TranscriptFilterControls />
        <div className="border-t" />
        <div className="space-y-2">
          <div>
            <div className="text-sm font-semibold">Compare Experiments</div>
            <div className="text-xs">
              Compare results between two different experiment runs.
            </div>
          </div>

          <div className="border rounded-md bg-gray-50 p-2 space-y-2">
            {!loadingDiffs && !diffsAttribute ? (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <div className="text-xs text-gray-600">Experiment 1</div>
                    <Input
                      value={experimentId1}
                      onChange={(e) => setExperimentId1(e.target.value)}
                      placeholder="e.g. experiment-1"
                      className="h-8 text-xs bg-white font-mono text-gray-600"
                    />
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs text-gray-600">Experiment 2</div>
                    <Input
                      value={experimentId2}
                      onChange={(e) => setExperimentId2(e.target.value)}
                      placeholder="e.g. experiment-2"
                      className="h-8 text-xs bg-white font-mono text-gray-600"
                    />
                  </div>
                </div>
                <Button
                  size="sm"
                  className="text-xs w-full"
                  onClick={handleRequestDiffs}
                  disabled={!experimentId1 || !experimentId2}
                >
                  Compare Experiments
                </Button>
              </>
            ) : loadingDiffs ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="text-xs text-gray-600">Loading diffs...</div>
                  <button
                    onClick={handleCancelDiffs}
                    className="inline-flex items-center gap-x-1 text-xs bg-red-50 text-red-500 border border-red-100 px-1.5 py-0.5 rounded-md hover:bg-red-100 transition-colors"
                  >
                    <RefreshCw className="h-3 w-3 mr" />
                    Clear
                  </button>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-1.5">
                  <div className="bg-blue-600 h-1.5 rounded-full animate-pulse"></div>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="text-xs text-gray-600">
                    Comparison between experiments
                    <span className="font-mono whitespace-pre-wrap text-indigo-800">
                      &nbsp;{experimentId1}&nbsp;
                    </span>
                    and
                    <span className="font-mono whitespace-pre-wrap text-indigo-800">
                      &nbsp;{experimentId2}&nbsp;
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleCancelDiffs}
                      className="text-xs"
                    >
                      Clear
                    </Button>
                  </div>
                </div>
                {diffLoadingProgress &&
                  diffLoadingProgress[0] !== diffLoadingProgress[1] && (
                    <ProgressBar
                      current={diffLoadingProgress[0]}
                      total={diffLoadingProgress[1]}
                    />
                  )}
              </div>
            )}
          </div>
        </div>
        <div className="border-t" />
        <div className="space-y-2">
          <div>
            <div className="text-sm font-semibold">Global Search</div>
            <div className="text-xs">
              Look for patterns, errors, or other interesting phenomena in the
              transcripts.
            </div>
          </div>

          <div className="border rounded-md bg-gray-50 p-2 space-y-1">
            <div className="flex items-center justify-between text-xs">
              <div className="text-gray-600">Search query</div>
              {loadingProgress && !loadingSearchQuery && (
                <div className="text-gray-400">
                  {loadingProgress[0]} searches finished
                  {loadingProgress[1] - loadingProgress[0] > 0 && (
                    <>
                      , {loadingProgress[1] - loadingProgress[0]} had API issues{' '}
                      <span
                        className="cursor-pointer text-indigo-500 hover:text-indigo-600"
                        onClick={() => handleSearch(curSearchQuery)}
                      >
                        (retry)
                      </span>
                    </>
                  )}
                </div>
              )}
            </div>
            {curSearchQuery ? (
              <div className="space-y-2">
                <div className="flex items-center">
                  <div className="flex-1">
                    <div className="px-2 py-1 bg-indigo-50 border border-indigo-100 rounded text-xs font-mono whitespace-pre-wrap text-indigo-800">
                      {curSearchQuery}
                    </div>
                  </div>
                  <div className="flex flex-col xl:flex-row ml-2 space-y-1 xl:space-y-0 xl:space-x-1">
                    <button
                      onClick={() => handleShare(curSearchQuery)}
                      className="inline-flex items-center gap-x-1 text-xs bg-blue-50 text-blue-500 border border-blue-100 px-1.5 py-0.5 rounded-md hover:bg-blue-100 transition-colors"
                      title="Share this search"
                    >
                      <Share2 className="h-3 w-3" />
                      Share
                    </button>
                    <button
                      onClick={() => handleClearSearch()}
                      className="inline-flex items-center gap-x-1 text-xs bg-red-50 text-red-500 border border-red-100 px-1.5 py-0.5 rounded-md hover:bg-red-100 transition-colors"
                    >
                      <RefreshCw className="h-3 w-3 mr" />
                      Clear
                    </button>
                  </div>
                </div>

                {/* Progress bar for updates */}
                {loadingSearchQuery &&
                  loadingSearchQuery === curSearchQuery &&
                  loadingProgress && (
                    <ProgressBar
                      current={loadingProgress[0]}
                      total={loadingProgress[1]}
                    />
                  )}
                <Button
                  size="sm"
                  variant="outline"
                  className="text-xs w-full"
                  onClick={handleRequestClusters}
                  disabled={
                    !frameGridId ||
                    // Already loading clusters or marginals
                    (activeDim &&
                      (activeDim.loading_clusters ||
                        activeDim.loading_marginals)) ||
                    // Already clustering
                    activeClusterTaskId !== undefined ||
                    // Loading a search currently
                    loadingSearchQuery !== undefined ||
                    // Disable button when feedback input is visible
                    showFeedbackInput
                  }
                >
                  {activeDim && activeDim.loading_clusters ? (
                    <Loader2 className="h-3 w-3 mr-2 animate-spin" />
                  ) : (
                    <Sparkles className="h-3 w-3 mr-2" />
                  )}
                  {activeDim && activeDim.bins && activeDim.bins.length > 0
                    ? 'Re-cluster with feedback'
                    : 'Cluster matching results'}
                </Button>

                {/* Feedback input for re-clustering - only show when requested */}
                {showFeedbackInput && (
                  <div className="mt-1.5 space-y-0.5">
                    <div className="text-xs text-gray-600 mb-0.5">
                      Feedback for re-clustering
                    </div>
                    <div className="flex space-x-1 items-center">
                      <Input
                        autoFocus
                        value={clusterFeedback}
                        onChange={(e) => setClusterFeedback(e.target.value)}
                        placeholder="Describe how clusters should be improved..."
                        className="text-xs bg-white font-mono text-gray-600 flex-1 h-7"
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            handleRequestClusters();
                          }
                        }}
                      />
                      <Button
                        size="sm"
                        onClick={handleRequestClusters}
                        className="text-xs h-7 px-2"
                      >
                        Submit
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={handleCancelFeedback}
                        className="text-xs h-7 px-2"
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}

                {/* Display bins if they exist */}
                {activeDim && activeDim.bins && activeDim.bins.length > 0 && (
                  <div className="space-y-2 mt-3">
                    <div className="text-xs text-gray-600 font-medium">
                      Clusters
                    </div>
                    {activeDim.bins.map((bin) => (
                      <BinEditor
                        key={bin.id}
                        bin={bin}
                        loading={activeDim.loading_marginals || false}
                        marginalJudgments={
                          marginals?.[activeDim.id]?.[bin.id] || undefined
                        }
                      />
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <>
                <div className="flex flex-wrap gap-2">
                  {PRESET_QUERIES.map((preset) => {
                    const IconComponent = preset.icon;
                    return (
                      <button
                        key={preset.id}
                        onClick={() => handleSelectPreset(preset.query)}
                        onMouseEnter={() => handlePresetHover(preset.query)}
                        onMouseLeave={handlePresetLeave}
                        className="inline-flex items-center gap-1.5 px-2 py-1 bg-white border border-gray-200 rounded-full text-xs font-medium text-gray-700 hover:bg-gray-50 hover:border-gray-300 transition-colors"
                      >
                        <IconComponent className="h-3 w-3 text-blue-500" />
                        {preset.label}
                      </button>
                    );
                  })}
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
                    />
                    <div className="flex items-center justify-end p-2">
                      <Button
                        type="button"
                        size="sm"
                        className="gap-1 h-8 text-xs"
                        onClick={() => handleSearch(searchQueryTextboxValue)}
                        disabled={!searchQueryTextboxValue?.trim()}
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
                    <div className="flex justify-between items-center mb-1">
                      <div className="text-xs font-medium text-gray-500">
                        Saved Searches
                      </div>
                    </div>
                    {searchesWithStats.map((search, index) => {
                      const completionPercentage =
                        search.num_total > 0
                          ? Math.min(
                              (search.num_judgments_computed /
                                search.num_total) *
                                100,
                              100
                            )
                          : 0;
                      const isComplete = completionPercentage === 100;
                      // Extract first 8 characters of UUID for display
                      const shortDimId = search.search_id.split('-')[0];

                      return (
                        <div
                          key={index}
                          className="group mb-1 border border-gray-100 rounded hover:border-indigo-300 hover:bg-indigo-50 transition-all"
                        >
                          <div className="flex items-center py-1.5 px-2 text-xs bg-white">
                            <code
                              className="px-1 bg-gray-50 border border-gray-100 rounded text-[10px] text-gray-500 mr-2 flex-shrink-0"
                              title={search.search_id}
                            >
                              {shortDimId}
                            </code>
                            <div
                              className="font-mono text-gray-800 truncate flex-1 cursor-pointer"
                              title={search.search_query}
                              onClick={() => {
                                handleSearch(search.search_query);
                              }}
                            >
                              {search.search_query}
                            </div>
                            <div className="flex items-center ml-2 space-x-1.5 flex-shrink-0">
                              <div className="flex items-center gap-1.5">
                                <div
                                  className="relative w-12 h-1.5 bg-gray-100 rounded-full overflow-hidden flex-shrink-0"
                                  title={`${search.num_judgments_computed} of ${search.num_total} processed`}
                                >
                                  <div
                                    className={`absolute top-0 left-0 h-full ${isComplete ? 'bg-indigo-500' : 'bg-blue-500'}`}
                                    style={{
                                      width: `${completionPercentage}%`,
                                    }}
                                  ></div>
                                </div>
                                <span className="text-[9px] text-gray-500 whitespace-nowrap">
                                  {Math.round(completionPercentage)}% computed
                                </span>
                              </div>
                              <button
                                className="hover:bg-indigo-50 rounded p-0.5 text-indigo-400 hover:text-indigo-600 transition-colors"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleShare(search.search_query);
                                }}
                                title="Share this search"
                              >
                                <Share2 className="h-3 w-3" />
                              </button>
                              <button
                                className="hover:bg-indigo-50 rounded p-0.5 text-indigo-400 hover:text-indigo-600 transition-colors"
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
                                className="hover:bg-red-50 rounded p-0.5 text-red-400 hover:text-red-600 transition-colors"
                                onClick={async (e) => {
                                  e.stopPropagation();
                                  await dispatch(deleteSearch(search.search_id))
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
                                <XOctagon className="h-3 w-3" />
                              </button>
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
      </div>
    </Card>
  );
};

export default SearchArea;
