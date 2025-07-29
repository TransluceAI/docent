'use client';

import { ResponsiveBar } from '@nivo/bar';
import { ResponsiveLine } from '@nivo/line';
import { useMemo } from 'react';
import TableChart from './TableChart';
import ChartContainer from './ChartContainer';
import { ChartSpec } from '../types/collectionTypes';
import { useAppSelector } from '../store/hooks';
import { ChartData, ScoreData, getScoreAt } from '../utils/chartDataUtils';
import { useGetChartDataQuery } from '../api/chartApi';

type GraphValue = string | number;

export interface GraphDatum {
  [key: string]: GraphValue;
}

export default function Chart({ chart }: { chart: ChartSpec }) {
  const collectionId = useAppSelector((state) => state.collection.collectionId);

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
  const chartData: ChartData = useMemo(() => {
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
      // Dimensions and values for this bin
      const dimensions: Record<string, string> = {};

      // Key format is key1,value1|key2,value2
      for (const part of key.split('|')) {
        const [dim, value] = part.split(',', 2);
        if (dim && value) {
          dimensions[dim] = value;
        }
      }

      // If the chart doesn't have a seriesKey, there will be one series with a name equal to the yKey
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
  }, [relevantBinStats, chart.x_key, chart.y_key, chart.series_key]);

  // Handle loading and error states after all hooks
  if (isLoading) {
    return <div>Loading chart data...</div>;
  }

  if (error) {
    return <div>Error loading chart data</div>;
  }

  if (chart.chart_type === 'bar') {
    return <BarChart chartData={chartData} />;
  } else if (chart.chart_type === 'line') {
    return <LineChart chartData={chartData} />;
  } else if (chart.chart_type === 'table') {
    return <TableChart chartData={chartData} />;
  }
  return null;
}

type NivoBar = Record<string, any>;

function BarChart({ chartData }: { chartData: ChartData }) {
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

  return (
    <ChartContainer minHeight={200}>
      <ResponsiveBar
        animate={false}
        data={data}
        keys={chartData.seriesValues}
        indexBy={chartData.xKey}
        labelSkipWidth={12}
        labelSkipHeight={12}
        theme={chartTheme}
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

function LineChart({ chartData }: { chartData: ChartData }) {
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

  if (!chartData.xKey || data.length === 0) {
    return null;
  }

  return (
    <ChartContainer minHeight={200}>
      <ResponsiveLine
        animate={false}
        data={data}
        margin={{
          top: 20,
          right: chartData.seriesValues.length > 1 ? 110 : 20,
          bottom: 50,
          left: 60,
        }}
        theme={chartTheme}
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

const chartTheme = {
  axis: {
    ticks: {
      text: {
        fill: 'hsl(var(--muted-foreground))',
      },
    },
    legend: {
      text: {
        fill: 'hsl(var(--foreground))',
      },
    },
  },
  legends: {
    text: {
      fill: 'hsl(var(--muted-foreground))',
    },
  },
  tooltip: {
    container: {
      background: 'hsl(var(--card))',
      color: 'hsl(var(--card-foreground))',
      border: '1px solid hsl(var(--border))',
      borderRadius: '6px',
    },
  },
};
