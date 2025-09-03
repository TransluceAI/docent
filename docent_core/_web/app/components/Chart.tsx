'use client';

import { ResponsiveBar } from '@nivo/bar';
import { ResponsiveLine } from '@nivo/line';
import { useMemo, useCallback } from 'react';
import TableChart from './TableChart';
import ChartContainer from './ChartContainer';
import { ChartSpec } from '../types/collectionTypes';
import { useAppSelector } from '../store/hooks';
import { ChartData, getScoreAt, parseChartData } from '../utils/chartDataUtils';
import { useGetChartDataQuery } from '../api/chartApi';
import { useChartFilters } from '../../hooks/use-chart-filters';
import { CustomBarTooltip, CustomLineTooltip } from './CustomTooltips';
import { Loader2 } from 'lucide-react';

type GraphValue = string | number;

export interface GraphDatum {
  [key: string]: GraphValue;
}

export default function Chart({ chart }: { chart: ChartSpec }) {
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const { handleCellClick } = useChartFilters(collectionId);

  const {
    data: chartDataResponse,
    isLoading,
    error,
  } = useGetChartDataQuery(
    {
      collectionId: collectionId!,
      chartId: chart.id,
    },
    {
      skip: !collectionId,
    }
  );

  const relevantBinStats = chartDataResponse?.result?.binStats;

  const maxValues = 100;

  // Parse data once for all chart types
  const chartData: ChartData = useMemo(
    () => parseChartData(relevantBinStats, chart, { maxValues }),
    [
      relevantBinStats,
      chart.x_key,
      chart.y_key,
      chart.series_key,
      chart.x_label,
      chart.y_label,
      chart.series_label,
    ]
  );

  // Handle loading and error states after all hooks
  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-4 text-sm">
        <Loader2 size={16} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center p-4 text-sm">
        Error loading chart
      </div>
    );
  }

  if (chart.chart_type === 'bar') {
    return <BarChart chartData={chartData} handleCellClick={handleCellClick} />;
  } else if (chart.chart_type === 'line') {
    return (
      <LineChart chartData={chartData} handleCellClick={handleCellClick} />
    );
  } else if (chart.chart_type === 'table') {
    return <TableChart chartData={chartData} />;
  }
  return null;
}

type NivoBar = Record<string, any>;

function BarChart({
  chartData,
  handleCellClick,
}: {
  chartData: ChartData;
  handleCellClick: (
    xKey: string,
    xValue: string,
    seriesKey?: string,
    seriesValue?: string
  ) => void;
}) {
  const theme = computeChartTheme();
  const data: NivoBar[] = useMemo(
    () =>
      chartData.xValues.map((xValue) => {
        const barItem: NivoBar = { [chartData.xKey]: xValue };

        for (const seriesName of chartData.seriesValues) {
          const scoreData = getScoreAt(chartData, seriesName, xValue);
          if (scoreData) {
            barItem[seriesName] = scoreData.score;
          }
        }

        return barItem;
      }),
    [chartData]
  );

  const handleBarClick = useCallback(
    (bar: any) => {
      const xValue = bar.indexValue;
      const seriesValue = bar.id;

      if (chartData.xKey) {
        handleCellClick(
          chartData.xKey,
          xValue,
          chartData.is2d ? chartData.seriesKey : undefined,
          chartData.is2d ? seriesValue : undefined
        );
      }
    },
    [chartData, handleCellClick]
  );

  return (
    <ChartContainer minHeight={200}>
      <ResponsiveBar
        animate={false}
        data={data}
        keys={chartData.seriesValues}
        indexBy={chartData.xKey}
        labelSkipWidth={12}
        labelSkipHeight={12}
        theme={theme}
        onClick={handleBarClick}
        tooltip={CustomBarTooltip}
        legends={
          chartData.seriesValues.length > 1
            ? [
                {
                  dataFrom: 'keys',
                  anchor: 'bottom-right',
                  direction: 'column',
                  translateX: 120,
                  itemsSpacing: 3,
                  itemWidth: 100,
                  itemHeight: 16,
                },
              ]
            : []
        }
        axisBottom={{
          tickRotation: -90,
          legend: chartData.xLabel,
          legendOffset: 32,
          tickValues: getTickValues(chartData.xValues),
        }}
        axisLeft={{ legend: chartData.yLabel, legendOffset: -40 }}
        margin={{
          top: 20,
          right: chartData.seriesValues.length > 1 ? 130 : 20,
          bottom: 50,
          left: 60,
        }}
        groupMode="grouped"
      />
    </ChartContainer>
  );
}

type NivoLineSeries = {
  id: string;
  data: { x: any; y: number | null }[];
};

function LineChart({
  chartData,
  handleCellClick,
}: {
  chartData: ChartData;
  handleCellClick: (
    xKey: string,
    xValue: string,
    seriesKey?: string,
    seriesValue?: string
  ) => void;
}) {
  const theme = computeChartTheme();
  const data: NivoLineSeries[] = useMemo(() => {
    const seriesMap: Record<string, { x: any; y: number | null }[]> = {};

    chartData.seriesValues.forEach((seriesName) => {
      chartData.xValues.forEach((xValue) => {
        const scoreData = getScoreAt(chartData, seriesName, xValue);
        if (!seriesMap[seriesName]) seriesMap[seriesName] = [];
        seriesMap[seriesName].push({ x: xValue, y: scoreData?.score ?? null });
      });
    });

    return Object.entries(seriesMap).map(([id, data]) => ({ id, data }));
  }, [chartData]);

  const handlePointClick = useCallback(
    (point: any) => {
      const xValue = point.data.x;
      const seriesValue = point.seriesId;

      if (chartData.xKey) {
        handleCellClick(
          chartData.xKey,
          xValue,
          chartData.is2d ? chartData.seriesKey : undefined,
          chartData.is2d ? seriesValue : undefined
        );
      }
    },
    [chartData, handleCellClick]
  );

  if (!chartData.xKey || data.length === 0) {
    return null;
  }

  return (
    <ChartContainer minHeight={200}>
      <ResponsiveLine
        animate={false}
        data={data}
        onClick={handlePointClick}
        tooltip={CustomLineTooltip}
        margin={{
          top: 20,
          right: chartData.seriesValues.length > 1 ? 110 : 20,
          bottom: 50,
          left: 60,
        }}
        theme={theme}
        yScale={{
          type: 'linear',
          min: 'auto',
          max: 'auto',
          stacked: false,
          reverse: false,
        }}
        axisBottom={{
          tickRotation: -90,
          legend: chartData.xLabel,
          legendOffset: 36,
          tickValues: getTickValues(chartData.xValues),
        }}
        axisLeft={{ legend: chartData.yLabel, legendOffset: -40 }}
        pointSize={10}
        pointColor={{ theme: 'background' }}
        pointBorderWidth={2}
        pointBorderColor={{ from: 'seriesColor' }}
        pointLabelYOffset={-12}
        enableTouchCrosshair={true}
        useMesh={true}
        legends={
          chartData.seriesValues.length > 1
            ? [
                {
                  anchor: 'bottom-right',
                  direction: 'column',
                  translateX: 100,
                  itemWidth: 80,
                  itemHeight: 22,
                  symbolShape: 'circle',
                },
              ]
            : []
        }
      />
    </ChartContainer>
  );
}

const getTickValues = (values: (string | number)[]) => {
  if (values.length <= 20) return values;
  const step = Math.ceil(values.length / 20);
  return values.filter((_, index) => index % step === 0);
};

function getCssVarValue(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
}

function getCssHsl(name: string): string | undefined {
  const raw = getCssVarValue(name);
  if (!raw) return undefined;
  return `hsl(${raw})`;
}

// CSS vars are not available when rendering for export, so we need to get the acutal HSL values
function computeChartTheme() {
  const mutedForeground = getCssHsl('--muted-foreground');
  const foreground = getCssHsl('--foreground');
  const card = getCssHsl('--card');
  const cardForeground = getCssHsl('--card-foreground');
  const border = getCssHsl('--border');

  return {
    axis: {
      ticks: {
        text: {
          fill: mutedForeground,
        },
      },
      legend: {
        text: {
          fill: foreground,
        },
      },
    },
    legends: {
      text: {
        fill: mutedForeground,
      },
    },
    tooltip: {
      container: {
        background: card,
        color: cardForeground,
        border: `1px solid ${border}`,
        borderRadius: '6px',
      },
    },
  } as const;
}
