'use client';

import { useMemo, useState } from 'react';
import { useAppSelector } from '../store/hooks';
import Graph, { GraphDatum } from './Graph';
import { Plus, X } from 'lucide-react';

interface Tab {
  id: string;
  label: string;
}

export function GraphAreaWithTabs() {
  const graphData = useAppSelector((state) => state.experimentViewer.graphData);

  const [tabs, setTabs] = useState<Tab[]>([
    { id: '1', label: 'Graph 1' },
    { id: '2', label: 'Graph 2' },
    { id: '3', label: 'Graph 3' },
  ]);
  const [activeTabId, setActiveTabId] = useState('1');

  const addTab = () => {
    const newId = (Math.max(...tabs.map((t) => parseInt(t.id))) + 1).toString();
    const newTab = { id: newId, label: `Graph ${newId}` };
    setTabs([...tabs, newTab]);
    setActiveTabId(newId);
  };

  const removeTab = (tabId: string) => {
    if (tabs.length <= 1) return; // Don't allow removing the last tab

    const newTabs = tabs.filter((tab) => tab.id !== tabId);
    setTabs(newTabs);

    // If we're removing the active tab, switch to the first remaining tab
    if (activeTabId === tabId) {
      setActiveTabId(newTabs[0].id);
    }
  };

  return (
    <div className="h-1/2 flex flex-col">
      {/* Tab Bar */}
      <div className="flex items-end border-b border-border">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`group relative flex items-center px-2 py-1 text-xs font-medium cursor-pointer transition-colors rounded-t-md border-t border-l border-r mr-1 ${
              activeTabId === tab.id
                ? 'bg-background border-border text-primary -mb-px border-b'
                : 'bg-secondary/80 border-border text-muted-foreground hover:bg-muted hover:text-primary'
            }`}
            onClick={() => setActiveTabId(tab.id)}
          >
            <span className="font-mono">{tab.label}</span>
            {tabs.length > 1 && (
              <button
                className={`ml-1 -mr-1 p-0.5 rounded-sm opacity-0 group-hover:opacity-100 transition-opacity ${
                  activeTabId === tab.id
                    ? 'hover:bg-muted'
                    : 'hover:bg-accent'
                }`}
                onClick={(e) => {
                  e.stopPropagation();
                  removeTab(tab.id);
                }}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        ))}

        {/* Add Tab Button */}
        <button
          className="flex items-center justify-center p-1 ml-0 text-secondary hover:text-muted-foreground hover:bg-muted rounded transition-colors self-center"
          onClick={addTab}
        >
          <Plus className="h-3 w-3" />
        </button>
      </div>

      {/* Tab Content */}
      <div className="flex-1 bg-background border-l border-r border-b border-border rounded-b-md">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`h-full p-3 ${activeTabId === tab.id ? 'block' : 'hidden'}`}
          >
            {activeTabId === tab.id && tab.id === '1' && graphData && (
              <Graph data={graphData} type="bar" xKey="sample_id" yKey="avg" />
            )}
            {/* Empty divs for other tabs - you can fill these in later */}
            {activeTabId === tab.id && tab.id !== '1' && (
              <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
                Content for {tab.label} - to be implemented
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function GraphArea() {
  // experimentViewer slice
  const binStats = useAppSelector((state) => state.experimentViewer.binStats);
  const chartType = useAppSelector((state) => state.experimentViewer.chartType);

  // collection slice
  const innerBinKey = useAppSelector((state) => state.collection.innerBinKey);
  const outerBinKey = useAppSelector((state) => state.collection.outerBinKey);
  const dimensionsMap = useAppSelector((state) => state.collection.dimensionsMap);

  const graphData = useMemo(() => {
    const result: GraphDatum[] = [];

    if (!binStats) {
      return result;
    }

    // Get unique outer and inner dimension values with their IDs - matching ExperimentViewer logic
    const outerValuesWithIds: Array<{ id: string; value: string }> = [];
    const innerValuesWithIds: Array<{ id: string; value: string }> = [];

    if (outerBinKey) {
      const values = new Set<string>();
      Object.keys(binStats).forEach((key) => {
        const parts = key.split('|');
        parts.forEach((part) => {
          if (part.includes(',')) {
            const [dim, value] = part.split(',', 2);
            if (dim === outerBinKey) {
              values.add(value);
            }
          }
        });
      });
      outerValuesWithIds.push(
        ...Array.from(values).map((value) => ({ id: value, value }))
      );
    }

    if (innerBinKey) {
      const values = new Set<string>();
      Object.keys(binStats).forEach((key) => {
        const parts = key.split('|');
        parts.forEach((part) => {
          if (part.includes(',')) {
            const [dim, value] = part.split(',', 2);
            if (dim === innerBinKey) {
              values.add(value);
            }
          }
        });
      });
      innerValuesWithIds.push(
        ...Array.from(values).map((value) => ({ id: value, value }))
      );
    }

    // Helper to safely get bin key name
    const getBinKeyName = (binKeyId: string | undefined) => {
      if (!binKeyId || !dimensionsMap) {
        return 'Unknown';
      }
      return dimensionsMap[binKeyId]?.name ?? 'Unknown';
    };

    // Create graph data based on the available dimensions
    const hasOuter = outerValuesWithIds.length > 0;
    const hasInner = innerValuesWithIds.length > 0;

    if (hasOuter && hasInner) {
      // 2D case: create data for each combination
      outerValuesWithIds.forEach(({ id: outerId, value: outerValue }) => {
        innerValuesWithIds.forEach(({ id: innerId, value: innerValue }) => {
          const key = `${innerBinKey},${innerId}|${outerBinKey},${outerId}`;
          const stats = binStats[key];

          if (stats) {
            const scoreKey =
              Object.keys(stats).find((k) =>
                k.toLowerCase().includes('default')
              ) || Object.keys(stats)[0];
            const score = stats[scoreKey]?.mean ?? 0;

            result.push({
              value: score,
              [getBinKeyName(outerBinKey)]: outerValue,
              [getBinKeyName(innerBinKey)]: innerValue,
            });
          }
        });
      });
    } else if (hasOuter || hasInner) {
      // 1D case: use available dimension
      const valuesWithIds = hasOuter ? outerValuesWithIds : innerValuesWithIds;
      const dimId = hasOuter ? outerBinKey : innerBinKey;

      valuesWithIds.forEach(({ id, value }) => {
        const key = `${dimId},${id}`;
        const stats = binStats[key];

        if (stats) {
          const scoreKey =
            Object.keys(stats).find((k) =>
              k.toLowerCase().includes('default')
            ) || Object.keys(stats)[0];
          const score = stats[scoreKey]?.mean ?? 0;

          result.push({
            value: score,
            [getBinKeyName(dimId)]: value,
          });
        }
      });
    }

    return result;
  }, [binStats, innerBinKey, outerBinKey, dimensionsMap]);

  // Determine the x-axis key based on available dimensions
  const xKey = useMemo(() => {
    if (outerBinKey && dimensionsMap?.[outerBinKey]?.name) {
      return dimensionsMap[outerBinKey].name;
    }
    if (innerBinKey && dimensionsMap?.[innerBinKey]?.name) {
      return dimensionsMap[innerBinKey].name;
    }
    return 'Unknown';
  }, [innerBinKey, outerBinKey, dimensionsMap]);

  if (!graphData.length || !binStats) {
    return null;
  }

  return (
    <div className="h-2/5 flex flex-col border rounded-md overflow-hidden">
      <Graph
        data={graphData}
        type={chartType === 'line' ? 'line' : 'bar'}
        xKey={xKey}
        yKey="value"
      />
    </div>
  );
}
