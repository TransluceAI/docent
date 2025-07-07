'use client';

import { ResponsiveBar } from '@nivo/bar';
import { ResponsiveLine } from '@nivo/line';
import { useMemo } from 'react';
import TableChart from './TableChart';
import ChartContainer from './ChartContainer';
import { ChartSpec } from '../types/collectionTypes';
import { useAppSelector } from '../store/hooks';
import { TaskStats } from '../types/experimentViewerTypes';
import {
  ChartData,
  ScoreData,
  getScoreFromStats,
  getScoreAt,
} from '../utils/chartDataUtils';

type GraphValue = string | number;

export interface GraphDatum {
  [key: string]: GraphValue;
}

export default function Chart({ chart }: { chart: ChartSpec }) {
  const allBinStats = useAppSelector(
    (state) => state.experimentViewer.binStats
  );
  let binStats: Record<string, TaskStats> | undefined;
  if (chart.seriesKey) {
    binStats = allBinStats?.[`${chart.xKey}|${chart.seriesKey}`];
  } else {
    binStats = allBinStats?.[`${chart.xKey}`];
  }

  const maxValues = 100;

  // Parse data once for all chart types
  const chartData: ChartData = useMemo(() => {
    if (!binStats) {
      return {
        data: {},
        xValues: [],
        seriesValues: [],
        xKey: chart.xKey,
        seriesKey: chart.seriesKey ?? 'Score',
        yKey: chart.yKey,
        is2d: Boolean(chart.seriesKey),
      };
    }

    const xValueSet = new Set<string>();
    const seriesValueSet = new Set<string>();

    // Indexed like data[seriesValue][xValue]
    const parsedData: Record<string, Record<string, ScoreData>> = {};

    Object.entries(binStats).forEach(([key, stats]) => {
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
      const seriesValue = chart.seriesKey
        ? dimensions[chart.seriesKey]
        : chart.yKey;

      const xValue = dimensions[chart.xKey];
      if (!xValue || !seriesValue) return;

      xValueSet.add(xValue);
      seriesValueSet.add(seriesValue);

      if (!parsedData[seriesValue]) parsedData[seriesValue] = {};
      parsedData[seriesValue][xValue] = getScoreFromStats(stats, chart.yKey);
    });

    const xValues = Array.from(xValueSet).slice(0, maxValues);
    const seriesValues = Array.from(seriesValueSet).slice(0, maxValues);

    return {
      data: parsedData,
      xValues,
      seriesValues,
      xKey: chart.xKey,
      seriesKey: chart.seriesKey ?? 'Score',
      yKey: chart.yKey,
      is2d: Boolean(chart.seriesKey),
    };
  }, [binStats, chart.xKey, chart.yKey, chart.seriesKey]);

  if (chart.chartType === 'bar') {
    return <BarChart chartData={chartData} />;
  } else if (chart.chartType === 'line') {
    return <LineChart chartData={chartData} />;
  } else if (chart.chartType === 'table') {
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
        legends={[
          {
            dataFrom: 'keys',
            anchor: 'bottom-right',
            direction: 'column',
            translateX: 120,
            itemsSpacing: 3,
            itemWidth: 100,
            itemHeight: 16,
          },
        ]}
        axisBottom={{ legend: chartData.xKey, legendOffset: 32 }}
        axisLeft={{ legend: chartData.yKey, legendOffset: -40 }}
        margin={{ top: 20, right: 130, bottom: 50, left: 60 }}
        groupMode="grouped"
      />
    </ChartContainer>
  );
}

type NivoLineSeries = {
  id: string;
  data: { x: any; y: number }[];
};

function LineChart({ chartData }: { chartData: ChartData }) {
  const data: NivoLineSeries[] = useMemo(() => {
    const seriesMap: Record<string, { x: any; y: number }[]> = {};

    chartData.seriesValues.forEach((seriesName) => {
      chartData.xValues.forEach((xValue) => {
        const scoreData = getScoreAt(chartData, seriesName, xValue);
        if (scoreData) {
          if (!seriesMap[seriesName]) seriesMap[seriesName] = [];
          seriesMap[seriesName].push({ x: xValue, y: scoreData.score });
        }
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
        margin={{ top: 20, right: 110, bottom: 50, left: 60 }}
        yScale={{
          type: 'linear',
          min: 'auto',
          max: 'auto',
          stacked: false,
          reverse: false,
        }}
        axisBottom={{ legend: chartData.xKey, legendOffset: 36 }}
        axisLeft={{ legend: chartData.yKey, legendOffset: -40 }}
        pointSize={10}
        pointColor={{ theme: 'background' }}
        pointBorderWidth={2}
        pointBorderColor={{ from: 'seriesColor' }}
        pointLabelYOffset={-12}
        enableTouchCrosshair={true}
        useMesh={true}
        legends={[
          {
            anchor: 'bottom-right',
            direction: 'column',
            translateX: 100,
            itemWidth: 80,
            itemHeight: 22,
            symbolShape: 'circle',
          },
        ]}
      />
    </ChartContainer>
  );
}
