import { toPng } from 'html-to-image';
import { parseChartData } from './chartDataUtils';
import { ChartSpec } from '../types/collectionTypes';
import { TaskStats } from '../types/experimentViewerTypes';

export const getChartExportElementId = (chartId: string) =>
  `chart-export-${chartId}`;

export async function exportChartToPng(chartId: string, filename: string) {
  const rootId = getChartExportElementId(chartId);
  const exportRoot = document.getElementById(rootId);
  if (!exportRoot) return;

  const bgVar = getComputedStyle(document.documentElement)
    .getPropertyValue('--background')
    .trim();
  const backgroundColor = bgVar ? `hsl(${bgVar})` : undefined;

  const tableEl = exportRoot.querySelector('table') as HTMLElement | null;
  const svgEl = exportRoot.querySelector('svg') as SVGSVGElement | null;
  const nodeToCapture: HTMLElement =
    (tableEl as HTMLElement) || (svgEl as unknown as HTMLElement) || exportRoot;

  const targetScrollWidth =
    (nodeToCapture as any).scrollWidth || nodeToCapture.clientWidth;
  const targetScrollHeight =
    (nodeToCapture as any).scrollHeight || nodeToCapture.clientHeight;

  const dataUrl = await toPng(nodeToCapture, {
    cacheBust: true,
    backgroundColor,
    pixelRatio: 3,
    width: targetScrollWidth,
    height: targetScrollHeight,
    style: {
      width: `${targetScrollWidth}px`,
      height: `${targetScrollHeight}px`,
    },
  });

  const link = document.createElement('a');
  link.download = `${filename || 'chart'}.png`;
  link.href = dataUrl;
  link.click();
}

function escapeCsvField(value: any): string {
  if (value === null || value === undefined) return '';
  const str = String(value);
  if (str.includes('"')) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  if (str.includes(',') || str.includes('\n')) {
    return `"${str}"`;
  }
  return str;
}

export function exportChartToCsv(
  chart: ChartSpec,
  relevantBinStats: Record<string, TaskStats> | undefined,
  filename: string
) {
  const chartData = parseChartData(relevantBinStats, chart);

  const headers: string[] = [];
  const xHeader = chartData.xLabel || chartData.xKey || 'x';
  headers.push(xHeader);
  if (chartData.is2d) {
    const seriesHeader =
      chartData.seriesLabel || chartData.seriesKey || 'series';
    headers.push(seriesHeader);
  }
  // Determine whether to include n/ci columns based on data presence
  let includeN = false;
  let includeCi = false;
  outer: for (const seriesValue of chartData.seriesValues) {
    for (const xValue of chartData.xValues) {
      const d = chartData.data[seriesValue]?.[xValue];
      if (d?.n !== null && d?.n !== undefined) includeN = true;
      if (d?.ci !== null && d?.ci !== undefined) includeCi = true;
      if (includeN && includeCi) break outer;
    }
  }

  const yHeader = chartData.yLabel || chartData.yKey || 'score';
  headers.push(yHeader);
  if (includeN) headers.push('n');
  if (includeCi) headers.push('ci');

  const rows: string[] = [];
  rows.push(headers.join(','));

  for (const xValue of chartData.xValues) {
    for (const seriesValue of chartData.seriesValues) {
      const scoreData = chartData.data[seriesValue]?.[xValue] || {
        score: null,
        n: null,
        ci: null,
      };

      const record: (string | number | null)[] = [];
      record.push(xValue);
      if (chartData.is2d) {
        record.push(seriesValue);
      }
      record.push(scoreData?.score ?? null);
      if (includeN) record.push(scoreData?.n ?? null);
      if (includeCi) record.push(scoreData?.ci ?? null);

      rows.push(record.map(escapeCsvField).join(','));
    }
  }

  const csvContent = rows.join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${filename || 'chart'}.csv`;
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
    if (link && link.parentNode) {
      link.parentNode.removeChild(link);
    }
  }, 500);
}
