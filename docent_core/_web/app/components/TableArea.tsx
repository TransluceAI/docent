'use client';

import { useMemo, useCallback } from 'react';
import { v4 as uuid4 } from 'uuid';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { PrimitiveFilter } from '../types/frameTypes';
import { addBaseFilter, addBaseFilters } from '../store/searchSlice';
import { cn } from '@/lib/utils';
import { TaskStats } from '../types/experimentViewerTypes';

// Constants
const MAX_DIMENSION_VALUES = 100;
const HIGH_SCORE_THRESHOLD = 0.8;
const LOW_SCORE_THRESHOLD = 0;

const getScoreFromStats = (stats: TaskStats) => {
  if (!stats) return { score: 0, scoreKey: '' };
  const scoreKey =
    Object.keys(stats).find((k) => k.toLowerCase().includes('default')) ||
    Object.keys(stats)[0];
  if (
    !scoreKey ||
    stats[scoreKey]?.mean === undefined ||
    stats[scoreKey].mean === null
  ) {
    return { score: 0, scoreKey: scoreKey || '' };
  }
  return {
    score: stats[scoreKey].mean as number,
    n: stats[scoreKey].n,
    ci: stats[scoreKey].ci,
    scoreKey,
  };
};

const getScoreDisplay = (score: number | undefined, ci?: number) => {
  if (typeof score !== 'number') return '';
  let display = score.toFixed(2);
  if (ci && ci > 0) display += ` ±${ci.toFixed(3)}`;
  return display;
};

const getScoreClass = (score: number | undefined, n: number | undefined) => {
  if (typeof score !== 'number' || n === undefined || n === 0)
    return 'bg-gray-50 hover:bg-gray-100';
  if (score >= HIGH_SCORE_THRESHOLD) return 'bg-green-50 hover:bg-green-100';
  if (score > LOW_SCORE_THRESHOLD) return 'bg-yellow-50 hover:bg-yellow-100';
  return 'bg-red-50 hover:bg-red-100';
};

const getFilterTitle = (
  rowName: string,
  rowValue: string,
  colName?: string,
  colValue?: string
) => {
  if (colName && colValue) {
    return `Filter to ${rowName}: ${rowValue}, ${colName}: ${colValue}`;
  }
  return `Filter to ${rowName}: ${rowValue}`;
};

export default function TableArea() {
  const dispatch = useAppDispatch();

  const { binStats: rawBinStats } = useAppSelector(
    (state) => state.experimentViewer
  );

  const { innerBinKey, outerBinKey, dimensionsMap } = useAppSelector(
    (state) => state.frame
  );

  // Get unique outer and inner dimension values with their IDs - matching ExperimentViewer logic
  const outerValuesWithIds = useMemo(() => {
    if (!outerBinKey || !rawBinStats) {
      return [];
    }

    // Extract dimension values from the bin keys
    const values = new Set<string>();
    Object.keys(rawBinStats).forEach((key) => {
      const parts = key.split('|');
      parts.forEach((part) => {
        if (part.includes(',')) {
          const [dim, value] = part.split(',', 2);
          if (dim === outerBinKey) {
            values.add(value);
          }
        }
      });
    });

    const result = Array.from(values).map((value) => ({
      id: value,
      value: value,
    }));
    return result.slice(0, MAX_DIMENSION_VALUES);
  }, [outerBinKey, rawBinStats]);

  const innerValuesWithIds = useMemo(() => {
    if (!innerBinKey || !rawBinStats) {
      return [];
    }

    // Extract dimension values from the bin keys
    const values = new Set<string>();
    Object.keys(rawBinStats).forEach((key) => {
      const parts = key.split('|');
      parts.forEach((part) => {
        if (part.includes(',')) {
          const [dim, value] = part.split(',', 2);
          if (dim === innerBinKey) {
            values.add(value);
          }
        }
      });
    });

    const result = Array.from(values).map((value) => ({
      id: value,
      value: value,
    }));
    return result.slice(0, MAX_DIMENSION_VALUES);
  }, [innerBinKey, rawBinStats]);

  // Get total counts for UI indicators
  const totalOuterValues = useMemo(() => {
    if (!outerBinKey || !rawBinStats) return 0;
    const values = new Set<string>();
    Object.keys(rawBinStats).forEach((key) => {
      const parts = key.split('|');
      parts.forEach((part) => {
        if (part.includes(',')) {
          const [dim, value] = part.split(',', 2);
          if (dim === outerBinKey) {
            values.add(value);
          }
        }
      });
    });
    return values.size;
  }, [outerBinKey, rawBinStats]);

  const totalInnerValues = useMemo(() => {
    if (!innerBinKey || !rawBinStats) return 0;
    const values = new Set<string>();
    Object.keys(rawBinStats).forEach((key) => {
      const parts = key.split('|');
      parts.forEach((part) => {
        if (part.includes(',')) {
          const [dim, value] = part.split(',', 2);
          if (dim === innerBinKey) {
            values.add(value);
          }
        }
      });
    });
    return values.size;
  }, [innerBinKey, rawBinStats]);

  // Helper to safely get dimension name
  const getDimensionName = (dimId: string | undefined) => {
    if (!dimId || !dimensionsMap) return 'Dimension';
    return dimensionsMap[dimId]?.name ?? 'Dimension';
  };

  const tableData = useMemo(() => {
    const hasOuter = outerValuesWithIds.length > 0;
    const hasInner = innerValuesWithIds.length > 0;

    if (!hasOuter && !hasInner) return null;

    // 2D case: outer as rows, inner as columns
    if (hasOuter && hasInner) {
      return {
        rows: outerValuesWithIds,
        cols: innerValuesWithIds,
        is2D: true,
        rowDimId: outerBinKey,
        colDimId: innerBinKey,
        rowName: getDimensionName(outerBinKey),
        colName: getDimensionName(innerBinKey),
      };
    }

    // 1D case: use available dimension as rows, "Score" as column
    const availableValues = hasOuter ? outerValuesWithIds : innerValuesWithIds;
    const availableDimId = hasOuter ? outerBinKey : innerBinKey;

    return {
      rows: availableValues,
      cols: [{ id: 'score', value: 'Score' }],
      is2D: false,
      rowDimId: availableDimId,
      colDimId: undefined,
      rowName: getDimensionName(availableDimId),
      colName: 'Score',
    };
  }, [
    outerValuesWithIds,
    innerValuesWithIds,
    outerBinKey,
    innerBinKey,
    getDimensionName,
  ]);

  // Calculate average scores for each dimension combination or single dimension
  const dimensionScores = useMemo(() => {
    if (!rawBinStats) return {};
    if (!outerValuesWithIds.length && !innerValuesWithIds.length) return {};

    // 2D case: both dimensions present
    if (outerValuesWithIds.length && innerValuesWithIds.length) {
      const scores: Record<
        string,
        Record<
          string,
          { score: number; n?: number; ci?: number | null; scoreKey?: string }
        >
      > = {};
      outerValuesWithIds.forEach(({ id: outerId, value: outerValue }) => {
        scores[outerValue] = {};
        innerValuesWithIds.forEach(({ id: innerId, value: innerValue }) => {
          const key = `${innerBinKey},${innerId}|${outerBinKey},${outerId}`;
          const stats = rawBinStats[key];
          scores[outerValue][innerValue] = getScoreFromStats(stats);
        });
      });
      return scores;
    }

    // 1D case: only one dimension present
    const availableValues = outerValuesWithIds.length
      ? outerValuesWithIds
      : innerValuesWithIds;
    const availableDimId = outerValuesWithIds.length
      ? outerBinKey
      : innerBinKey;

    const scores: Record<
      string,
      { score: number; n?: number; ci?: number | null; scoreKey?: string }
    > = {};
    availableValues.forEach(({ id, value }) => {
      const key = `${availableDimId},${id}`;
      const stats = rawBinStats[key];
      scores[value] = getScoreFromStats(stats);
    });

    return scores;
  }, [
    rawBinStats,
    outerValuesWithIds,
    innerValuesWithIds,
    innerBinKey,
    outerBinKey,
  ]);

  // Helper function to create filters
  const createFilter = useCallback(
    (dimId: string, value: string): PrimitiveFilter => ({
      type: 'primitive',
      key_path: dimensionsMap?.[dimId]?.metadata_key
        ? ['metadata', ...dimensionsMap[dimId].metadata_key.split('.')]
        : [],
      value,
      op: '==',
      id: uuid4(),
      name: null,
      supports_sql: true,
    }),
    [dimensionsMap]
  );

  if (!tableData || !rawBinStats) {
    return (
      <>
        <div className="h-auto max-h-[35%] overflow-y-auto overflow-x-auto custom-scrollbar border rounded-sm">
          <div className="w-full h-16 flex items-center justify-center">
            <p className="text-xs text-gray-500">
              Select an inner or outer bin key to view grouped stats
            </p>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="h-auto max-h-[35%] overflow-y-auto overflow-x-auto custom-scrollbar border rounded-sm">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-white z-10">
            <tr>
              <th className="border-r border-b border-gray-200 px-2 py-1 sticky left-0" />
              {tableData.cols.map(({ id: colId, value: colValue }, colIdx) => (
                <th
                  key={colId}
                  className={cn(
                    colIdx !== tableData.cols.length - 1 && 'border-r',
                    'border-b border-gray-200 px-2 py-1 text-center font-normal text-gray-700 cursor-pointer hover:bg-gray-100 transition-colors relative max-w-[200px]'
                  )}
                  title={
                    tableData.colDimId
                      ? `Filter to ${tableData.colName}: ${colValue}`
                      : undefined
                  }
                  onClick={() => {
                    if (tableData.colDimId && dimensionsMap) {
                      const filter = createFilter(tableData.colDimId, colValue);
                      dispatch(addBaseFilter(filter));
                    }
                  }}
                >
                  <span className="block truncate overflow-hidden text-ellipsis whitespace-nowrap">
                    <span className="font-light text-[11px]">
                      {tableData.colName}:{' '}
                    </span>
                    <span className="font-mono">{colValue}</span>
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableData.rows.map(({ id: rowId, value: rowValue }) => (
              <tr key={rowId} className="hover:bg-gray-50/50">
                <td
                  className="border-r border-gray-200 px-2 py-1 text-gray-700 sticky left-0 bg-white cursor-pointer hover:bg-gray-100 transition-colors relative z-[9] max-w-[200px]"
                  title={`Filter to ${tableData.rowName}: ${rowValue}`}
                  onClick={() => {
                    if (tableData.rowDimId && dimensionsMap) {
                      const filter = createFilter(tableData.rowDimId, rowValue);
                      dispatch(addBaseFilter(filter));
                    }
                  }}
                >
                  <span className="block truncate pr-3 overflow-hidden text-ellipsis whitespace-nowrap">
                    <span className="font-light text-[11px]">
                      {tableData.rowName}:{' '}
                    </span>
                    <span className="font-mono">{rowValue}</span>
                  </span>
                </td>
                {tableData.cols.map(
                  ({ id: colId, value: colValue }, colIdx) => {
                    // Get score data based on table type
                    let score: number | undefined;
                    let n: number | undefined;
                    let ci: number | undefined;
                    let scoreKey: string | undefined;

                    if (tableData.is2D) {
                      // 2D case: use both dimensions
                      const row = dimensionScores[rowValue];
                      const cellData =
                        typeof row === 'object' && row !== null
                          ? (
                              row as Record<
                                string,
                                {
                                  score: number;
                                  n?: number;
                                  ci?: number;
                                  scoreKey?: string;
                                }
                              >
                            )[colValue]
                          : undefined;
                      score = cellData?.score;
                      n = cellData?.n;
                      ci = cellData?.ci;
                      scoreKey = cellData?.scoreKey;
                    } else {
                      // 1D case: use single dimension
                      const cellData = dimensionScores[rowValue] as
                        | {
                            score: number;
                            n?: number;
                            ci?: number;
                            scoreKey?: string;
                          }
                        | undefined;
                      score = cellData?.score;
                      n = cellData?.n;
                      ci = cellData?.ci;
                      scoreKey = cellData?.scoreKey;
                    }

                    return (
                      <td
                        key={colId}
                        className={cn(
                          colIdx !== tableData.cols.length - 1 && 'border-r',
                          'border-gray-200 px-2 py-1 cursor-pointer transition-colors relative text-center',
                          getScoreClass(score, n)
                        )}
                        title={getFilterTitle(
                          tableData.rowName,
                          rowValue,
                          tableData.colName,
                          colValue
                        )}
                        onClick={() => {
                          if (tableData.rowDimId && dimensionsMap) {
                            if (tableData.is2D && tableData.colDimId) {
                              // 2D case: add both filters
                              const rowFilter = createFilter(
                                tableData.rowDimId,
                                rowValue
                              );
                              const colFilter = createFilter(
                                tableData.colDimId,
                                colValue
                              );
                              dispatch(addBaseFilters([rowFilter, colFilter]));
                            } else {
                              // 1D case: add single filter
                              const filter = createFilter(
                                tableData.rowDimId,
                                rowValue
                              );
                              dispatch(addBaseFilter(filter));
                            }
                          }
                        }}
                      >
                        {n !== undefined && n > 0 && (
                          <div>
                            {scoreKey && (
                              <span className="font-light text-[11px] text-gray-600">
                                {scoreKey}:{' '}
                              </span>
                            )}
                            <span className="font-mono">
                              {getScoreDisplay(score, ci)}
                            </span>
                            <span className="text-[11px] text-gray-500">
                              {' '}
                              n={n}
                            </span>
                          </div>
                        )}
                      </td>
                    );
                  }
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer with indicators */}
      {(totalOuterValues > MAX_DIMENSION_VALUES ||
        totalInnerValues > MAX_DIMENSION_VALUES) && (
        <div className="px-2 py-1 bg-yellow-50 border-t border-yellow-200 text-[11px] text-yellow-700">
          {totalOuterValues > MAX_DIMENSION_VALUES &&
          totalInnerValues > MAX_DIMENSION_VALUES
            ? `Showing first ${MAX_DIMENSION_VALUES} of ${totalOuterValues} rows and first ${MAX_DIMENSION_VALUES} of ${totalInnerValues} columns`
            : totalOuterValues > MAX_DIMENSION_VALUES
              ? `Showing first ${MAX_DIMENSION_VALUES} of ${totalOuterValues} rows`
              : `Showing first ${MAX_DIMENSION_VALUES} of ${totalInnerValues} columns`}
        </div>
      )}
    </>
  );
}
