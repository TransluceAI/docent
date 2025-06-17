import { ChevronDown, ChevronRight, Loader2, ChevronLeft, ChevronFirst, ChevronLast } from 'lucide-react';
import React, {
  useMemo,
  useState,
  useEffect,
  useRef,
  useCallback,
} from 'react';
import { useRouter } from 'next/navigation';
import { FixedSizeList, ListChildComponentProps } from 'react-window';

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
import { Citation } from '../types/experimentViewerTypes';
import { AgentRunMetadata } from './AgentRunMetadata';
import { RegexSnippet } from '../types/experimentViewerTypes';
import { navToAgentRun } from '@/lib/nav';
import { renderTextWithCitations } from '@/lib/renderCitations';
import { RootState } from '../store/store';
import { SearchResultWithCitations } from '../types/frameTypes';
import { addBaseFilter, updateBaseFilter } from '../store/searchSlice';

interface AttributeSectionProps {
  dataId: string;
  curAttributeQuery: string;
  attributes: SearchResultWithCitations[];
}

const AttributeSection: React.FC<AttributeSectionProps> = ({
  dataId,
  curAttributeQuery,
  attributes,
}) => {
  const router = useRouter();
  const frameGridId = useAppSelector((state: RootState) => state.frame.frameGridId);

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
      {attributes.map((attribute, idx) => {
        const attributeText = attribute.value;
        if (!attributeText) {
          return null;
        }
        const citations = attribute.citations || [];
        return (
          <div
            key={idx}
            className="group bg-indigo-50 rounded-md p-1 text-xs text-indigo-900 leading-snug mt-1 hover:bg-indigo-100 transition-colors cursor-pointer border border-transparent hover:border-indigo-200"
            onMouseDown={(e) => {
              const firstCitation = citations.length > 0 ? citations[0] : null;
              navToAgentRun(
                e,
                router,
                window,
                dataId,
                firstCitation?.transcript_idx ?? undefined,
                firstCitation?.block_idx,
                frameGridId,
                curAttributeQuery
              );
            }}
          >
            <div className="flex flex-col">
              <div className="flex items-start justify-between gap-2">
                <p className="mb-0.5 flex-1">
                  {renderTextWithCitations(
                    attributeText,
                    citations,
                    dataId,
                    router,
                    window,
                    curAttributeQuery,
                    frameGridId
                  )}
                </p>
                <div className="flex shrink-0"></div>
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

const HighlightedSnippet: React.FC<{ snippetData: RegexSnippet }> = ({ snippetData }) => {
  const [isExpanded, setIsExpanded] = React.useState(false);
  try {
    if (!snippetData || typeof snippetData !== 'object') {
      return <p className="text-xs text-red-600">Error: Invalid snippet data</p>;
    }
    const { snippet, match_start, match_end } = snippetData;
    if (
      typeof snippet !== 'string' ||
      typeof match_start !== 'number' ||
      typeof match_end !== 'number'
    ) {
      return <p className="text-xs text-red-600">Error: Invalid snippet format</p>;
    }
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
          style={{ scrollbarWidth: 'thin', scrollbarColor: '#a5b3e6 #e0e7ff' }}
        >
          <span className="text-xs text-indigo-900 break-words whitespace-pre-wrap">
            {before}
            <span className="px-0.5 py-0.25 bg-indigo-200 text-indigo-800 rounded">{matched}</span>
            {after}
          </span>
        </div>
      </div>
    );
  } catch (error) {
    return <p className="text-xs text-red-600">Error rendering snippet</p>;
  }
};

const RegexSnippetsSection: React.FC<{ regexSnippets?: RegexSnippet[] }> = ({ regexSnippets }) => {
  if (!regexSnippets || regexSnippets.length === 0) {
    return null;
  }
  return (
    <div className="border-indigo-100 border-t pt-1 mt-1 space-y-1">
      <div className="flex items-center">
        <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
        <span className="text-xs font-medium text-indigo-700">Regex matches</span>
      </div>
      {regexSnippets?.map((snippetData, index) => (
        <HighlightedSnippet key={index} snippetData={snippetData} />
      ))}
    </div>
  );
};

export default function ExperimentViewer() {
  const dispatch = useAppDispatch();
  const router = useRouter();
  
  // Get all state at the top level
  const { innerDimId, outerDimId, dimensionsMap, agentRunMetadata, frameGridId, baseFilter } = useAppSelector(
    (state) => state.frame
  );

  const {
    loadingSearchQuery,
    curSearchQuery,
    searchResultMap: attributeMap,
  } = useAppSelector((state) => state.search);

  const {
    expandedOuter,
    expandedInner,
    experimentViewerScrollPosition,
    dimIdsToFilterIds,
    filtersMap,
    regexSnippets,
    statMarginals: rawStatMarginals,
    idMarginals: rawIdMarginals,
    outerStatMarginals,
  } = useAppSelector((state) => state.experimentViewer);

  // Scroll handling
  const scrolledOnceRef = useRef(false);
  const [scrollPosition, setScrollPosition] = useState<number | undefined>(undefined);
  const debouncedScrollPosition = useDebounce(scrollPosition, 100);

  // Use debouncing to prevent too many updates
  useEffect(() => {
    if (debouncedScrollPosition) {
      dispatch(setExperimentViewerScrollPosition(debouncedScrollPosition));
    }
  }, [debouncedScrollPosition, dispatch]);

  const containerRef = useRef<HTMLDivElement>(null);
  const [listHeight, setListHeight] = useState(600);

  // Add resize observer to update list height
  useEffect(() => {
    if (!containerRef.current) return;

    const updateHeight = () => {
      if (containerRef.current) {
        const containerHeight = containerRef.current.clientHeight;
        const paginationHeight = 48; // Approximate height of pagination controls
        setListHeight(containerHeight - paginationHeight);
      }
    };

    const resizeObserver = new ResizeObserver(updateHeight);
    resizeObserver.observe(containerRef.current);

    // Initial height calculation
    updateHeight();

    return () => {
      resizeObserver.disconnect();
    };
  }, []);

  const containerRefCallback = useCallback(
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
            const attrs = attributeMap?.[datapointId]?.[curSearchQuery];
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
  }, [rawIdMarginals, curSearchQuery, attributeMap]);

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

  // Flatten agent run entries for virtualization
  const flatAgentRuns = useMemo(() => {
    const result: { agentRunId: string; marginalKey: string }[] = [];
    allAgentRunEntries.forEach(([marginalKey, agentRunIds]) => {
      agentRunIds.forEach(agentRunId => {
        result.push({ agentRunId, marginalKey });
      });
    });
    return result;
  }, [allAgentRunEntries]);

  // Get unique outer and inner dimension values with their IDs
  const outerValuesWithIds = useMemo(() => {
    if (!outerDimId || !filtersMap || !dimIdsToFilterIds) return [];
    return dimIdsToFilterIds[outerDimId]?.map(id => ({
      id,
      value: filtersMap[id].value
    })) || [];
  }, [outerDimId, filtersMap, dimIdsToFilterIds]);

  const innerValuesWithIds = useMemo(() => {
    if (!innerDimId || !filtersMap || !dimIdsToFilterIds) return [];
    return dimIdsToFilterIds[innerDimId]?.map(id => ({
      id,
      value: filtersMap[id].value
    })) || [];
  }, [innerDimId, filtersMap, dimIdsToFilterIds]);

  // Calculate average scores for each dimension combination or single dimension
  const dimensionScores = useMemo(() => {
    if (!statMarginals) return {};
    // 2D case
    if (outerValuesWithIds.length && innerValuesWithIds.length) {
      const scores: Record<string, Record<string, { score: number; n?: number }>> = {};
      outerValuesWithIds.forEach(({ id: outerId, value: outerValue }) => {
        scores[outerValue] = {};
        innerValuesWithIds.forEach(({ id: innerId, value: innerValue }) => {
          const key = `${innerDimId},${innerId}|${outerDimId},${outerId}`;
          const stats = statMarginals[key];
          let scoreKey = stats && Object.keys(stats).find(k => k.toLowerCase().includes('default'));
          if (!scoreKey && stats) scoreKey = Object.keys(stats)[0];
          if (stats && scoreKey && stats[scoreKey]?.mean !== undefined && stats[scoreKey].mean !== null) {
            scores[outerValue][innerValue] = { 
              score: stats[scoreKey].mean as number,
              n: stats[scoreKey].n
            };
          } else {
            scores[outerValue][innerValue] = { score: 0 };
          }
        });
      });
      return scores;
    }
    // 1D case: only outer
    if (outerValuesWithIds.length && !innerValuesWithIds.length) {
      const scores: Record<string, { score: number; n?: number }> = {};
      outerValuesWithIds.forEach(({ id: outerId, value: outerValue }) => {
        const key = `${outerDimId},${outerId}`;
        const stats = statMarginals[key];
        let scoreKey = stats && Object.keys(stats).find(k => k.toLowerCase().includes('default'));
        if (!scoreKey && stats) scoreKey = Object.keys(stats)[0];
        if (stats && scoreKey && stats[scoreKey]?.mean !== undefined && stats[scoreKey].mean !== null) {
          scores[outerValue] = { 
            score: stats[scoreKey].mean as number,
            n: stats[scoreKey].n
          };
        } else {
          scores[outerValue] = { score: 0 };
        }
      });
      return scores;
    }
    // 1D case: only inner
    if (!outerValuesWithIds.length && innerValuesWithIds.length) {
      const scores: Record<string, { score: number; n?: number }> = {};
      innerValuesWithIds.forEach(({ id: innerId, value: innerValue }) => {
        const key = `${innerDimId},${innerId}`;
        const stats = statMarginals[key];
        let scoreKey = stats && Object.keys(stats).find(k => k.toLowerCase().includes('default'));
        if (!scoreKey && stats) scoreKey = Object.keys(stats)[0];
        if (stats && scoreKey && stats[scoreKey]?.mean !== undefined && stats[scoreKey].mean !== null) {
          scores[innerValue] = { 
            score: stats[scoreKey].mean as number,
            n: stats[scoreKey].n
          };
        } else {
          scores[innerValue] = { score: 0 };
        }
      });
      return scores;
    }
    return {};
  }, [statMarginals, outerValuesWithIds, innerValuesWithIds, innerDimId, outerDimId]);

  // Helper to safely get dimension name
  const getDimensionName = (dimId: string | undefined) => {
    if (!dimId || !dimensionsMap) return 'Dimension';
    return dimensionsMap[dimId]?.name ?? 'Dimension';
  };

  // Add pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 100; // Adjust this number based on performance testing

  // Calculate pagination values
  const totalPages = Math.ceil(flatAgentRuns.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = Math.min(startIndex + itemsPerPage, flatAgentRuns.length);
  const currentPageItems = flatAgentRuns.slice(startIndex, endIndex);

  // Pagination controls
  const goToPage = (page: number) => {
    setCurrentPage(Math.max(1, Math.min(page, totalPages)));
  };

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
    <Card className="flex-1 p-3 flex flex-col min-h-0">
      {/* Header with organization dropdown - always visible */}
      <div className="flex justify-between items-center shrink-0">
        <div>
          <div className="text-sm font-semibold">
            Agent Run Viewer
          </div>
          <div className="text-xs">Compare agent performance across runs.</div>
        </div>
        {/* Place dimension selector in the header */}
        <DimensionSelector />
      </div>

      {/* Dimension scores table - always visible */}
      {outerValuesWithIds.length > 0 && innerValuesWithIds.length > 0 && (
        <div className="w-full border border-gray-200 rounded mb-4 shrink-0">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th className="border border-gray-200 p-2 bg-gray-50 sticky left-0"></th>
                {innerValuesWithIds.map(({ id: innerId, value: innerValue }) => (
                  <th
                    key={innerId}
                    className="border border-gray-200 p-2 bg-gray-50 cursor-pointer hover:bg-indigo-100 transition-colors"
                    title={`Filter to ${getDimensionName(innerDimId)}: ${innerValue}`}
                    onClick={() => {
                      if (innerDimId && dimensionsMap) {
                        const innerFilter = {
                          type: 'primitive',
                          key_path: dimensionsMap[innerDimId]?.metadata_key
                            ? ['metadata', ...dimensionsMap[innerDimId].metadata_key.split('.')]
                            : undefined,
                          value: innerValue,
                          op: '==',
                          id: crypto.randomUUID(),
                          name: null,
                        } as PrimitiveFilter;
                        dispatch(addBaseFilter(innerFilter));
                      }
                    }}
                  >
                    <span className="underline decoration-dotted underline-offset-2 cursor-pointer" style={{textDecorationStyle: 'dotted'}}>{innerValue}</span>
                    <span className="absolute right-1 top-1 text-xs text-indigo-400" style={{fontSize: '10px'}}>&#128269;</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {outerValuesWithIds.map(({ id: outerId, value: outerValue }) => (
                <tr key={outerId}>
                  <td
                    className="border border-gray-200 p-2 bg-gray-50 font-medium sticky left-0 cursor-pointer hover:bg-indigo-100 transition-colors relative"
                    title={`Filter to ${getDimensionName(outerDimId)}: ${outerValue}`}
                    onClick={() => {
                      if (outerDimId && dimensionsMap) {
                        const outerFilter = {
                          type: 'primitive',
                          key_path: dimensionsMap[outerDimId]?.metadata_key
                            ? ['metadata', ...dimensionsMap[outerDimId].metadata_key.split('.')]
                            : undefined,
                          value: outerValue,
                          op: '==',
                          id: crypto.randomUUID(),
                          name: null,
                        } as PrimitiveFilter;
                        dispatch(addBaseFilter(outerFilter));
                      }
                    }}
                  >
                    <span className="underline decoration-dotted underline-offset-2 cursor-pointer" style={{textDecorationStyle: 'dotted'}}>{outerValue}</span>
                    <span className="absolute right-1 top-1 text-xs text-indigo-400" style={{fontSize: '10px'}}>&#128269;</span>
                  </td>
                  {innerValuesWithIds.map(({ id: innerId, value: innerValue }) => {
                    const row = dimensionScores[outerValue];
                    const cellData = typeof row === 'object' && row !== null ? (row as Record<string, { score: number; n?: number }>)[innerValue] : undefined;
                    const score = cellData?.score;
                    const n = cellData?.n;
                    return (
                      <td 
                        key={innerId} 
                        className={`border border-gray-200 p-2 cursor-pointer hover:bg-indigo-100 transition-colors relative ${
                          typeof score === 'number' && score >= 0.8 
                            ? 'bg-green-50' 
                            : typeof score === 'number' && score > 0 
                              ? 'bg-yellow-50' 
                              : 'bg-red-50'
                        }`}
                        title={`Filter to ${getDimensionName(outerDimId)}: ${outerValue}, ${getDimensionName(innerDimId)}: ${innerValue}`}
                        onClick={() => {
                          if (outerDimId && innerDimId && dimensionsMap) {
                            const outerFilter = {
                              type: 'primitive',
                              key_path: dimensionsMap[outerDimId]?.metadata_key
                                ? ['metadata', ...dimensionsMap[outerDimId].metadata_key.split('.')]
                                : undefined,
                              value: outerValue,
                              op: '==',
                              id: crypto.randomUUID(),
                              name: null,
                            } as PrimitiveFilter;
                            const innerFilter = {
                              type: 'primitive',
                              key_path: dimensionsMap[innerDimId]?.metadata_key
                                ? ['metadata', ...dimensionsMap[innerDimId].metadata_key.split('.')]
                                : undefined,
                              value: innerValue,
                              op: '==',
                              id: crypto.randomUUID(),
                              name: null,
                            } as PrimitiveFilter;
                            // Remove any filters with the same key_path as outerFilter or innerFilter
                            const filtersToKeep = (baseFilter?.filters || []).filter((f: import('../types/frameTypes').FrameFilter) => {
                              if (f.type !== 'primitive') return true;
                              const fKeyPath = (f as PrimitiveFilter).key_path?.join('.') || '';
                              const outerKeyPath = outerFilter.key_path?.join('.') || '';
                              const innerKeyPath = innerFilter.key_path?.join('.') || '';
                              return fKeyPath !== outerKeyPath && fKeyPath !== innerKeyPath;
                            });
                            // Add the new filters
                            const newFilters = [...filtersToKeep, outerFilter, innerFilter];
                            const newBaseFilter: import('../types/frameTypes').ComplexFilter = {
                              type: 'complex',
                              op: 'and',
                              id: baseFilter?.id || crypto.randomUUID(),
                              name: null,
                              filters: newFilters,
                            };
                            dispatch(updateBaseFilter(newBaseFilter));
                          }
                        }}
                      >
                        <span className="underline decoration-dotted underline-offset-2 cursor-pointer" style={{textDecorationStyle: 'dotted'}}>
                          {typeof score === 'number' ? score.toFixed(2) : ''}
                        </span>
                        {n !== undefined && <span className="text-gray-500 ml-1">(n={n})</span>}
                        <span className="absolute right-1 top-1 text-xs text-indigo-400" style={{fontSize: '10px'}}>&#128269;</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {/* 1D table: only outer - always visible */}
      {outerValuesWithIds.length > 0 && innerValuesWithIds.length === 0 && dimensionsMap && (
        <div className="w-full border border-gray-200 rounded mb-4 shrink-0">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th className="border border-gray-200 p-2 bg-gray-50">{dimensionsMap[outerDimId as keyof typeof dimensionsMap]?.name || 'Dimension'}</th>
                <th className="border border-gray-200 p-2 bg-gray-50">Score</th>
              </tr>
            </thead>
            <tbody>
              {outerValuesWithIds.map(({ id: outerId, value: outerValue }) => {
                const cellData = dimensionScores[outerValue] as { score: number; n?: number } | undefined;
                const score = cellData?.score;
                const n = cellData?.n;
                return (
                  <tr key={outerId}>
                    <td 
                      className="border border-gray-200 p-2 bg-gray-50 font-medium cursor-pointer hover:bg-indigo-100 transition-colors relative"
                      title={`Filter to ${getDimensionName(outerDimId)}: ${outerValue}`}
                      onClick={() => {
                        if (outerDimId && dimensionsMap) {
                          const outerFilter = {
                            type: 'primitive',
                            key_path: dimensionsMap[outerDimId]?.metadata_key
                              ? ['metadata', ...dimensionsMap[outerDimId].metadata_key.split('.')]
                              : undefined,
                            value: outerValue,
                            op: '==',
                            id: crypto.randomUUID(),
                            name: null,
                          } as PrimitiveFilter;
                          dispatch(addBaseFilter(outerFilter));
                        }
                      }}
                    >
                      <span className="underline decoration-dotted underline-offset-2 cursor-pointer" style={{textDecorationStyle: 'dotted'}}>{outerValue}</span>
                      <span className="absolute right-1 top-1 text-xs text-indigo-400" style={{fontSize: '10px'}}>&#128269;</span>
                    </td>
                    <td className={`border border-gray-200 p-2 cursor-pointer hover:bg-indigo-100 transition-colors relative ${
                      typeof score === 'number' && score >= 0.8
                        ? 'bg-green-50'
                        : typeof score === 'number' && score > 0
                          ? 'bg-yellow-50'
                          : 'bg-red-50'
                    }`}
                      onClick={() => {
                        if (outerDimId && dimensionsMap) {
                          const outerFilter = {
                            type: 'primitive',
                            key_path: dimensionsMap[outerDimId]?.metadata_key
                              ? ['metadata', ...dimensionsMap[outerDimId].metadata_key.split('.')]
                              : undefined,
                            value: outerValue,
                            op: '==',
                            id: crypto.randomUUID(),
                            name: null,
                          } as PrimitiveFilter;
                          dispatch(addBaseFilter(outerFilter));
                        }
                      }}
                      title={`Filter to ${getDimensionName(outerDimId)}: ${outerValue}`}
                    >
                      {typeof score === 'number' ? (
                        <span className="underline decoration-dotted underline-offset-2 cursor-pointer" style={{textDecorationStyle: 'dotted'}}>{score.toFixed(2)}</span>
                      ) : ''}
                      {n !== undefined && <span className="text-gray-500 ml-1">(n={n})</span>}
                      <span className="absolute right-1 top-1 text-xs text-indigo-400" style={{fontSize: '10px'}}>&#128269;</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {/* 1D table: only inner - always visible */}
      {innerValuesWithIds.length > 0 && outerValuesWithIds.length === 0 && dimensionsMap && (
        <div className="w-full border border-gray-200 rounded mb-4 shrink-0">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th className="border border-gray-200 p-2 bg-gray-50">{dimensionsMap[innerDimId as keyof typeof dimensionsMap]?.name || 'Dimension'}</th>
                <th className="border border-gray-200 p-2 bg-gray-50">Score</th>
              </tr>
            </thead>
            <tbody>
              {innerValuesWithIds.map(({ id: innerId, value: innerValue }) => {
                const cellData = dimensionScores[innerValue] as { score: number; n?: number } | undefined;
                const score = cellData?.score;
                const n = cellData?.n;
                return (
                  <tr key={innerId}>
                    <td 
                      className="border border-gray-200 p-2 bg-gray-50 font-medium cursor-pointer hover:bg-indigo-100 transition-colors relative"
                      title={`Filter to ${getDimensionName(innerDimId)}: ${innerValue}`}
                      onClick={() => {
                        if (innerDimId && dimensionsMap) {
                          const innerFilter = {
                            type: 'primitive',
                            key_path: dimensionsMap[innerDimId]?.metadata_key
                              ? ['metadata', ...dimensionsMap[innerDimId].metadata_key.split('.')]
                              : undefined,
                            value: innerValue,
                            op: '==',
                            id: crypto.randomUUID(),
                            name: null,
                          } as PrimitiveFilter;
                          dispatch(addBaseFilter(innerFilter));
                        }
                      }}
                    >
                      <span className="underline decoration-dotted underline-offset-2 cursor-pointer" style={{textDecorationStyle: 'dotted'}}>{innerValue}</span>
                      <span className="absolute right-1 top-1 text-xs text-indigo-400" style={{fontSize: '10px'}}>&#128269;</span>
                    </td>
                    <td className={`border border-gray-200 p-2 cursor-pointer hover:bg-indigo-100 transition-colors relative ${
                      typeof score === 'number' && score >= 0.8
                        ? 'bg-green-50'
                        : typeof score === 'number' && score > 0
                          ? 'bg-yellow-50'
                          : 'bg-red-50'
                    }`}
                      onClick={() => {
                        if (innerDimId && dimensionsMap) {
                          const innerFilter = {
                            type: 'primitive',
                            key_path: dimensionsMap[innerDimId]?.metadata_key
                              ? ['metadata', ...dimensionsMap[innerDimId].metadata_key.split('.')]
                              : undefined,
                            value: innerValue,
                            op: '==',
                            id: crypto.randomUUID(),
                            name: null,
                          } as PrimitiveFilter;
                          dispatch(addBaseFilter(innerFilter));
                        }
                      }}
                      title={`Filter to ${getDimensionName(innerDimId)}: ${innerValue}`}
                    >
                      {typeof score === 'number' ? (
                        <span className="underline decoration-dotted underline-offset-2 cursor-pointer" style={{textDecorationStyle: 'dotted'}}>{score.toFixed(2)}</span>
                      ) : ''}
                      {n !== undefined && <span className="text-gray-500 ml-1">(n={n})</span>}
                      <span className="absolute right-1 top-1 text-xs text-indigo-400" style={{fontSize: '10px'}}>&#128269;</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Content area: FLAT LIST of all agent runs - scrollable */}
      <div className="flex flex-col flex-1 min-h-0">
        {flatAgentRuns.length > 0 ? (
          <>
            <div className="flex-1 min-h-0 overflow-auto">
              {currentPageItems.map(({ agentRunId }) => {
                const attributes = curSearchQuery ? (attributeMap?.[agentRunId]?.[curSearchQuery]?.filter((attr: any) => attr.value !== null) || null) : null;
                return (
                  <div
                    key={agentRunId}
                    className="flex flex-col p-1 pb-[6px] border rounded text-xs bg-white/80 hover:bg-gray-50 mb-1"
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
                          undefined,
                          frameGridId
                        )
                      }
                    >
                      <div className="flex justify-between items-center">
                        <span className="text-gray-600">
                          Agent Run <span className="font-mono">{agentRunId}</span>
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
                    {/* Regex matches */}
                    <RegexSnippetsSection regexSnippets={regexSnippets?.[agentRunId]} />
                    {/* Attribute section if search query is active */}
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

            {/* Pagination Controls - always visible */}
            <div className="flex items-center justify-between px-2 py-2 border-t shrink-0">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => goToPage(1)}
                  disabled={currentPage === 1}
                  className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronFirst className="h-4 w-4" />
                </button>
                <button
                  onClick={() => goToPage(currentPage - 1)}
                  disabled={currentPage === 1}
                  className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="text-sm">
                  Page {currentPage} of {totalPages}
                </span>
                <button
                  onClick={() => goToPage(currentPage + 1)}
                  disabled={currentPage === totalPages}
                  className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
                <button
                  onClick={() => goToPage(totalPages)}
                  disabled={currentPage === totalPages}
                  className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronLast className="h-4 w-4" />
                </button>
              </div>
              <div className="text-sm text-gray-500">
                Showing {startIndex + 1}-{endIndex} of {flatAgentRuns.length} runs
              </div>
            </div>
          </>
        ) : (
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
