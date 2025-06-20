'use client';

import { useMemo, useCallback } from 'react';
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
    return 'bg-gray-50';
  if (score >= HIGH_SCORE_THRESHOLD) return 'bg-green-50';
  if (score > LOW_SCORE_THRESHOLD) return 'bg-yellow-50';
  return 'bg-red-50';
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

  const { statMarginals, filtersMap, dimIdsToFilterIds } = useAppSelector(
    (state) => state.experimentViewer
  );

  const { innerDimId, outerDimId, dimensionsMap } = useAppSelector(
    (state) => state.frame
  );

  // Get unique outer and inner dimension values with their IDs
  const outerValuesWithIds = useMemo(() => {
    if (!outerDimId || !filtersMap || !dimIdsToFilterIds) return [];
    const allValues =
      dimIdsToFilterIds[outerDimId]?.map((id) => ({
        id,
        value: filtersMap[id].value,
      })) || [];
    return allValues.slice(0, MAX_DIMENSION_VALUES);
  }, [outerDimId, filtersMap, dimIdsToFilterIds]);

  const innerValuesWithIds = useMemo(() => {
    if (!innerDimId || !filtersMap || !dimIdsToFilterIds) return [];
    const allValues =
      dimIdsToFilterIds[innerDimId]?.map((id) => ({
        id,
        value: filtersMap[id].value,
      })) || [];
    return allValues.slice(0, MAX_DIMENSION_VALUES);
  }, [innerDimId, filtersMap, dimIdsToFilterIds]);

  // Get total counts for UI indicators
  const totalOuterValues = useMemo(() => {
    if (!outerDimId || !filtersMap || !dimIdsToFilterIds) return 0;
    return dimIdsToFilterIds[outerDimId]?.length || 0;
  }, [outerDimId, filtersMap, dimIdsToFilterIds]);

  const totalInnerValues = useMemo(() => {
    if (!innerDimId || !filtersMap || !dimIdsToFilterIds) return 0;
    return dimIdsToFilterIds[innerDimId]?.length || 0;
  }, [innerDimId, filtersMap, dimIdsToFilterIds]);

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
        rowDimId: outerDimId,
        colDimId: innerDimId,
        rowName: getDimensionName(outerDimId),
        colName: getDimensionName(innerDimId),
      };
    }

    // 1D case: use available dimension as rows, "Score" as column
    const availableValues = hasOuter ? outerValuesWithIds : innerValuesWithIds;
    const availableDimId = hasOuter ? outerDimId : innerDimId;

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
    outerDimId,
    innerDimId,
    getDimensionName,
  ]);

  // Calculate average scores for each dimension combination or single dimension
  const dimensionScores = useMemo(() => {
    if (!statMarginals) return {};
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
          const key = `${innerDimId},${innerId}|${outerDimId},${outerId}`;
          const stats = statMarginals[key];
          scores[outerValue][innerValue] = getScoreFromStats(stats);
        });
      });
      return scores;
    }

    // 1D case: only one dimension present
    const availableValues = outerValuesWithIds.length
      ? outerValuesWithIds
      : innerValuesWithIds;
    const availableDimId = outerValuesWithIds.length ? outerDimId : innerDimId;

    const scores: Record<
      string,
      { score: number; n?: number; ci?: number | null; scoreKey?: string }
    > = {};
    availableValues.forEach(({ id, value }) => {
      const key = `${availableDimId},${id}`;
      const stats = statMarginals[key];
      scores[value] = getScoreFromStats(stats);
    });

    return scores;
  }, [
    statMarginals,
    outerValuesWithIds,
    innerValuesWithIds,
    innerDimId,
    outerDimId,
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
      id: crypto.randomUUID(),
      name: null,
    }),
    [dimensionsMap]
  );

  if (!tableData || !statMarginals) {
    return null;
  }

  return (
    <>
      <div className="max-h-2/5 flex-1 overflow-y-auto overflow-x-auto custom-scrollbar border rounded-md">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-gray-50 z-10">
            <tr>
              <th className="border-r border-gray-200 px-2 py-1 sticky left-0 bg-gray-50 " />
              {tableData.cols.map(({ id: colId, value: colValue }, colIdx) => (
                <th
                  key={colId}
                  className={cn(
                    colIdx !== tableData.cols.length - 1 && 'border-r',
                    'border-gray-200 px-2 py-1 text-center font-normal text-gray-700 cursor-pointer hover:bg-indigo-50 transition-colors relative'
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
                  <span className="block truncate">
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
                  className="border-r border-gray-200 px-2 py-1 text-gray-700 sticky left-0 bg-white cursor-pointer hover:bg-indigo-50 transition-colors relative"
                  title={`Filter to ${tableData.rowName}: ${rowValue}`}
                  onClick={() => {
                    if (tableData.rowDimId && dimensionsMap) {
                      const filter = createFilter(tableData.rowDimId, rowValue);
                      dispatch(addBaseFilter(filter));
                    }
                  }}
                >
                  <span className="block truncate pr-3">
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
                          'border-gray-200 px-2 py-1 cursor-pointer hover:bg-indigo-50 transition-colors relative text-center',
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
