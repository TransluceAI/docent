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
import { useFrameGrid } from '../contexts/FrameGridContext';
import type { OrganizationMethod } from '../contexts/FrameGridContext';
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
import { TaskStats } from '@/app/types/docent';
import { Button } from '@/components/ui/button';
import { BASE_DOCENT_PATH } from '../constants';

interface ExperimentViewerProps {
  onShowDatapoint?: (datapointId: string, blockId?: number) => void;
}

export default function ExperimentViewer({
  onShowDatapoint,
}: ExperimentViewerProps) {
  // Use global state from context
  const {
    curEvalId,
    expandedOuter,
    setExpandedOuter,
    expandedInner,
    setExpandedInner,
    experimentViewerScrollPosition,
    setExperimentViewerScrollPosition,
    organizationMethod,
    setOrganizationMethod,
    curAttributeQuery,
    transcriptMetadata,
    expBins,
    expStatMarginals,
    expIdMarginals,
    perSampleStats,
    perExperimentStats,
    interventionDescriptions,
  } = useFrameGrid();
  const router = useRouter();
  // Get search params for handling query parameters
  const searchParams = useSearchParams();

  // Create refs for outer items to enable scrolling to specific items
  const itemRefs = useRef<Record<string, HTMLDivElement | null>>({});
  // Create a ref for the container to track scroll position
  const containerRef = useRef<HTMLDivElement>(null);

  // Initialize variables with empty defaults that will be populated if data exists
  const experiments = useMemo(() => {
    if (!expBins) return [];
    return expBins.experiment_id
      .filter((id) => !id.startsWith('_'))
      .map((id) => id.replace('experiment_id_', ''));
  }, [expBins]);

  const samples = useMemo(() => {
    if (!expBins) return [];
    return expBins.sample_id
      .filter((id) => !id.startsWith('_'))
      .map((id) => id.replace('sample_id_', ''));
  }, [expBins]);

  // Create a function to get the marginal key - safe to use even if data is null
  const getMarginalKey = useCallback(
    (sampleId: string | null, experimentId: string | null) => {
      if (sampleId !== null && experimentId !== null) {
        return `sample_id,sample_id_${sampleId}|experiment_id,experiment_id_${experimentId}`;
      } else if (sampleId !== null) {
        return `sample_id,sample_id_${sampleId}`;
      } else if (experimentId !== null) {
        return `experiment_id,experiment_id_${experimentId}`;
      } else {
        return '';
      }
    },
    []
  );

  // Pre-compute valid samples for each experiment - safe to use even if data is null
  const samplesByExperiment = useMemo(() => {
    const validMap = new Map<string, string[]>();
    if (!expStatMarginals) return validMap;

    experiments.forEach((expId) => {
      const validSamples = samples.filter((sampleId) => {
        const stats = expStatMarginals[getMarginalKey(sampleId, expId)];
        return (
          stats &&
          Object.keys(stats).length > 0 &&
          Object.values(stats)[0]?.n > 0
        );
      });
      validMap.set(expId, validSamples);
    });

    return validMap;
  }, [experiments, samples, expStatMarginals, getMarginalKey]);

  // Pre-compute valid experiments for each sample - safe to use even if data is null
  const experimentsBySample = useMemo(() => {
    const validMap = new Map<string, string[]>();
    if (!expStatMarginals) return validMap;

    samples.forEach((sampleId) => {
      const validExps = experiments.filter((expId) => {
        const stats = expStatMarginals[getMarginalKey(sampleId, expId)];
        return (
          stats &&
          Object.keys(stats).length > 0 &&
          Object.values(stats)[0]?.n > 0
        );
      });
      validMap.set(sampleId, validExps);
    });

    return validMap;
  }, [experiments, samples, expStatMarginals, getMarginalKey]);

  const getFirstItem = useCallback(
    (mode: OrganizationMethod) => {
      const items = mode === 'experiment' ? experiments : samples;
      return items.length > 0 ? items[0] : null;
    },
    [experiments, samples]
  );

  // Handle organization mode change
  const handleOrganizationModeChange = useCallback(
    (value: OrganizationMethod) => {
      // Reset expansion states when organization mode changes
      const firstItem = getFirstItem(value);
      setExpandedOuter(firstItem ? new Set([firstItem]) : new Set());
      setExpandedInner({});
      setOrganizationMethod(value);
    },
    [getFirstItem, setExpandedOuter, setExpandedInner, setOrganizationMethod]
  );

  // Initialize expanded state when component mounts or dependencies change
  useEffect(() => {
    const firstItem = getFirstItem(organizationMethod);
    if (firstItem && expandedOuter.size === 0) {
      setExpandedOuter(new Set([firstItem]));
    }
  }, [getFirstItem]);

  // Save scroll position when user scrolls
  useEffect(() => {
    const handleScroll = () => {
      if (containerRef.current) {
        setExperimentViewerScrollPosition(containerRef.current.scrollTop);
      }
    };

    const container = containerRef.current;
    if (container) {
      container.addEventListener('scroll', handleScroll);
      return () => {
        container.removeEventListener('scroll', handleScroll);
      };
    }
  }, [setExperimentViewerScrollPosition, containerRef.current]);

  // Restore scroll position when component mounts or when experimentViewerScrollPosition changes
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = experimentViewerScrollPosition;
    }
  }, [experimentViewerScrollPosition]);

  // // Scroll to a specific item when scrollToItem prop changes
  // const scrollToItemById = useCallback(
  //   (id: string, type: 'experiment' | 'sample') => {
  //     // Only scroll if the organization method matches the item type
  //     if (
  //       (organizationMethod === 'experiment' && type === 'experiment') ||
  //       (organizationMethod === 'sample' && type === 'sample')
  //     ) {
  //       // If the item is an outer item in the current organization
  //       if (
  //         (organizationMethod === 'experiment' && type === 'experiment') ||
  //         (organizationMethod === 'sample' && type === 'sample')
  //       ) {
  //         // Expand the item if it's not already expanded
  //         if (!expandedOuter.has(id)) {
  //           setExpandedOuter((prev) => {
  //             const newSet = new Set(prev);
  //             newSet.add(id);
  //             return newSet;
  //           });
  //         }

  //         // Scroll to the item with a small delay to ensure it's rendered
  //         setTimeout(() => {
  //           const element = itemRefs.current[id];
  //           if (element && containerRef.current) {
  //             element.scrollIntoView({ behavior: 'smooth', block: 'start' });
  //           }
  //         }, 250);
  //       }
  //     }
  //   },
  //   [organizationMethod, expandedOuter, setExpandedOuter, setExpandedInner]
  // );

  // // Check for expId in query parameters and scroll to that experiment
  // useEffect(() => {
  //   const expId = searchParams.get('expId');
  //   const sampleId = searchParams.get('sampleId');

  //   console.log('effect triggered!');

  //   if (expId) {
  //     // Switch to experiment organization if needed
  //     if (organizationMethod !== 'experiment') {
  //       handleOrganizationModeChange('experiment');
  //     }

  //     // Scroll to the specified experiment
  //     scrollToItemById(expId, 'experiment');
  //   } else if (sampleId) {
  //     // Switch to sample organization if needed
  //     if (organizationMethod !== 'sample') {
  //       handleOrganizationModeChange('sample');
  //     }

  //     // Scroll to the specified sample
  //     scrollToItemById(sampleId, 'sample');
  //   }
  // }, [
  //   searchParams,
  //   scrollToItemById,
  //   organizationMethod,
  //   handleOrganizationModeChange,
  // ]);

  // Return early with loading if data isn't available
  if (!expBins || !expStatMarginals || !expIdMarginals) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center space-y-2 h-full">
        <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    );
  }

  const toggleOuter = (outerId: string) => {
    // First determine whether to add or remove; prevents double-toggling in StrictMode
    const isCurrentlyExpanded = expandedOuter.has(outerId);
    const actionToTake = !isCurrentlyExpanded;

    setExpandedOuter((prev) => {
      const newExpanded = new Set(prev);
      if (actionToTake) {
        newExpanded.add(outerId);
      } else {
        newExpanded.delete(outerId);
      }
      return newExpanded;
    });
  };

  const toggleInner = (outerId: string, innerId: string) => {
    // First determine whether to add or remove; prevents double-toggling in StrictMode
    const isCurrentlyExpanded = expandedInner[outerId]?.has(innerId) || false;
    const actionToTake = !isCurrentlyExpanded;

    setExpandedInner((prev) => {
      const newExpanded = { ...prev };

      if (outerId in newExpanded) {
        if (actionToTake) {
          newExpanded[outerId].add(innerId);
        } else {
          newExpanded[outerId].delete(innerId);
        }
      } else if (actionToTake) {
        newExpanded[outerId] = new Set([innerId]);
      }

      return newExpanded;
    });
  };

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
  const getOrganizationData = () => {
    if (organizationMethod === 'experiment') {
      return {
        outerItems: curAttributeQuery
          ? experiments.filter(
              (expId) => (samplesByExperiment.get(expId)?.length ?? 0) > 0
            )
          : experiments,
        outerAverages: perExperimentStats,
        getOuterKey: (outerId: string) => getMarginalKey(null, outerId),
        innerMap: samplesByExperiment,
        outerLabel: (
          <span>
            <span className="font-mono">{curEvalId}</span> Experiment
          </span>
        ),
        innerLabel: 'task',
        outerPrefix: '',
      };
    } else {
      return {
        outerItems: curAttributeQuery
          ? samples.filter(
              (sampleId) => (experimentsBySample.get(sampleId)?.length ?? 0) > 0
            )
          : samples,
        outerAverages: perSampleStats,
        innerMap: experimentsBySample,
        getOuterKey: (outerId: string) => getMarginalKey(outerId, null),
        outerLabel: (
          <span>
            <span className="font-mono">{curEvalId}</span> Task
          </span>
        ),
        innerLabel: 'experiment',
        outerPrefix: '',
      };
    }
  };

  const {
    outerItems,
    outerAverages,
    innerMap,
    outerLabel,
    innerLabel,
    outerPrefix,
    getOuterKey,
  } = getOrganizationData();

  return (
    <div className="flex flex-col h-full space-y-2">
      {/* Header with organization dropdown */}
      <div className="flex justify-between items-center">
        <div>
          <div className="text-sm font-semibold">
            Experiment Viewer
            <span className="text-xxs text-gray-500 font-light ml-2">
              {experiments.length} experiment
              {experiments.length === 1 ? '' : 's'}
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
        <div className="text-xs text-indigo-800 italic flex items-center gap-1.5 p-1.5 rounded-md border border-indigo-100">
          <HelpCircle className="h-3 w-3 text-indigo-500" />
          <span>
            Not seeing what you expected? You can edit your search query with
            more details to refine the results.
          </span>
        </div>
      )}

      {/* Content area */}
      <ScrollArea className="text-sm" containerRef={containerRef}>
        <div className="space-y-2">
          {outerItems.map((outerId, index) => (
            <Card
              key={outerId}
              className={cn(
                getCardStyles(expandedOuter.has(outerId)),
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
                  {expandedOuter.has(outerId) ? (
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
                          {outerId}
                        </span>
                        <span className="text-xxs text-gray-500 font-light ml-2">
                          {innerMap.get(outerId)?.length || 0} {innerLabel}
                          {innerMap.get(outerId)?.length === 1 ? '' : 's'}
                        </span>
                      </p>
                      {organizationMethod === 'experiment' &&
                        interventionDescriptions &&
                        interventionDescriptions[getOuterKey(outerId)] &&
                        interventionDescriptions[getOuterKey(outerId)].length >
                          0 && (
                          <p className="text-xs italic text-gray-600 mt-0.5">
                            {interventionDescriptions[getOuterKey(outerId)][0]}
                          </p>
                        )}
                    </div>
                    {organizationMethod === 'sample' &&
                      (experimentsBySample.get(outerId)?.length ?? 0) > 1 && (
                        <button
                          className="ml-2 text-gray-400 hover:text-blue-500 flex items-center text-[10px] transition-colors"
                          onClick={(e) => {
                            e.stopPropagation();
                            router.push(
                              `${BASE_DOCENT_PATH}/${curEvalId}/forest/${outerId}`
                            );
                          }}
                          title="View experiment tree"
                        >
                          <Network className="h-3 w-3" />
                        </button>
                      )}
                  </div>
                </div>
                {outerAverages && outerAverages[getOuterKey(outerId)] && (
                  <div className="flex flex-row flex-wrap gap-2 font-mono">
                    {Object.entries(
                      outerAverages[getOuterKey(outerId)] || {}
                    ).map(([scoreKey, stats], idx, arr) => {
                      if (curAttributeQuery) {
                        return null;
                      }
                      const isLoading =
                        stats.mean === null || stats.ci === null;
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

              {expandedOuter.has(outerId) && (
                <div className="space-y-1.5 mt-2 pl-5">
                  {innerMap.get(outerId)?.map((innerId) => {
                    const sampleId =
                      organizationMethod === 'experiment' ? innerId : outerId;
                    const expId =
                      organizationMethod === 'experiment' ? outerId : innerId;
                    const expIdIndex = experiments.indexOf(expId);

                    return (
                      <InnerCard
                        key={innerId}
                        sampleId={sampleId}
                        innerId={innerId}
                        organizationMethod={organizationMethod}
                        prevStats={
                          organizationMethod === 'experiment'
                            ? index > 0
                              ? expStatMarginals[
                                  getMarginalKey(
                                    innerId,
                                    experiments[index - 1]
                                  )
                                ]
                              : null
                            : expIdIndex > 0
                              ? expStatMarginals[
                                  getMarginalKey(
                                    sampleId,
                                    experiments[expIdIndex - 1]
                                  )
                                ]
                              : null
                        }
                        stats={
                          expStatMarginals[getMarginalKey(sampleId, expId)]
                        }
                        transcripts={
                          expIdMarginals?.[getMarginalKey(sampleId, expId)] ||
                          []
                        }
                        onShowDatapoint={onShowDatapoint}
                        isExpanded={expandedInner[outerId]?.has(innerId)}
                        onToggle={() => toggleInner(outerId, innerId)}
                        experimentCount={
                          organizationMethod === 'experiment'
                            ? (experimentsBySample.get(innerId)?.length ?? 0)
                            : undefined
                        }
                      />
                    );
                  })}
                  {innerMap.get(outerId)?.length === 0 && (
                    <div className="text-xs text-gray-500">
                      No results found
                    </div>
                  )}
                </div>
              )}
            </Card>
          ))}
          {outerItems.length === 0 && (
            <div className="text-xs text-gray-500">No results found</div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
