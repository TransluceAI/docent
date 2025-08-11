export interface ScoreData {
  score: number | null;
  n: number | null;
  ci: number | null;
}

/**
 * Intermediate data structure between binStats and chart-specific data structures
 */
export interface ChartData {
  // Indexed like data[seriesValue][xValue]
  data: Record<string, Record<string, ScoreData>>;
  xValues: string[];
  seriesValues: string[];
  xKey: string;
  xLabel: string;
  seriesKey: string;
  seriesLabel: string;
  yKey: string;
  yLabel: string;
  is2d: boolean;
}

// ------------------------------------------------------------------
// Access helpers
// ------------------------------------------------------------------

export function getScoreAt(
  chartData: ChartData,
  seriesName: string,
  xValue: string
): ScoreData | null {
  const row = chartData.data[seriesName];
  if (!row) return null;
  return (row as Record<string, ScoreData>)[xValue] ?? null;
}

// ------------------------------------------------------------------
// Parsing helpers
// ------------------------------------------------------------------

import { ChartSpec } from '../types/collectionTypes';
import { TaskStats } from '../types/experimentViewerTypes';

/**
 * Convert backend binStats to the intermediate ChartData structure used by charts and exports.
 *
 * - Parses composite bin keys ("key1,value1|key2,value2") into dimension values
 * - Produces a dense mapping data[seriesValue][xValue] -> { score, n, ci }
 * - Caps x/series lists to at most maxValues to match UI constraints
 *
 * Parameters:
 * - relevantBinStats: map of bin key -> TaskStats from the chart data API
 * - chart: the chart specification (x/series/y IDs and labels)
 * - opts.maxValues: optional cap for number of x/series values (default 100)
 */
export function parseChartData(
  relevantBinStats: Record<string, TaskStats> | undefined,
  chart: ChartSpec,
  opts?: { maxValues?: number }
): ChartData {
  const maxValues = opts?.maxValues ?? 100;

  if (!relevantBinStats) {
    return {
      data: {},
      xValues: [],
      seriesValues: [],
      xKey: chart.x_key || '',
      xLabel: chart.x_label || chart.x_key || '',
      seriesKey: chart.series_key ?? 'Score',
      seriesLabel: chart.series_label || chart.series_key || '',
      yKey: chart.y_key || '',
      yLabel: chart.y_label || chart.y_key || '',
      is2d: Boolean(chart.series_key),
    };
  }

  const xValueSet = new Set<string>();
  const seriesValueSet = new Set<string>();

  // Indexed like data[seriesValue][xValue]
  const parsedData: Record<string, Record<string, ScoreData>> = {};

  Object.entries(relevantBinStats).forEach(([key, stats]) => {
    const dimensions: Record<string, string> = {};

    // Key format is key1,value1|key2,value2
    for (const part of key.split('|')) {
      const [dim, value] = part.split(',', 2);
      if (dim && value) {
        dimensions[dim] = value;
      }
    }

    const seriesValue = chart.series_key
      ? dimensions[chart.series_key]
      : chart.y_label;

    const xValue = chart.x_key ? dimensions[chart.x_key] : undefined;
    if (!xValue || !seriesValue) return;

    xValueSet.add(xValue);
    seriesValueSet.add(seriesValue);

    if (!parsedData[seriesValue]) parsedData[seriesValue] = {};
    parsedData[seriesValue][xValue] = {
      score: stats.mean,
      n: stats.n,
      ci: stats.ci,
    };
  });

  const xValues = Array.from(xValueSet).slice(0, maxValues);
  const seriesValues = Array.from(seriesValueSet).slice(0, maxValues);

  return {
    data: parsedData,
    xValues,
    seriesValues,
    xKey: chart.x_key || '',
    xLabel: chart.x_label || chart.x_key || '',
    seriesKey: chart.series_key ?? 'Score',
    seriesLabel: chart.series_label || chart.series_key || '',
    yKey: chart.y_key || '',
    yLabel: chart.y_label || chart.y_key || '',
    is2d: Boolean(chart.series_key),
  };
}
