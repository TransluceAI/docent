import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ChevronDown,
  ChevronRight,
  Network,
  Loader2,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import {
  OrganizationMethod,
  RegexSnippet,
} from '../types/experimentViewerTypes';

import { BASE_DOCENT_PATH } from '../constants';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { useSelector } from 'react-redux';
import { RootState } from '../store/store';
import {
  AttributeWithCitation,
  TaskStats,
} from '../types/experimentViewerTypes';
import { getTranscriptMetadata } from '../store/frameSlice';
import {
  requestRegexSnippetsIfExist,
  voteOnAttribute,
} from '../store/attributeFinderSlice';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { updateRegexSnippets } from '../store/experimentViewerSlice';

interface InnerCard {
  sampleId: string;
  innerId: string;
  stats: TaskStats | null;
  datapointIds: string[];
  onShowDatapoint?: (datapointId: string, blockId?: number) => void;
  isExpanded: boolean;
  onToggle?: () => void;
  organizationMethod: OrganizationMethod;
  experimentCount?: number;
}

interface AttributeSectionProps {
  dataId: string;
  curAttributeQuery: string;
  attributeValues: AttributeWithCitation[];
  onShowDatapoint?: (datapointId: string, blockId?: number) => void;
}

const AttributeSection: React.FC<AttributeSectionProps> = ({
  dataId,
  curAttributeQuery,
  attributeValues,
  onShowDatapoint,
}) => {
  const dispatch = useAppDispatch();
  const voteState = useAppSelector((state) => state.attributeFinder.voteState);

  if (attributeValues.length === 0) {
    return null;
  }

  return (
    <div className="pt-1 mt-1 border-t border-indigo-100 text-xs space-y-1">
      <div className="flex items-center mb-1">
        <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
        <span className="text-xs font-medium text-indigo-700">
          Attributes from your query
        </span>
      </div>

      {/* Render only the attributes for the current query */}
      {attributeValues.map((attributeValue, idx) => {
        const attributeText = attributeValue.attribute;
        const citations = attributeValue.citations || [];
        const currentVote = voteState?.[dataId]?.[attributeText];

        // Create a component that renders text with citations highlighted
        const renderTextWithCitations = () => {
          if (!citations.length) {
            return attributeText;
          }

          // Sort citations by start index to process them in order
          const sortedCitations = [...citations].sort(
            (a, b) => a.start_idx - b.start_idx
          );

          const parts: JSX.Element[] = [];
          let lastIndex = 0;

          sortedCitations.forEach((citation, i) => {
            // Add text before the citation
            if (citation.start_idx > lastIndex) {
              parts.push(
                <span key={`text-${i}`}>
                  {attributeText.slice(lastIndex, citation.start_idx)}
                </span>
              );
            }

            // Add the cited text as a clickable element
            const citedText = attributeText.slice(
              citation.start_idx,
              citation.end_idx
            );
            parts.push(
              <button
                key={`citation-${i}`}
                className="px-0.5 py-0.25 bg-indigo-200 text-indigo-800 rounded hover:bg-indigo-400 hover:text-white transition-colors font-medium"
                onClick={(e) => {
                  e.stopPropagation();
                  if (onShowDatapoint) {
                    onShowDatapoint(dataId, citation.block_idx);
                  }
                }}
              >
                {citedText}
              </button>
            );

            lastIndex = citation.end_idx;
          });

          // Add any remaining text
          if (lastIndex < attributeText.length) {
            parts.push(
              <span key={`text-end`}>{attributeText.slice(lastIndex)}</span>
            );
          }

          return <>{parts}</>;
        };

        return (
          <div
            key={idx}
            className="group bg-indigo-50 rounded-md p-1 text-xs text-indigo-900 leading-snug mt-1 hover:bg-indigo-100 transition-colors cursor-pointer border border-transparent hover:border-indigo-200"
            onClick={(e) => {
              e.stopPropagation();
              if (onShowDatapoint) {
                const firstCitation =
                  citations.length > 0 ? citations[0] : null;
                onShowDatapoint(dataId, firstCitation?.block_idx);
              }
            }}
          >
            <div className="flex flex-col">
              <div className="flex items-start justify-between gap-2">
                <p className="mb-0.5 flex-1">{renderTextWithCitations()}</p>
                <div className="flex shrink-0">
                  <Tooltip>
                    <TooltipContent>This result is relevant</TooltipContent>
                    <TooltipTrigger asChild>
                      <button
                        className={`p-1 rounded transition-colors ${
                          currentVote === 'up'
                            ? 'bg-indigo-300 text-indigo-900 shadow-sm'
                            : 'hover:bg-indigo-200 hover:text-indigo-800'
                        }`}
                        onClick={(e) => {
                          e.stopPropagation();
                          dispatch(
                            voteOnAttribute({
                              datapoint_id: dataId,
                              attribute: attributeText,
                              vote: 'up',
                            })
                          );
                        }}
                      >
                        <ThumbsUp className="w-3 h-3" />
                      </button>
                    </TooltipTrigger>
                  </Tooltip>
                  <Tooltip>
                    <TooltipContent>This result is not relevant</TooltipContent>
                    <TooltipTrigger asChild>
                      <button
                        className={`p-1 rounded transition-colors ${
                          currentVote === 'down'
                            ? 'bg-indigo-300 text-indigo-900 shadow-sm'
                            : 'hover:bg-indigo-200 hover:text-indigo-800'
                        }`}
                        onClick={(e) => {
                          e.stopPropagation();
                          dispatch(
                            voteOnAttribute({
                              datapoint_id: dataId,
                              attribute: attributeText,
                              vote: 'down',
                            })
                          );
                        }}
                      >
                        <ThumbsDown className="w-3 h-3" />
                      </button>
                    </TooltipTrigger>
                  </Tooltip>
                </div>
              </div>
              <div className="flex items-center gap-1 text-[10px] text-indigo-600 mt-1">
                <span className="opacity-70">{curAttributeQuery}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

// Helper component to render highlighted regex snippets
const HighlightedSnippet: React.FC<{ snippetData: RegexSnippet }> = ({
  snippetData,
}) => {
  const [isExpanded, setIsExpanded] = React.useState(false);
  try {
    // Defensive coding to handle missing or malformed data
    if (!snippetData || typeof snippetData !== 'object') {
      return (
        <p className="text-xs text-red-600">Error: Invalid snippet data</p>
      );
    }

    const { snippet, match_start, match_end } = snippetData;

    // Check if we have all required properties with valid types
    if (
      typeof snippet !== 'string' ||
      typeof match_start !== 'number' ||
      typeof match_end !== 'number'
    ) {
      return (
        <p className="text-xs text-red-600">Error: Invalid snippet format</p>
      );
    }

    // Verify match positions are within bounds
    if (
      match_start < 0 ||
      match_end > snippet.length ||
      match_start >= match_end
    ) {
      return <p className="text-xs">{snippet}</p>;
    }

    const before = snippet.substring(0, match_start);
    const matched = snippet.substring(match_start, match_end);
    const after = snippet.substring(match_end);

    return (
      <div
        className="bg-indigo-50 p-2 rounded-md border border-transparent hover:border-indigo-200 max-w-full cursor-pointer transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div
          className={`overflow-y-auto ${isExpanded ? '' : 'max-h-20'}`}
          style={{
            scrollbarWidth: 'thin',
            scrollbarColor: '#a5b3e6 #e0e7ff',
          }}
        >
          <span className="text-xs text-indigo-900 break-words whitespace-pre-wrap">
            {before}
            <span className="px-0.5 py-0.25 bg-indigo-200 text-indigo-800 rounded">
              {matched}
            </span>
            {after}
          </span>
        </div>
      </div>
    );
  } catch (error) {
    return <p className="text-xs text-red-600">Error rendering snippet</p>;
  }
};

// RegexSnippetsSection component to display regex matches
const RegexSnippetsSection: React.FC<{
  regexSnippets?: RegexSnippet[];
  onShowDatapoint?: (datapointId: string, blockId?: number) => void;
}> = ({ regexSnippets }) => {
  if (!regexSnippets || regexSnippets.length === 0) {
    return null;
  }

  return (
    <div className="border-indigo-100 border-t pt-1 mt-1 space-y-1">
      <div className="flex items-center">
        <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
        <span className="text-xs font-medium text-indigo-700">
          Regex matches
        </span>
      </div>

      {regexSnippets?.map((snippetData, index) => (
        <HighlightedSnippet key={index} snippetData={snippetData} />
      ))}
    </div>
  );
};

const InnerCard: React.FC<InnerCard> = ({
  sampleId,
  innerId,
  stats,
  datapointIds,
  onShowDatapoint,
  isExpanded,
  onToggle,
  organizationMethod,
}) => {
  const dispatch = useAppDispatch();

  const attributeMap = useSelector(
    (state: RootState) => state.attributeFinder.attributeMap
  );
  const curAttributeQuery = useSelector(
    (state: RootState) => state.attributeFinder.curAttributeQuery
  );
  const evalId = useSelector((state: RootState) => state.frame.evalId);
  const transcriptMetadata = useSelector(
    (state: RootState) => state.frame.transcriptMetadata
  );
  const interventionDescriptionMarginals = useSelector(
    (state: RootState) =>
      state.experimentViewer.interventionDescriptionMarginals
  );

  const selectedDiffTranscript = useSelector(
    (state: RootState) => state.experimentViewer.selectedDiffTranscript
  );
  const selectedDiffSampleId = useSelector(
    (state: RootState) => state.experimentViewer.selectedDiffSampleId
  );

  /**
   * Regex snippets for the associated transcripts
   */

  const regexSnippets = useAppSelector(
    (state: RootState) => state.experimentViewer.regexSnippets
  );
  const baseFilter = useAppSelector(
    (state: RootState) => state.frame.baseFilter
  );

  useEffect(() => {
    if (isExpanded && baseFilter && datapointIds.length > 0) {
      const fetchSnippets = async () => {
        try {
          const result = await dispatch(
            requestRegexSnippetsIfExist({
              filterId: baseFilter.id,
              datapointIds: datapointIds,
            })
          ).unwrap();
          dispatch(updateRegexSnippets(result));
        } catch (error) {
          console.error('Error requesting regex snippets', error);
        }
      };
      fetchSnippets();
    }
  }, [isExpanded, baseFilter, datapointIds, dispatch]);

  // Get all score keys from both current and previous stats
  const allScoreKeys = useMemo(() => {
    const keys = new Set<string>();

    if (stats) {
      Object.keys(stats).forEach((key) => keys.add(key));
    }

    return Array.from(keys);
  }, [stats]);

  const formatAccuracy = (value: number) => `${value.toFixed(2)}`;

  const formatDiff = (diff: number) =>
    diff > 0 ? `+${formatAccuracy(diff)}` : formatAccuracy(diff);

  const getColorForAccuracy = (accuracy: number) => {
    if (accuracy >= 0.8) return 'bg-green-100 text-green-800';
    if (accuracy > 0.0) return 'bg-yellow-100 text-yellow-800';
    return 'bg-red-100 text-red-800';
  };

  const getColorForDiff = (diff: number) => {
    if (diff > 0.05) return 'text-green-600';
    if (diff < -0.05) return 'text-red-600';
    return 'text-gray-500';
  };

  useEffect(() => {
    if (isExpanded && datapointIds.length > 0) {
      dispatch(getTranscriptMetadata(datapointIds));
    }
  }, [isExpanded, baseFilter, datapointIds, dispatch]); // Re-request when base filter changes too

  // const handleDiffClick = (dataId: string) => {
  //   if (selectedDiffTranscript === null) {
  //     // First transcript selected
  //     setSelectedDiffTranscript(dataId);
  //     setSelectedDiffSampleId(sampleId);
  //   } else if (selectedDiffTranscript === dataId) {
  //     // Deselect if clicking the same transcript
  //     setSelectedDiffTranscript(null);
  //     setSelectedDiffSampleId(null);
  //   } else {
  //     // Second transcript selected - navigate to diff view
  //     router.push(
  //       `${BASE_DOCENT_PATH}/${evalId}/diff?datapoint1=${selectedDiffTranscript}&datapoint2=${dataId}`
  //     );
  //     setSelectedDiffTranscript(null);
  //     setSelectedDiffSampleId(null);
  //   }
  // };

  // Check if diffing is allowed for this card
  // const canDiff =
  //   selectedDiffSampleId === null || selectedDiffSampleId === sampleId;

  // Create a function to get the marginal key for interventionDescriptions
  const getMarginalKey = (
    sampleId: string | null,
    experimentId: string | null
  ) => {
    if (sampleId !== null && experimentId !== null) {
      return `sample_id,sample_id_${sampleId}|experiment_id,experiment_id_${experimentId}`;
    } else if (sampleId !== null) {
      return `sample_id,sample_id_${sampleId}`;
    } else if (experimentId !== null) {
      return `experiment_id,experiment_id_${experimentId}`;
    } else {
      return '';
    }
  };

  // Get the appropriate key for the current organization method
  const getInterventionKey = () => {
    if (organizationMethod === 'sample') {
      // When organized by sample, innerId is the experiment ID
      return getMarginalKey(null, innerId);
    }
    return null;
  };

  // Get intervention description if available
  const interventionKey = getInterventionKey();
  const hasInterventionDescription =
    organizationMethod === 'sample' &&
    interventionDescriptionMarginals &&
    interventionKey &&
    interventionDescriptionMarginals[interventionKey] &&
    interventionDescriptionMarginals[interventionKey].length > 0;

  const getAttributeValues = useCallback(
    (dataId: string) => {
      if (curAttributeQuery === undefined) return null;
      const values = attributeMap?.[dataId]?.[curAttributeQuery];
      if (values === undefined || values.length === 0) return null;
      return values;
    },
    [curAttributeQuery, attributeMap]
  );

  return (
    datapointIds.length > 0 && (
      <div
        className={`flex flex-col p-1.5 rounded border transition-all duration-200 ${
          isExpanded
            ? 'bg-blue-50/50 border-blue-200'
            : 'bg-gray-50/80 border-gray-200 hover:bg-gray-100'
        }`}
      >
        <div
          className="flex flex-1 justify-between cursor-pointer text-xs items-center"
          onClick={() => onToggle?.()}
        >
          <div className="flex items-center">
            {isExpanded ? (
              <ChevronDown className="h-3.5 w-3.5 mr-1.5 text-blue-500" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 mr-1.5 text-gray-400" />
            )}
            <div>
              <div className="flex items-center">
                <span className="font-medium text-gray-600">
                  {organizationMethod === 'experiment' ? 'Task' : 'Experiment'}{' '}
                  <span className="font-mono">{innerId}</span>
                  {curAttributeQuery && (
                    <span className="text-xxs text-gray-500 font-light ml-2">
                      {datapointIds.length} datapoint
                      {datapointIds.length === 1 ? '' : 's'}
                    </span>
                  )}
                </span>
                {/* {organizationMethod === 'experiment' &&
                  (experimentCount ?? 0) > 1 && (
                    <button
                      className="ml-2 text-gray-400 hover:text-blue-500 flex items-center text-[10px] transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        router.push(
                          `${BASE_DOCENT_PATH}/${evalId}/forest/${innerId}`
                        );
                      }}
                      title="View experiment tree"
                    >
                      <Network className="h-3 w-3" />
                    </button>
                  )} */}
              </div>
              {hasInterventionDescription && (
                <p className="text-xs italic text-gray-600 mt-0.5">
                  {interventionDescriptionMarginals[interventionKey][0]}
                </p>
              )}
            </div>
          </div>
          {stats && (
            <div className="flex flex-row gap-2 items-center font-mono">
              {allScoreKeys.map((scoreKey, index) => {
                if (curAttributeQuery) return null;

                const scoreStats = stats[scoreKey];
                if (!scoreStats) return null;

                const isLoading =
                  scoreStats.mean === null || scoreStats.ci === null;

                return (
                  <React.Fragment key={scoreKey}>
                    <div className="inline-flex items-center gap-1">
                      <span className="text-[10px] text-gray-400 font-normal">
                        {scoreKey}:
                      </span>
                      <div
                        className={`px-1.5 py-0.5 rounded-sm text-xs font-medium ${
                          isLoading
                            ? 'bg-gray-100 text-gray-600'
                            : getColorForAccuracy(scoreStats.mean!)
                        }`}
                      >
                        {isLoading ? (
                          '--'
                        ) : (
                          <>
                            {formatAccuracy(scoreStats.mean!)}
                            <span className="text-[11px] font-normal">
                              {scoreStats.ci! > 0
                                ? ` ±${formatAccuracy(scoreStats.ci!)}`
                                : ''}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                    {index === allScoreKeys.length - 1 && (
                      <span className="text-gray-500 text-[11px]">
                        n={scoreStats.n}
                      </span>
                    )}
                  </React.Fragment>
                );
              })}
            </div>
          )}
        </div>
        {isExpanded && (
          <div className="flex flex-col gap-1 mt-1.5 ml-5 pl-0.5">
            {datapointIds.map((dataId) => {
              // Skip if there is an active query but there are no matching attribute values
              const attributeValues = getAttributeValues(dataId);
              if (curAttributeQuery && attributeValues === null) return null;

              return (
                <div
                  key={dataId}
                  className={`flex flex-col p-1 border rounded text-xs cursor-pointer transition-colors ${
                    selectedDiffTranscript !== undefined &&
                    selectedDiffTranscript !== dataId
                      ? 'bg-orange-50/50 hover:bg-orange-100/50'
                      : 'bg-white/80 hover:bg-gray-50'
                  }`}
                  onClick={() =>
                    onShowDatapoint ? onShowDatapoint(dataId) : undefined
                  }
                >
                  <div>
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">
                        Transcript <span className="font-mono">{dataId}</span>
                      </span>
                      <div className="flex gap-2">
                        {/* Only show diff option if this card's sample ID matches the selected diff sample ID or no diff is in progress */}
                        {/* {canDiff && (
               <span
                 className={`font-medium cursor-pointer ${
                   selectedDiffTranscript === dataId
                     ? 'text-red-500 hover:text-red-600'
                     : selectedDiffTranscript !== null
                       ? 'text-orange-500 hover:text-orange-600'
                       : 'text-orange-500 hover:text-orange-600'
                 }`}
                 onClick={(e) => {
                   e.stopPropagation();
                   if (selectedDiffTranscript === dataId) {
                     setSelectedDiffTranscript(null);
                     setSelectedDiffSampleId(null);
                   } else {
                     handleDiffClick(dataId);
                   }
                 }}
               >
                 {selectedDiffTranscript === dataId
                   ? 'Cancel compare selection'
                   : selectedDiffTranscript !== null
                     ? 'Select to compare'
                     : 'Compare'}
               </span>
             )} */}
                        <span
                          className="text-blue-600 font-medium hover:text-blue-700"
                          onClick={(e) => {
                            e.stopPropagation();
                            onShowDatapoint
                              ? onShowDatapoint(dataId)
                              : () => {};
                          }}
                        >
                          View
                        </span>
                      </div>
                    </div>
                    {/* Display metadata if available */}
                    {transcriptMetadata && transcriptMetadata[dataId] && (
                      <div className="pt-1 border-t border-gray-100 text-[10px] text-gray-500 flex flex-wrap gap-x-3 gap-y-0.5">
                        {transcriptMetadata[dataId].is_loading_messages ? (
                          <span className="whitespace-nowrap flex items-center">
                            <Loader2 className="h-3 w-3 animate-spin text-blue-500 mr-1" />
                            <span className="text-blue-500 font-medium">
                              Running experiment (click to view progress)...
                            </span>
                          </span>
                        ) : (
                          <>
                            {transcriptMetadata[dataId].epoch_id !==
                              undefined && (
                              <span className="whitespace-nowrap">
                                <span className="font-medium text-gray-600">
                                  run:
                                </span>{' '}
                                {transcriptMetadata[dataId].epoch_id}
                              </span>
                            )}
                            {transcriptMetadata[dataId].model !== undefined && (
                              <span className="whitespace-nowrap">
                                <span className="font-medium text-gray-600">
                                  model:
                                </span>{' '}
                                {transcriptMetadata[dataId].model}
                              </span>
                            )}
                            {transcriptMetadata[dataId].scores &&
                              transcriptMetadata[dataId].default_score_key && (
                                <span
                                  className={`whitespace-nowrap font-medium px-1 rounded ${
                                    typeof transcriptMetadata[dataId].scores[
                                      transcriptMetadata[dataId]
                                        .default_score_key
                                    ] === 'boolean'
                                      ? transcriptMetadata[dataId].scores[
                                          transcriptMetadata[dataId]
                                            .default_score_key
                                        ]
                                        ? 'bg-green-50 text-green-600'
                                        : 'bg-red-50 text-red-600'
                                      : 'bg-blue-50 text-blue-600'
                                  }`}
                                >
                                  {typeof transcriptMetadata[dataId].scores[
                                    transcriptMetadata[dataId].default_score_key
                                  ] === 'boolean'
                                    ? transcriptMetadata[dataId].scores[
                                        transcriptMetadata[dataId]
                                          .default_score_key
                                      ]
                                      ? '✓ correct'
                                      : '✗ incorrect'
                                    : `${transcriptMetadata[dataId].default_score_key}: ${transcriptMetadata[dataId].scores[transcriptMetadata[dataId].default_score_key]}`}
                                </span>
                              )}
                          </>
                        )}
                      </div>
                    )}
                  </div>

                  <RegexSnippetsSection
                    regexSnippets={regexSnippets?.[dataId]}
                    onShowDatapoint={onShowDatapoint}
                  />

                  {/* Replace the inline attribute section with the new component */}
                  {attributeValues && curAttributeQuery && (
                    <AttributeSection
                      dataId={dataId}
                      curAttributeQuery={curAttributeQuery}
                      attributeValues={attributeValues}
                      onShowDatapoint={onShowDatapoint}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    )
  );
};

export default InnerCard;
