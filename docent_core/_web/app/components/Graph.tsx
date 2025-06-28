'use client';

import { ResponsiveBar } from '@nivo/bar';
import { ResponsiveLine } from '@nivo/line';
import { useMemo } from 'react';

type GraphValue = string | number;

export interface GraphDatum {
  [key: string]: GraphValue;
}

interface SpecificGraphProps {
  data: GraphDatum[];
  xKey: string;
  yKey: string;
}

interface GraphProps extends SpecificGraphProps {
  type: 'bar' | 'line';
}

export default function Graph({ data, xKey, yKey, type }: GraphProps) {
  if (type === 'bar') {
    return <BarGraph data={data} xKey={xKey} yKey={yKey} />;
  } else if (type === 'line') {
    return <LineGraph data={data} xKey={xKey} yKey={yKey} />;
  }
  return null;
}

function BarGraph({ data, xKey, yKey }: SpecificGraphProps) {
  const [barData, seriesKeys] = useMemo(() => {
    // Create mapping from x-values to (stringified series value, y-value) pairs
    const byXs: Record<GraphValue, [string, GraphValue][]> = {};
    const seriesKeys: Set<string> = new Set();
    for (const row of data) {
      const xValue = row[xKey];
      if (!byXs[xValue]) {
        byXs[xValue] = [];
      }
      if (Object.keys(row).length > 2) {
        // If there are multiple series, look for each one
        for (const key in row) {
          if (key !== xKey && key !== yKey) {
            byXs[xValue].push([String(row[key]), row[yKey]]);
            seriesKeys.add(String(row[key]));
          }
        }
      } else {
        // If there is only one series, use the yKey as the series key
        byXs[xValue].push([yKey, row[yKey]]);
        seriesKeys.add(yKey);
      }
    }
    const barData = Object.entries(byXs).map(([xValue, yValues]) => {
      // Merge all key-value pairs for this xValue into a single object
      const expanded = yValues.reduce(
        (acc, [k, v]) => {
          acc[k] = v;
          return acc;
        },
        {} as Record<string, GraphValue>
      );
      return { [xKey]: xValue, ...expanded };
    });
    return [barData, Array.from(seriesKeys)];
  }, [data, xKey, yKey]);

  return (
    <ResponsiveBar /* or Bar for fixed dimensions */
      animate={false}
      data={barData}
      keys={seriesKeys}
      indexBy={xKey}
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
      axisBottom={{ legend: xKey, legendOffset: 32 }}
      axisLeft={{ legend: yKey, legendOffset: -40 }}
      margin={{ top: 20, right: 130, bottom: 50, left: 60 }}
      groupMode="grouped"
    />
  );
}

function LineGraph({ data, xKey, yKey }: SpecificGraphProps) {
  const lineData = useMemo(() => {
    // Map from series key to (x-value, y-value) pairs
    const serieses: Record<string, { x: GraphValue; y: GraphValue }[]> = {};
    for (const row of data) {
      for (const key in row) {
        const seriesValue = row[key];
        if (key != xKey && key != yKey) {
          // Then this is a series
          if (!serieses[seriesValue]) {
            serieses[seriesValue] = [];
          }
          serieses[seriesValue].push({ x: row[xKey], y: row[yKey] });
        }
      }
    }

    return Object.entries(serieses).map(([seriesValue, data]) => ({
      id: seriesValue,
      data,
    }));
  }, [data, xKey, yKey]);

  return (
    <ResponsiveLine /* or Line for fixed dimensions */
      animate={false}
      data={lineData}
      margin={{ top: 20, right: 110, bottom: 50, left: 60 }}
      yScale={{
        type: 'linear',
        min: 'auto',
        max: 'auto',
        stacked: false,
        reverse: false,
      }}
      axisBottom={{ legend: xKey, legendOffset: 36 }}
      axisLeft={{ legend: yKey, legendOffset: -40 }}
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
  );
}
