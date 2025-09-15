'use client';

import { useState } from 'react';
import { useAppSelector } from '../store/hooks';
import { cn } from '@/lib/utils';
import { ChartData, getScoreAt } from '../utils/chartDataUtils';
import ChartContainer from './ChartContainer';
import { useChartFilters } from '../../hooks/use-chart-filters';
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';

// Constants
const MAX_DIMENSION_VALUES = 100;
const HIGH_SCORE_THRESHOLD = 0.8;
const LOW_SCORE_THRESHOLD = 0;

// Types
type SortDirection = 'asc' | 'desc' | 'none';
type SortConfig = {
  columnKey: string; // Which column we're sorting by
  direction: SortDirection;
};

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
  const { collectionId } = useAppSelector((state) => state.collection);
  const { handleCellClick, handleDimensionClick } =
    useChartFilters(collectionId);

  const [sortConfig, setSortConfig] = useState<SortConfig | null>(null);

  const handleSort = (columnKey: string) => {
    const nextDirection: SortDirection =
      !sortConfig || sortConfig.columnKey !== columnKey
        ? 'asc'
        : sortConfig.direction === 'asc'
          ? 'desc'
          : sortConfig.direction === 'desc'
            ? 'none'
            : 'asc';

    if (nextDirection === 'none') {
      setSortConfig(null);
    } else {
      setSortConfig({ columnKey, direction: nextDirection });
    }
  };

  const getSortIcon = (columnKey: string) => {
    if (
      !sortConfig ||
      sortConfig.columnKey !== columnKey ||
      sortConfig.direction === 'none'
    ) {
      return (
        <ChevronsUpDown className="w-3 h-3 opacity-0 group-hover:opacity-50" />
      );
    }
    return sortConfig.direction === 'asc' ? (
      <ChevronUp className="w-3 h-3 opacity-70" />
    ) : (
      <ChevronDown className="w-3 h-3 opacity-70" />
    );
  };

  // Sort rows based on column values
  const getSortedRows = () => {
    if (!sortConfig || sortConfig.direction === 'none') {
      return chartData.xValues; // Return original order
    }

    const sortedRows = [...chartData.xValues].sort((rowA, rowB) => {
      const scoreDataA = getScoreAt(chartData, sortConfig.columnKey, rowA);
      const scoreDataB = getScoreAt(chartData, sortConfig.columnKey, rowB);

      const scoreA = scoreDataA?.score ?? -Infinity;
      const scoreB = scoreDataB?.score ?? -Infinity;

      if (sortConfig.direction === 'asc') {
        return scoreA - scoreB;
      } else {
        return scoreB - scoreA;
      }
    });

    return sortedRows;
  };

  const tableData = {
    rows: getSortedRows(),
    cols: chartData.seriesValues,
    rowDimId: chartData.xKey,
    colDimId: chartData.seriesKey,
    totalRows: chartData.xValues.length,
    totalCols: chartData.seriesValues.length,
    is2d: chartData.is2d,
  };

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
              <th className="border-r border-b border-border px-2 py-1 sticky left-0 bg-background" />
              {tableData.cols.map((colValue: string, colIdx: number) => (
                <th
                  key={colValue}
                  className={cn(
                    colIdx !== tableData.cols.length - 1 && 'border-r',
                    'border-b border-border px-2 py-1 text-center font-normal text-primary relative max-w-[200px] group'
                  )}
                >
                  <div className="flex items-center justify-center gap-1">
                    <span
                      className="block truncate overflow-hidden text-ellipsis whitespace-nowrap cursor-pointer hover:bg-muted transition-colors rounded px-1 py-0.5"
                      title={
                        tableData.colDimId
                          ? `Filter to ${tableData.colDimId}: ${colValue}`
                          : undefined
                      }
                      onClick={() => {
                        if (tableData.is2d && tableData.colDimId) {
                          handleDimensionClick(tableData.colDimId, colValue);
                        }
                      }}
                    >
                      {chartData.seriesLabel && (
                        <span className="font-mono font-bold">
                          {chartData.seriesLabel}:{' '}
                        </span>
                      )}
                      <span className="font-mono">{colValue}</span>
                    </span>
                    <button
                      className="ml-1 p-0.5 rounded hover:bg-muted transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSort(colValue);
                      }}
                      title="Sort rows by this column"
                    >
                      {getSortIcon(colValue)}
                    </button>
                  </div>
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
                      handleDimensionClick(tableData.rowDimId, rowValue);
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
                          handleCellClick(
                            tableData.rowDimId,
                            rowValue,
                            tableData.is2d ? tableData.colDimId : undefined,
                            tableData.is2d ? colValue : undefined
                          );
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
