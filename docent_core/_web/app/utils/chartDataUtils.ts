import {
  TaskStats,
  TranscriptMetadataField,
} from '../types/experimentViewerTypes';

export interface ScoreData {
  score: number;
  n?: number;
  ci?: number | null;
  scoreKey?: string;
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
  seriesKey: string;
  yKey: string;
  is2d: boolean;
}

/**
 * Extract score information from TaskStats
 */
export function getScoreFromStats(
  stats: TaskStats,
  scoreKey?: string
): ScoreData {
  if (!stats) return { score: 0, scoreKey: '' };

  if (!scoreKey) {
    scoreKey =
      Object.keys(stats).find((k) => k.toLowerCase().includes('default')) ||
      Object.keys(stats)[0];
  }

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
}

// ------------------------------------------------------------------
// Access helpers
// ------------------------------------------------------------------

export function getScoreAt(
  chartData: ChartData,
  seriesName: string,
  xValue: string
): ScoreData | undefined {
  const row = chartData.data[seriesName];
  if (!row) return undefined;
  return (row as Record<string, ScoreData>)[xValue!];
}

export function getFieldsByPrefix(
  fields: TranscriptMetadataField[],
  prefix: string
) {
  return fields
    .map((field) => field.name)
    .filter((name) => name.startsWith(prefix))
    .map((name) => name.replace(prefix, ''));
}
