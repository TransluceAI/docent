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
