import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import React, {
  useMemo,
  useState,
  useEffect,
  useRef,
  useCallback,
} from 'react';

import { Card } from '@/components/ui/card';
import { useDebounce } from '@/hooks/use-debounce';
import { cn } from '@/lib/utils';





import {
  addExpandedInner,
  addExpandedOuter,
  removeExpandedInner,
  removeExpandedOuter,
  setExperimentViewerScrollPosition,
} from '../store/experimentViewerSlice';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { PrimitiveFilter } from '../types/frameTypes';

import DimensionSelector from './DimensionSelector';
import InnerCard from './InnerCard';

interface ExperimentViewerProps {
  onShowAgentRun?: (agentRunId: string, blockId?: number, blockId2?: number, paired?: boolean) => void;
}

export default function ExperimentViewer({
  onShowAgentRun,
}: ExperimentViewerProps) {
  const dispatch = useAppDispatch();

  /**
   * Get state
   */

  const { innerDimId, outerDimId, dimensionsMap } = useAppSelector(
    (state) => state.frame
  );

  // Attributes
  const {
    diffMap,
    loadingSearchQuery,
    curSearchQuery,
    searchResultMap: attributeMap,
    // voteState,
  } = useAppSelector((state) => state.search);

  const {
    expandedOuter,
    expandedInner,
    experimentViewerScrollPosition,
    dimIdsToFilterIds,
    filtersMap,
  } = useAppSelector((state) => state.experimentViewer);

  // Assemble maps of the inner and outer filters
  const outerFilters = useMemo(() => {
    if (!outerDimId || !filtersMap) return undefined;
    return dimIdsToFilterIds?.[outerDimId]?.reduce(
      (acc, filter_id) => {
        acc[filter_id] = filtersMap[filter_id];
        return acc;
      },
      {} as Record<string, PrimitiveFilter>
    );
  }, [outerDimId, filtersMap, dimIdsToFilterIds]);
  const innerFilters = useMemo(() => {
    if (!innerDimId || !filtersMap) return undefined;
    return dimIdsToFilterIds?.[innerDimId]?.reduce(
      (acc, filter_id) => {
        acc[filter_id] = filtersMap[filter_id];
        return acc;
      },
      {} as Record<string, PrimitiveFilter>
    );
  }, [innerDimId, filtersMap, dimIdsToFilterIds]);

  const outerFilterIds = useMemo(() => {
    if (!outerFilters) return [];
    return Object.keys(outerFilters);
  }, [outerFilters]);

  const innerFilterIds = useMemo(() => {
    if (!innerFilters) return [];
    return Object.keys(innerFilters);
  }, [innerFilters]);

  // Marginals
  const {
    statMarginals: rawStatMarginals,
    idMarginals: rawIdMarginals,
    outerStatMarginals,
  } = useAppSelector((state) => state.experimentViewer);

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

  /**
   * Deal with filtering by the attribute query and diff results
   */

  // Filter to IDs to ones that have the attribute query
  const idMarginals = useMemo(() => {
    if (!rawIdMarginals) return rawIdMarginals;
    if (!curSearchQuery && !diffMap) return rawIdMarginals;

    // Filter the keys and their datapoints based on attribute query or diff results
    const filtered = Object.entries(rawIdMarginals).reduce(
      (result, [key, datapointsList]) => {
        // Filter datapoints to ones that have the attributes and/or diff results
        const filteredAgentRuns = datapointsList.filter((datapointId) => {
          // Check for attributes if there's an active attribute query

          if (curSearchQuery) {
            const attrs = attributeMap?.[datapointId]?.[curSearchQuery];
            return attrs && attrs.length && attrs[0].value !== null;
          }

          // Check for diff results if there's an active diff query
          let hasDiffResults = true;
          if (diffMap) {
            hasDiffResults = Object.keys(diffMap).some((key) => {
              const [id1, id2] = key.split('___');
              return id1 === datapointId || id2 === datapointId;
            });
          }

          return hasDiffResults;
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
  }, [rawIdMarginals, curSearchQuery, attributeMap, diffMap]);

  // Only keep stat marginals that have datapoints, after filtering by attribute query
  const statMarginals = useMemo(() => {
    if (!rawStatMarginals) return rawStatMarginals;
    if (!curSearchQuery && !diffMap) return rawStatMarginals;
    return Object.fromEntries(
      Object.entries(rawStatMarginals).filter(([key, _]) => {
        return idMarginals && key in idMarginals;
      })
    );
  }, [rawStatMarginals, curSearchQuery, idMarginals, diffMap]);

  // For each outer filter, get the inner filters that have non-null stats
  const [outerIdsToInnerIds, filteredInnerIds] = useMemo(() => {
    const validMap = new Map<string, string[]>();
    const validInnerSet = new Set<string>();
    if (!statMarginals) return [validMap, validInnerSet];

    outerFilterIds.forEach((outerId) => {
      const validSamples = innerFilterIds.filter((innerId) => {
        const stats = statMarginals[getMarginalKey(innerId, outerId)];
        const isValid =
          stats &&
          Object.keys(stats).length > 0 &&
          Object.values(stats)[0]?.n > 0;
        return isValid;
      });
      if (validSamples.length > 0) {
        validMap.set(outerId, validSamples);
      }
    });

    innerFilterIds.forEach((innerId) => {
      const stats = statMarginals[getMarginalKey(innerId, null)];
      const isValid =
        stats &&
        Object.keys(stats).length > 0 &&
        Object.values(stats)[0]?.n > 0;

      if (isValid) {
        validInnerSet.add(innerId);
      }
    });

    return [validMap, validInnerSet];
  }, [outerFilterIds, innerFilterIds, statMarginals, getMarginalKey]);

  // Determine whether there is an outer or inner dimension
  const hasOuterDimension = useMemo(() => {
    return outerIdsToInnerIds && outerIdsToInnerIds.size > 0;
  }, [outerIdsToInnerIds]);
  const hasInnerDimension = useMemo(() => {
    return filteredInnerIds && filteredInnerIds.size > 0;
  }, [filteredInnerIds]);

  // Determine what to display as the outer and inner dim names
  const [outerDimName, innerDimName] = useMemo(() => {
    return [
      outerDimId && dimensionsMap?.[outerDimId]?.name,
      innerDimId && dimensionsMap?.[innerDimId]?.name,
    ];
  }, [outerDimId, innerDimId, dimensionsMap]);

  const [outerLabel, innerLabel]: [string, string] = useMemo(() => {
    return [outerDimName || 'outer', innerDimName || 'inner'];
  }, [outerDimName, innerDimName]);
  const getOuterKey = (outerId: string) => getMarginalKey(null, outerId);

  /**
   * Handle feedback
   */

  // const attributeFeedback = useMemo(() => {
  //   if (!voteState) return [];
  //   return Object.entries(voteState).flatMap(([agent_run_id, attributes]) =>
  //     Object.entries(attributes).map(
  //       ([attribute, vote]) =>
  //         ({
  //           attribute,
  //           vote,
  //         }) as AttributeFeedback
  //     )
  //   );
  // }, [voteState]);
  // const [missingQueries, setMissingQueries] = useState<string>('');
  // const [waitingOnNewQuery, setWaitingOnNewQuery] = useState(false);
  // const handleFeedbackSubmit = useCallback(async () => {
  //   if (!curSearchQuery) return;
  //   // if (attributeFeedback.length === 0 && !missingQueries) {
  //   if (!missingQueries) {
  //     toast({
  //       title: 'No feedback provided',
  //       description: 'Please provide feedback',
  //       variant: 'destructive',
  //     });
  //     return;
  //   }

  //   toast({
  //     title: 'Feedback submitted',
  //     description: "We're recomputing the search results with your feedback...",
  //   });
  //   setWaitingOnNewQuery(true);

  //   try {
  //     const result = await dispatch(
  //       submitAttributeFeedback({
  //         originalQuery: curSearchQuery,
  //         feedback: attributeFeedback,
  //         missingQueries,
  //       })
  //     ).unwrap();

  //     // Update the curAttributeQuery
  //     dispatch(clearSearch());
  //     dispatch(setSearchQueryTextboxValue(result));

  //     // Reset feedback state
  //     dispatch(clearVoteState());
  //     setMissingQueries('');
  //   } finally {
  //     setWaitingOnNewQuery(false);
  //   }
  // }, [curSearchQuery, attributeFeedback, missingQueries, dispatch]);

  /**
   * Handle toggling of outer and inner panels
   */

  // Get first item so we can expand it
  const getFirstItemId = useCallback(() => {
    const items = outerIdsToInnerIds.keys();
    // Get first item from the iterator if it exists
    const firstItem = items?.next();
    return firstItem && !firstItem.done ? firstItem.value : null;
  }, [outerIdsToInnerIds]);

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

    const firstItem = getFirstItemId();
    if (
      firstItem &&
      (expandedOuter === undefined || Object.keys(expandedOuter).length === 0)
    ) {
      dispatch(addExpandedOuter(firstItem));
      alreadyExpanded.current = true;
    }
  }, [getFirstItemId, dispatch, expandedOuter]);

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

  /**
   * Styling
   */

  const getColorForAccuracy = (accuracy: number) => {
    if (accuracy >= 0.8) return 'bg-green-100 text-green-800';
    if (accuracy > 0.0) return 'bg-yellow-100 text-yellow-800';
    return 'bg-red-100 text-red-800';
  };
  const formatAccuracy = (value: number) => `${value.toFixed(2)}`;

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
    <Card className="flex-1 p-3 flex flex-col space-y-2 min-w-0 overflow-auto">
      {/* Header with organization dropdown */}
      <div className="flex justify-between items-center">
        <div>
          <div className="text-sm font-semibold">
            Agent Run Viewer
            <span className="text-xxs text-gray-500 font-light ml-2">
              {outerFilterIds.length} {outerLabel}
              {outerFilterIds.length === 1 ? '' : 's'}
            </span>
          </div>
          <div className="text-xs">Compare agent performance across runs.</div>
        </div>

        {/* Place dimension selector in the header */}
        <DimensionSelector />
      </div>

      {/* Hint for refining search queries */}
      {/* {curSearchQuery && (
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
      )} */}

      {/* Content area */}
      <div
        className="space-y-2 overflow-auto custom-scrollbar"
        ref={containerRef}
      >
        {/* If there is an outer grouping, do that */}
        {hasOuterDimension &&
          Array.from(outerIdsToInnerIds.keys()).map((outerId, index) => (
            <Card
              key={index}
              className={cn(
                `p-2 rounded-md shadow-none transition-all duration-200 ${
                  (expandedOuter?.[outerId] ?? false)
                    ? 'border-blue-200'
                    : 'border-gray-200'
                }`,
                'space-y-2'
              )}
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
                        <span className="font-mono">{outerLabel}</span>
                        {' ' + outerFilters?.[outerId]?.name || outerId}
                        <span className="text-xxs text-gray-500 font-light ml-2">
                          {outerIdsToInnerIds.get(outerId)?.length || 0}{' '}
                          {innerLabel}
                          {outerIdsToInnerIds.get(outerId)?.length === 1
                            ? ''
                            : 's'}
                        </span>
                      </p>
                    </div>
                  </div>
                </div>
                {outerStatMarginals &&
                  outerStatMarginals[getOuterKey(outerId)] &&
                  !curSearchQuery && (
                    <div className="flex flex-row flex-wrap gap-2 font-mono">
                      {Object.entries(
                        outerStatMarginals[getOuterKey(outerId)] || {}
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
                  {outerIdsToInnerIds.get(outerId)?.map((innerId) => {
                    return (
                      <InnerCard
                        key={innerId}
                        innerId={innerId}
                        innerLabel={innerLabel}
                        innerName={innerFilters?.[innerId]?.name || innerId}
                        stats={statMarginals[getMarginalKey(innerId, outerId)]}
                        agentRunIds={
                          idMarginals?.[getMarginalKey(innerId, outerId)] || []
                        }
                        onShowAgentRun={onShowAgentRun}
                        isExpanded={
                          expandedInner?.[outerId]?.[innerId] ?? false
                        }
                        onToggle={() => toggleInner(outerId, innerId)}
                        innerCount={outerIdsToInnerIds.get(outerId)?.length}
                      />
                    );
                  })}
                </div>
              )}
            </Card>
          ))}

        {/* No outer grouping, but has an inner grouping */}
        {!hasOuterDimension &&
          hasInnerDimension &&
          innerFilterIds?.map((innerId, index) => (
            <InnerCard
              key={innerId}
              innerId={innerId}
              innerLabel={innerLabel}
              innerName={innerFilters?.[innerId]?.name || innerId}
              stats={statMarginals[getMarginalKey(innerId, null)]}
              agentRunIds={idMarginals?.[getMarginalKey(innerId, null)] || []}
              onShowAgentRun={onShowAgentRun}
              isExpanded={expandedInner?.['DEFAULT_OUTER']?.[innerId] ?? false}
              onToggle={() => toggleInner('DEFAULT_OUTER', innerId)}
              innerCount={innerFilterIds.length}
            />
          ))}

        {!hasOuterDimension && !hasInnerDimension && (
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
    </Card>
  );
}
