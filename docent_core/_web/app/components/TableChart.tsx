'use client';

import { useCallback } from 'react';
import { v4 as uuid4 } from 'uuid';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { PrimitiveFilter } from '../types/collectionTypes';
import { addFilters } from '../store/collectionSlice';
import { cn } from '@/lib/utils';
import { ChartData, getScoreAt } from '../utils/chartDataUtils';
import ChartContainer from './ChartContainer';
import { useGetChartMetadataQuery } from '../api/chartApi';

// Constants
const MAX_DIMENSION_VALUES = 100;
const HIGH_SCORE_THRESHOLD = 0.8;
const LOW_SCORE_THRESHOLD = 0;

const getScoreDisplay = (score: number | null, ci?: number | null) => {
  if (typeof score !== 'number') return '';
  let display = score.toFixed(2);
  if (ci && ci > 0) display += ` ± ${ci.toFixed(3)}`;
  return display;
};

const getScoreClass = (score: number | null, n: number | null) => {
  if (typeof score !== 'number' || n === undefined || n === 0)
    return 'bg-secondary hover:bg-muted';
  if (score >= HIGH_SCORE_THRESHOLD)
    return 'bg-green-bg hover:bg-green-text/30';
  if (score > LOW_SCORE_THRESHOLD)
    return 'bg-yellow-bg hover:bg-yellow-text/30';
  return 'bg-red-bg hover:bg-red-text/35';
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

export default function TableChart({ chartData }: { chartData: ChartData }) {
  const dispatch = useAppDispatch();
  const { collectionId } = useAppSelector((state) => state.collection);

  // Get chart metadata including dimensions
  const { data: chartMetadata } = useGetChartMetadataQuery(
    { collectionId: collectionId! },
    { skip: !collectionId }
  );

  const tableData = {
    rows: chartData.xValues,
    cols: chartData.seriesValues,
    rowDimId: chartData.xKey,
    colDimId: chartData.seriesKey,
    totalRows: chartData.xValues.length,
    totalCols: chartData.seriesValues.length,
    is2d: chartData.is2d,
  };

  // Helper function to create filters
  const createFilter = useCallback(
    (dimId: string, value: string): PrimitiveFilter | undefined => {
      // Find the dimension in the chart metadata
      const allDimensions = [
        ...(chartMetadata?.fields?.dimensions || []),
        ...(chartMetadata?.fields?.measures || []),
      ];
      const dimension = allDimensions.find((dim) => dim.key === dimId);

      // We can't filter on anything besides run metadata, e.g. cluster centroid
      if (!dimension?.extra?.metadata_key) {
        return undefined;
      }

      // Build key path from dimension metadata
      const key_path = ['metadata', ...dimension.extra.metadata_key.split('.')];

      return {
        type: 'primitive',
        key_path,
        value,
        op: '==',
        id: uuid4(),
        name: null,
        supports_sql: true,
      };
    },
    [chartMetadata?.fields?.dimensions, chartMetadata?.fields?.measures]
  );

  if (!tableData || !chartData.xKey) {
    return (
      <ChartContainer xScroll className="border-t border-border">
        <div className="w-full h-16 flex items-center justify-center">
          <p className="text-xs text-muted-foreground">
            Select an inner or outer bin key to view grouped stats
          </p>
        </div>
      </ChartContainer>
    );
  }

  return (
    <>
      <ChartContainer xScroll className="border-t border-border">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-background z-10">
            <tr>
              <th className="border-r border-b border-border px-2 py-1 sticky left-0" />
              {tableData.cols.map((colValue: string, colIdx: number) => (
                <th
                  key={colValue}
                  className={cn(
                    colIdx !== tableData.cols.length - 1 && 'border-r',
                    'border-b border-border px-2 py-1 text-center font-normal text-primary cursor-pointer hover:bg-muted transition-colors relative max-w-[200px]'
                  )}
                  title={
                    tableData.colDimId
                      ? `Filter to ${tableData.colDimId}: ${colValue}`
                      : undefined
                  }
                  onClick={() => {
                    if (tableData.is2d && tableData.colDimId) {
                      const filter = createFilter(tableData.colDimId, colValue);
                      if (filter) {
                        dispatch(addFilters([filter]));
                      }
                    }
                  }}
                >
                  <span className="block truncate overflow-hidden text-ellipsis whitespace-nowrap">
                    {chartData.seriesLabel && (
                      <span className="font-mono font-bold">
                        {chartData.seriesLabel}:{' '}
                      </span>
                    )}
                    <span className="font-mono">{colValue}</span>
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableData.rows.map((rowValue) => (
              <tr key={rowValue} className="hover:bg-secondary/50">
                <td
                  className="border-r border-border px-2 py-1 text-primary sticky left-0 bg-background cursor-pointer hover:bg-muted transition-colors relative z-[9] max-w-[200px]"
                  title={`Filter to ${tableData.rowDimId}: ${rowValue}`}
                  onClick={() => {
                    if (tableData.rowDimId) {
                      const filter = createFilter(tableData.rowDimId, rowValue);
                      if (filter) {
                        dispatch(addFilters([filter]));
                      }
                    }
                  }}
                >
                  <span className="block truncate pr-3 overflow-hidden text-ellipsis whitespace-nowrap">
                    <span className="font-mono font-bold">
                      {chartData.xLabel}:{' '}
                    </span>
                    <span className="font-mono">{rowValue}</span>
                  </span>
                </td>
                {tableData.cols.map((colValue, colIdx) => {
                  const scoreData = getScoreAt(chartData, colValue, rowValue);

                  const { score, n, ci } = scoreData || {};

                  return (
                    <td
                      key={colValue}
                      className={cn(
                        colIdx !== tableData.cols.length - 1 && 'border-r',
                        'border-border px-2 py-1 cursor-pointer transition-colors relative text-center',
                        getScoreClass(score ?? null, n ?? null)
                      )}
                      title={getFilterTitle(
                        tableData.rowDimId,
                        rowValue,
                        tableData.colDimId || undefined,
                        colValue
                      )}
                      onClick={() => {
                        if (tableData.rowDimId) {
                          if (tableData.is2d && tableData.colDimId) {
                            // 2D case: add both filters
                            const rowFilter = createFilter(
                              tableData.rowDimId,
                              rowValue
                            );
                            const colFilter = createFilter(
                              tableData.colDimId,
                              colValue
                            );
                            if (rowFilter && colFilter) {
                              dispatch(addFilters([rowFilter, colFilter]));
                            } else if (rowFilter) {
                              dispatch(addFilters([rowFilter]));
                            } else if (colFilter) {
                              dispatch(addFilters([colFilter]));
                            }
                          } else {
                            // 1D case: add single filter
                            const filter = createFilter(
                              tableData.rowDimId,
                              rowValue
                            );
                            if (filter) {
                              dispatch(addFilters([filter]));
                            }
                          }
                        }
                      }}
                    >
                      {score !== undefined && score !== null && (
                        <div className="flex flex-row gap-3 items-center justify-between text-[11px]">
                          {chartData.yLabel && (
                            <div className="font-mono text-muted-foreground">
                              {chartData.yLabel}:{' '}
                            </div>
                          )}
                          <div className="font-mono">
                            {getScoreDisplay(score, ci)}
                          </div>
                          {n !== null && n !== undefined && (
                            <div className="text-muted-foreground"> n={n}</div>
                          )}
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </ChartContainer>

      {/* Footer with indicators */}
      {(tableData.totalRows > MAX_DIMENSION_VALUES ||
        tableData.totalCols > MAX_DIMENSION_VALUES) && (
        <div className="px-2 py-1 bg-yellow-50 border-t border-yellow-200 text-[11px] text-yellow-700">
          {tableData.totalRows > MAX_DIMENSION_VALUES &&
          tableData.totalCols > MAX_DIMENSION_VALUES
            ? `Showing first ${MAX_DIMENSION_VALUES} of ${tableData.totalRows} rows and first ${MAX_DIMENSION_VALUES} of ${tableData.totalCols} columns`
            : tableData.totalRows > MAX_DIMENSION_VALUES
              ? `Showing first ${MAX_DIMENSION_VALUES} of ${tableData.totalRows} rows`
              : `Showing first ${MAX_DIMENSION_VALUES} of ${tableData.totalCols} columns`}
        </div>
      )}
    </>
  );
}
