import { RegexSnippet, TaskStats } from '../types/experimentViewerTypes';

import { ChevronDown, ChevronRight } from 'lucide-react';
import React, { useCallback, useEffect, useMemo } from 'react';
import {
  requestRegexSnippetsIfExist,
  // voteOnAttribute,
} from '../store/searchSlice';
import { updateRegexSnippets } from '../store/experimentViewerSlice';
import { getAgentRunMetadata } from '../store/frameSlice';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { RootState } from '../store/store';
import { SearchResultWithCitations } from '../types/frameTypes';
import { AgentRunMetadata } from './AgentRunMetadata';
import { useRouter } from 'next/navigation';
import { navToAgentRun } from '@/lib/nav';

interface InnerCardProps {
  innerId: string;
  innerName?: string;
  innerLabel: string;
  stats: TaskStats | null;
  agentRunIds: string[];
  isExpanded: boolean;
  onToggle?: () => void;
  innerCount?: number;
}

interface AttributeSectionProps {
  dataId: string;
  curAttributeQuery: string;
  attributes: SearchResultWithCitations[];
}

const AttributeSection: React.FC<AttributeSectionProps> = ({
  dataId,
  curAttributeQuery,
  attributes: attributes,
}) => {
  const router = useRouter();
  const frameGridId = useAppSelector(
    (state: RootState) => state.frame.frameGridId
  );

  if (attributes.length === 0) {
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
      {attributes.map((attribute, idx) => {
        const attributeText = attribute.value;
        if (!attributeText) {
          return null;
        }
        const citations = attribute.citations || [];
        // const currentVote = voteState?.[dataId]?.[attributeText];

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
                onMouseDown={(e) => {
                  navToAgentRun(
                    e,
                    router,
                    window,
                    dataId,
                    citation.block_idx,
                    frameGridId,
                    curAttributeQuery
                  );
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
            onMouseDown={(e) => {
              const firstCitation = citations.length > 0 ? citations[0] : null;
              const blockId = firstCitation?.block_idx;
              navToAgentRun(
                e,
                router,
                window,
                dataId,
                blockId,
                frameGridId,
                curAttributeQuery
              );
            }}
          >
            <div className="flex flex-col">
              <div className="flex items-start justify-between gap-2">
                <p className="mb-0.5 flex-1">{renderTextWithCitations()}</p>
                <div className="flex shrink-0">
                  {/* <Tooltip>
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
                              agent_run_id: dataId,
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
                              agent_run_id: dataId,
                              attribute: attributeText,
                              vote: 'down',
                            })
                          );
                        }}
                      >
                        <ThumbsDown className="w-3 h-3" />
                      </button>
                    </TooltipTrigger>
                  </Tooltip> */}
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

const InnerCard: React.FC<InnerCardProps> = ({
  innerId,
  innerName,
  innerLabel,
  stats,
  agentRunIds,
  isExpanded,
  onToggle,
}) => {
  const router = useRouter();
  const dispatch = useAppDispatch();

  const {
    curSearchQuery,
    searchResultMap: attributeMap,
    loadingSearchQuery: loadingAttributesForId,
  } = useAppSelector((state: RootState) => state.search);

  const { baseFilter, agentRunMetadata, frameGridId } = useAppSelector(
    (state: RootState) => state.frame
  );

  const { regexSnippets } = useAppSelector(
    (state: RootState) => state.experimentViewer
  );

  /**
   * Regex snippets for the associated transcripts
   */

  useEffect(() => {
    if (
      isExpanded &&
      baseFilter &&
      agentRunIds.length > 0 &&
      !loadingAttributesForId
    ) {
      const fetchSnippets = async () => {
        try {
          const result = await dispatch(
            requestRegexSnippetsIfExist({
              filterId: baseFilter.id,
              agentRunIds: agentRunIds,
            })
          ).unwrap();
          dispatch(updateRegexSnippets(result));
        } catch (error) {
          console.error('Error requesting regex snippets', error);
        }
      };
      fetchSnippets();
    }
  }, [isExpanded, baseFilter, agentRunIds, dispatch, loadingAttributesForId]);

  // Get all score keys from both current and previous stats
  const allScoreKeys = useMemo(() => {
    const keys = new Set<string>();

    if (stats) {
      Object.keys(stats).forEach((key) => keys.add(key));
    }

    return Array.from(keys);
  }, [stats]);

  const formatAccuracy = (value: number) => `${value.toFixed(2)}`;

  const getColorForAccuracy = (accuracy: number) => {
    if (accuracy >= 0.8) return 'bg-green-100 text-green-800';
    if (accuracy > 0.0) return 'bg-yellow-100 text-yellow-800';
    return 'bg-red-100 text-red-800';
  };

  useEffect(() => {
    if (isExpanded && agentRunIds.length > 0 && !loadingAttributesForId) {
      dispatch(getAgentRunMetadata(agentRunIds));
    }
  }, [isExpanded, baseFilter, agentRunIds, dispatch, loadingAttributesForId]); // Re-request when base filter changes too

  const getAttributes = useCallback(
    (dataId: string) => {
      if (!curSearchQuery) return null;
      const attributes = attributeMap?.[dataId]?.[curSearchQuery].filter(
        (attr) => attr.value !== null
      );
      if (attributes === undefined || attributes.length === 0) return null;
      return attributes;
    },
    [curSearchQuery, attributeMap]
  );

  return (
    agentRunIds.length > 0 && (
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
                  <span className="font-mono">{innerLabel}</span>
                  {' ' + (innerName || innerId)}
                  <span className="text-xxs text-gray-500 font-light ml-2">
                    {agentRunIds.length} agent run
                    {agentRunIds.length === 1 ? '' : 's'}
                  </span>
                </span>
              </div>
            </div>
          </div>
          {stats && (
            <div className="flex flex-row gap-2 items-center font-mono">
              {allScoreKeys.map((scoreKey, index) => {
                if (curSearchQuery) return null;

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
            {agentRunIds.map((agentRunId) => {
              // Skip if there is an active query but there are no matching attribute values
              const attributes = getAttributes(agentRunId);

              if (curSearchQuery && attributes === null) return null;

              return (
                <div
                  key={agentRunId}
                  className="flex flex-col p-1 border rounded text-xs bg-white/80 hover:bg-gray-50"
                >
                  <div
                    className="cursor-pointer"
                    onMouseDown={(e) =>
                      navToAgentRun(
                        e,
                        router,
                        window,
                        agentRunId,
                        undefined,
                        frameGridId
                      )
                    }
                  >
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">
                        Agent Run{' '}
                        <span className="font-mono">{agentRunId}</span>
                      </span>
                      <div className="flex gap-2">
                        <span
                          className="text-blue-600 font-medium hover:text-blue-700"
                          onMouseDown={(e) => {
                            navToAgentRun(
                              e,
                              router,
                              window,
                              agentRunId,
                              undefined,
                              frameGridId,
                              curSearchQuery
                            );
                          }}
                        >
                          View
                        </span>
                      </div>
                    </div>
                    {/* Display metadata if available */}
                    {agentRunMetadata && agentRunMetadata[agentRunId] && (
                      <AgentRunMetadata agentRunId={agentRunId} />
                    )}
                  </div>

                  <RegexSnippetsSection
                    regexSnippets={regexSnippets?.[agentRunId]}
                  />

                  {/* Replace the inline attribute section with the new component */}
                  {attributes && curSearchQuery && (
                    <AttributeSection
                      dataId={agentRunId}
                      curAttributeQuery={curSearchQuery}
                      attributes={attributes}
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
