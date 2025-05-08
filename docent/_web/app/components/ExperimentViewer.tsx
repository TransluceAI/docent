import React, {
  useMemo,
  useState,
  useEffect,
  useRef,
  useCallback,
} from 'react';
import { Card } from '@/components/ui/card';
import {
  ChevronDown,
  ChevronRight,
  Network,
  HelpCircle,
  Loader2,
} from 'lucide-react';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import InnerCard from './InnerCard';
import { useRouter, useSearchParams } from 'next/navigation';
import { cn } from '@/lib/utils';
import { AttributeFeedback } from '@/app/types/experimentViewerTypes';
import { Button } from '@/components/ui/button';
import { BASE_DOCENT_PATH } from '../constants';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import {
  addExpandedInner,
  addExpandedOuter,
  clearExpandedInner,
  clearExpandedOuter,
  removeExpandedInner,
  removeExpandedOuter,
  setExperimentViewerScrollPosition,
  setOrganizationMethod,
} from '../store/experimentViewerSlice';
import { OrganizationMethod } from '../types/experimentViewerTypes';
import { toast } from '@/hooks/use-toast';
import {
  clearAttributeQuery,
  clearVoteState,
  setAttributeQueryTextboxValue,
  submitAttributeFeedback,
} from '../store/attributeFinderSlice';

interface ExperimentViewerProps {
  onShowDatapoint?: (datapointId: string, blockId?: number) => void;
}

export default function ExperimentViewer({
  onShowDatapoint,
}: ExperimentViewerProps) {
  const dispatch = useAppDispatch();
  const router = useRouter();

  /**
   * Get state
   */

  const evalId = useAppSelector((state) => state.frame.evalId);
  const sampleDimId = useAppSelector((state) => state.frame.sampleDimId);
  const experimentDimId = useAppSelector(
    (state) => state.frame.experimentDimId
  );

  // Attributes
  const loadingAttributesForId = useAppSelector(
    (state) => state.attributeFinder.loadingAttributesForId
  );
  const curAttributeQuery = useAppSelector(
    (state) => state.attributeFinder.curAttributeQuery
  );
  const attributeMap = useAppSelector(
    (state) => state.attributeFinder.attributeMap
  );
  const voteState = useAppSelector((state) => state.attributeFinder.voteState);

  // UI state
  const expandedOuter = useAppSelector(
    (state) => state.experimentViewer.expandedOuter
  );
  const expandedInner = useAppSelector(
    (state) => state.experimentViewer.expandedInner
  );
  const organizationMethod = useAppSelector(
    (state) => state.experimentViewer.organizationMethod
  );
  const experimentViewerScrollPosition = useAppSelector(
    (state) => state.experimentViewer.experimentViewerScrollPosition
  );

  const experiments = useAppSelector(
    (state) => state.experimentViewer.experimentFilters
  );
  const experimentIds = useMemo(() => {
    if (!experiments) return [];
    return Object.keys(experiments);
  }, [experiments]);
  const samples = useAppSelector(
    (state) => state.experimentViewer.sampleFilters
  );
  const sampleIds = useMemo(() => {
    if (!samples) return [];
    return Object.keys(samples);
  }, [samples]);

  // Marginals
  const rawStatMarginals = useAppSelector(
    (state) => state.experimentViewer.statMarginals
  );
  const rawIdMarginals = useAppSelector(
    (state) => state.experimentViewer.idMarginals
  );
  const sampleStatMarginals = useAppSelector(
    (state) => state.experimentViewer.sampleStatMarginals
  );
  const experimentStatMarginals = useAppSelector(
    (state) => state.experimentViewer.experimentStatMarginals
  );
  const interventionDescriptionMarginals = useAppSelector(
    (state) => state.experimentViewer.interventionDescriptionMarginals
  );

  // Create a function to get the marginal key - safe to use even if data is null
  const getMarginalKey = useCallback(
    (sampleId: string | null, experimentId: string | null) => {
      if (sampleId !== null && experimentId !== null) {
        return `${sampleDimId},${sampleId}|${experimentDimId},${experimentId}`;
      } else if (sampleId !== null) {
        return `${sampleDimId},${sampleId}`;
      } else if (experimentId !== null) {
        return `${experimentDimId},${experimentId}`;
      } else {
        return '';
      }
    },
    [sampleDimId, experimentDimId]
  );

  /**
   * Deal with filtering by the attribute query
   */

  const idMarginals = useMemo(() => {
    if (!rawIdMarginals || !curAttributeQuery) return rawIdMarginals;

    // Filter the keys and their datapoints based on attribute query
    const filtered = Object.entries(rawIdMarginals).reduce(
      (result, [key, datapointsList]) => {
        // Filter datapoints to ones that have the attributes
        const filteredDatapoints = datapointsList.filter((datapointId) => {
          const attrs = attributeMap?.[datapointId]?.[curAttributeQuery];
          return attrs && attrs.length > 0;
        });

        // Only include keys that have at least one datapoint after filtering
        if (filteredDatapoints.length > 0) {
          result[key] = filteredDatapoints;
        }

        return result;
      },
      {} as typeof rawIdMarginals
    );

    return filtered;
  }, [rawIdMarginals, curAttributeQuery, attributeMap]);

  const statMarginals = useMemo(() => {
    if (!rawStatMarginals || !curAttributeQuery) return rawStatMarginals;
    return Object.fromEntries(
      Object.entries(rawStatMarginals).filter(([key, _]) => {
        return idMarginals && key in idMarginals;
      })
    );
  }, [rawStatMarginals, curAttributeQuery, idMarginals]);

  // For each experiment, get the samples that have non-null stats
  const samplesByExperiment = useMemo(() => {
    const validMap = new Map<string, string[]>();
    if (!statMarginals || !experiments || !samples) return validMap;

    experimentIds.forEach((expId) => {
      const validSamples = sampleIds.filter((sampleId) => {
        const stats = statMarginals[getMarginalKey(sampleId, expId)];
        return (
          stats &&
          Object.keys(stats).length > 0 &&
          Object.values(stats)[0]?.n > 0
        );
      });
      validMap.set(expId, validSamples);
    });

    return validMap;
  }, [experimentIds, sampleIds, statMarginals, getMarginalKey]);

  // For each sample, get the experiments that have non-null stats
  const experimentsBySample = useMemo(() => {
    const validMap = new Map<string, string[]>();
    if (!statMarginals || !experiments || !samples) return validMap;

    sampleIds.forEach((sampleId) => {
      const validExperiments = experimentIds.filter((expId) => {
        const stats = statMarginals[getMarginalKey(sampleId, expId)];
        return (
          stats &&
          Object.keys(stats).length > 0 &&
          Object.values(stats)[0]?.n > 0
        );
      });
      validMap.set(sampleId, validExperiments);
    });

    return validMap;
  }, [experimentIds, sampleIds, statMarginals, getMarginalKey]);

  /**
   * Handle feedback
   */

  const attributeFeedback = useMemo(() => {
    if (!voteState) return [];
    return Object.entries(voteState).flatMap(([datapoint_id, attributes]) =>
      Object.entries(attributes).map(
        ([attribute, vote]) =>
          ({
            attribute,
            vote,
          }) as AttributeFeedback
      )
    );
  }, [voteState]);
  const [missingQueries, setMissingQueries] = useState<string>('');

  const [waitingOnNewQuery, setWaitingOnNewQuery] = useState(false);

  const handleFeedbackSubmit = useCallback(async () => {
    if (!curAttributeQuery) return;
    if (attributeFeedback.length === 0 && !missingQueries) {
      toast({
        title: 'No feedback provided',
        description: 'Please provide feedback',
        variant: 'destructive',
      });
      return;
    }

    toast({
      title: 'Feedback submitted',
      description: "We're recomputing the search results with your feedback...",
    });
    setWaitingOnNewQuery(true);

    try {
      const result = await dispatch(
        submitAttributeFeedback({
          originalQuery: curAttributeQuery,
          feedback: attributeFeedback,
          missingQueries,
        })
      ).unwrap();

      // Update the curAttributeQuery
      dispatch(clearAttributeQuery());
      dispatch(setAttributeQueryTextboxValue(result));

      // Reset feedback state
      dispatch(clearVoteState());
      setMissingQueries('');
    } finally {
      setWaitingOnNewQuery(false);
    }
  }, [curAttributeQuery, attributeFeedback, missingQueries, dispatch]);

  /**
   * Handle toggling of outer and inner panels
   */

  // Get first item so we can expand it
  const getFirstItem = useCallback(
    (mode: OrganizationMethod) => {
      const items = mode === 'experiment' ? experimentIds : sampleIds;
      return items && items.length > 0 ? items[0] : null;
    },
    [experimentIds, sampleIds]
  );

  // Handle organization mode change
  const handleOrganizationModeChange = useCallback(
    (value: OrganizationMethod) => {
      dispatch(setOrganizationMethod(value));

      // Clear expansion states
      dispatch(clearExpandedOuter());
      dispatch(clearExpandedInner());

      // Auto-expand the first item
      const firstItem = getFirstItem(value);
      if (firstItem) {
        dispatch(addExpandedOuter(firstItem));
      }
    },
    [getFirstItem, dispatch]
  );

  const toggleOuter = (outerId: string) => {
    // First determine whether to add or remove; prevents double-toggling in StrictMode
    const isCurrentlyExpanded = expandedOuter?.[outerId] ?? false;
    const actionToTake = !isCurrentlyExpanded;

    if (actionToTake) {
      dispatch(addExpandedOuter(outerId));
    } else {
      dispatch(removeExpandedOuter(outerId));
    }
  };

  const toggleInner = (outerId: string, innerId: string) => {
    // First determine whether to add or remove; prevents double-toggling in StrictMode
    const isCurrentlyExpanded = expandedInner?.[outerId]?.[innerId] ?? false;
    const actionToTake = !isCurrentlyExpanded;

    // Update the expandedInner state
    if (actionToTake) {
      dispatch(addExpandedInner({ outerId, innerId }));
    } else {
      dispatch(removeExpandedInner({ outerId, innerId }));
    }
  };

  // Initialize expanded state when component mounts or dependencies change
  const alreadyExpanded = useRef(false); // If a user clicks, it should still be reactive; this gets reset when there is a refresh of samples/exps
  useEffect(() => {
    if (alreadyExpanded.current) return;

    const firstItem = getFirstItem(organizationMethod);
    if (
      firstItem &&
      (expandedOuter === undefined || Object.keys(expandedOuter).length === 0)
    ) {
      dispatch(addExpandedOuter(firstItem));
    }
    alreadyExpanded.current = true;
  }, [getFirstItem, organizationMethod, dispatch, expandedOuter]);

  // When the samples or experiments change, we need to clear the expansion states
  useEffect(() => {
    alreadyExpanded.current = false;
    dispatch(clearExpandedOuter());
    dispatch(clearExpandedInner());
  }, [sampleIds, experimentIds, dispatch]);

  /**
   * Scrolling
   */

  // Create refs for outer items to enable scrolling to specific items
  const itemRefs = useRef<Record<string, HTMLDivElement | null>>({});
  // Create a ref for the container to track scroll position
  const containerRef = useRef<HTMLDivElement>(null);

  // Save scroll position when user scrolls
  useEffect(() => {
    const handleScroll = () => {
      if (containerRef.current) {
        dispatch(
          setExperimentViewerScrollPosition(containerRef.current.scrollTop)
        );
      }
    };

    const container = containerRef.current;
    if (container) {
      container.addEventListener('scroll', handleScroll);
      return () => {
        container.removeEventListener('scroll', handleScroll);
      };
    }
  }, [dispatch]);

  // Restore scroll position when component mounts or when experimentViewerScrollPosition changes
  useEffect(() => {
    if (containerRef.current && experimentViewerScrollPosition) {
      containerRef.current.scrollTop = experimentViewerScrollPosition;
    }
  }, [experimentViewerScrollPosition]);

  /**
   * Construct options that determine the order in which data is displayed
   */

  const getColorForAccuracy = (accuracy: number) => {
    if (accuracy >= 0.8) return 'bg-green-100 text-green-800';
    if (accuracy > 0.0) return 'bg-yellow-100 text-yellow-800';
    return 'bg-red-100 text-red-800';
  };

  const formatAccuracy = (value: number) => `${value.toFixed(2)}`;

  // Common card styles for both organization methods
  const getCardStyles = (isExpanded: boolean) =>
    `p-2 rounded-md shadow-none transition-all duration-200 ${
      isExpanded ? 'border-blue-200' : 'border-gray-200'
    }`;

  // Get the appropriate data based on organization method
  const {
    outerFilters,
    innerFilters,
    outerFilterIds,
    outerAverages,
    innerMap,
    outerLabel,
    innerLabel,
    outerPrefix,
    getOuterKey,
  } = useMemo(() => {
    if (organizationMethod === 'experiment') {
      return {
        outerFilters: experiments,
        innerFilters: samples,
        outerFilterIds: experimentIds.filter(
          (expId) => (samplesByExperiment.get(expId)?.length ?? 0) > 0
        ),
        outerAverages: !curAttributeQuery ? experimentStatMarginals : undefined, // Only show stats if not filtering
        getOuterKey: (outerId: string) => getMarginalKey(null, outerId),
        innerMap: samplesByExperiment,
        outerLabel: 'Experiment',
        innerLabel: 'task',
        outerPrefix: '',
      };
    } else {
      return {
        outerFilters: samples,
        innerFilters: experiments,
        outerFilterIds: sampleIds.filter(
          (sampleId) => (experimentsBySample.get(sampleId)?.length ?? 0) > 0
        ),
        outerAverages: !curAttributeQuery ? sampleStatMarginals : undefined, // Only show stats if not filtering
        innerMap: experimentsBySample,
        getOuterKey: (outerId: string) => getMarginalKey(outerId, null),
        outerLabel: 'Task',
        innerLabel: 'experiment',
        outerPrefix: '',
      };
    }
  }, [
    organizationMethod,
    experiments,
    samples,
    curAttributeQuery,
    experimentStatMarginals,
    sampleStatMarginals,
    getMarginalKey,
    samplesByExperiment,
    experimentsBySample,
    evalId,
  ]);

  // If data isn't available, show a loading spinner
  if (!statMarginals || !idMarginals) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center space-y-2 h-full">
        <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full space-y-2">
      {/* Header with organization dropdown */}
      <div className="flex justify-between items-center">
        <div>
          <div className="text-sm font-semibold">
            Experiment Viewer
            <span className="text-xxs text-gray-500 font-light ml-2">
              {experimentIds.length} experiment
              {experimentIds.length === 1 ? '' : 's'}
            </span>
          </div>
          <div className="text-xs">Compare agent performance across runs.</div>
        </div>
        <div className="flex items-center space-x-1.5">
          <span className="text-xs text-gray-500">Organize by:</span>
          <Select
            value={organizationMethod}
            onValueChange={handleOrganizationModeChange}
          >
            <SelectTrigger className="h-6 w-24 text-xs border-gray-200 bg-transparent hover:bg-gray-50 px-2 font-normal">
              <SelectValue placeholder="Organization" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="experiment" className="text-xs">
                Experiment
              </SelectItem>
              <SelectItem value="sample" className="text-xs">
                Task
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Hint for refining search queries */}
      {curAttributeQuery && (
        <div className="text-xs text-indigo-800 italic flex items-center justify-between gap-1.5 p-1.5 rounded-md border border-indigo-100">
          {waitingOnNewQuery ? (
            <div className="flex items-center justify-between w-full">
              <span>Search query is being refined with your feedback...</span>
            </div>
          ) : (
            <div className="flex items-center justify-between w-full">
              <input
                type="text"
                placeholder="Relevant queries that are entirely missing from the search results"
                className="text-xs px-2 py-1 border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500 w-[400px]"
                value={missingQueries}
                onChange={(e) => setMissingQueries(e.target.value)}
              />
              <Button
                variant="ghost"
                size="sm"
                className="text-xs text-green-600 hover:text-green-800"
                onClick={handleFeedbackSubmit}
              >
                Submit feedback
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Content area */}
      <ScrollArea className="text-sm" containerRef={containerRef}>
        <div className="space-y-2">
          {outerFilterIds?.map((outerId, index) => (
            <Card
              key={index}
              className={cn(
                getCardStyles(expandedOuter?.[outerId] ?? false),
                'space-y-2'
              )}
              ref={(el: HTMLDivElement | null) => {
                itemRefs.current[outerId] = el;
              }}
            >
              <div
                className="flex items-center justify-between cursor-pointer group"
                onClick={() => toggleOuter(outerId)}
              >
                <div className="flex items-center">
                  {expandedOuter?.[outerId] ? (
                    <ChevronDown className="h-4 w-4 mr-1.5 text-blue-500" />
                  ) : (
                    <ChevronRight className="h-4 w-4 mr-1.5 text-gray-400 group-hover:text-gray-600" />
                  )}
                  <div className="flex items-center">
                    <div>
                      <p className="text-sm font-semibold text-gray-800">
                        {outerLabel}{' '}
                        <span className="font-mono">
                          {outerPrefix}
                          {outerFilters?.[outerId]?.name || outerId}
                        </span>
                        <span className="text-xxs text-gray-500 font-light ml-2">
                          {innerMap.get(outerId)?.length || 0} {innerLabel}
                          {innerMap.get(outerId)?.length === 1 ? '' : 's'}
                        </span>
                      </p>
                      {organizationMethod === 'experiment' &&
                        interventionDescriptionMarginals &&
                        interventionDescriptionMarginals[
                          getOuterKey(outerId)
                        ] &&
                        interventionDescriptionMarginals[getOuterKey(outerId)]
                          .length > 0 && (
                          <p className="text-xs italic text-gray-600 mt-0.5">
                            {
                              interventionDescriptionMarginals[
                                getOuterKey(outerId)
                              ][0]
                            }
                          </p>
                        )}
                    </div>
                    {/* {organizationMethod === 'sample' &&
                      (experimentsBySample.get(outerId)?.length ?? 0) > 1 && (
                        <button
                          className="ml-2 text-gray-400 hover:text-blue-500 flex items-center text-[10px] transition-colors"
                          onClick={(e) => {
                            e.stopPropagation();
                            router.push(
                              `${BASE_DOCENT_PATH}/${evalId}/forest/${outerId}`
                            );
                          }}
                          title="View experiment tree"
                        >
                          <Network className="h-3 w-3" />
                        </button>
                      )} */}
                  </div>
                </div>
                {outerAverages && outerAverages[getOuterKey(outerId)] && (
                  <div className="flex flex-row flex-wrap gap-2 font-mono">
                    {Object.entries(
                      outerAverages[getOuterKey(outerId)] || {}
                    ).map(([scoreKey, stats], idx, arr) => {
                      const isLoading =
                        !stats || stats.mean === null || stats.ci === null;
                      return (
                        <React.Fragment key={scoreKey}>
                          <div className="inline-flex items-center gap-1">
                            <>
                              <span className="text-[10px] text-gray-400 font-normal">
                                {scoreKey}:
                              </span>
                              <div
                                className={`px-1.5 py-0.5 rounded-sm text-xs font-medium ${
                                  isLoading
                                    ? 'bg-gray-100 text-gray-600'
                                    : getColorForAccuracy(stats.mean!)
                                }`}
                              >
                                {isLoading ? (
                                  '--'
                                ) : (
                                  <>{formatAccuracy(stats.mean!)}</>
                                )}
                              </div>
                            </>
                          </div>
                          {idx === arr.length - 1 && (
                            <span className="text-gray-500 text-[11px]">
                              n={stats.n}
                            </span>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </div>
                )}
              </div>

              {expandedOuter?.[outerId] && (
                <div className="space-y-1.5 mt-2 pl-5">
                  {innerMap.get(outerId)?.map((innerId) => {
                    const sampleId =
                      organizationMethod === 'experiment' ? innerId : outerId;
                    const expId =
                      organizationMethod === 'experiment' ? outerId : innerId;

                    return (
                      <InnerCard
                        key={innerId}
                        innerId={innerId}
                        innerName={innerFilters?.[innerId]?.name || innerId}
                        organizationMethod={organizationMethod}
                        stats={statMarginals[getMarginalKey(sampleId, expId)]}
                        datapointIds={
                          idMarginals?.[getMarginalKey(sampleId, expId)] || []
                        }
                        onShowDatapoint={onShowDatapoint}
                        isExpanded={
                          expandedInner?.[outerId]?.[innerId] ?? false
                        }
                        onToggle={() => toggleInner(outerId, innerId)}
                        experimentCount={
                          organizationMethod === 'experiment'
                            ? (experimentsBySample.get(innerId)?.length ?? 0)
                            : undefined
                        }
                      />
                    );
                  })}
                </div>
              )}
            </Card>
          ))}
          {outerFilterIds?.length === 0 && (
            <div className="text-xs text-gray-500">
              {loadingAttributesForId ? (
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
      </ScrollArea>
    </div>
  );
}
