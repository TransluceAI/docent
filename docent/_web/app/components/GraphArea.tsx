'use client';

import { useMemo, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { useAppSelector } from '../store/hooks';
import Graph, { GraphDatum } from './Graph';

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
      <div className="flex items-end border-b border-gray-200">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`group relative flex items-center px-2 py-1 text-xs font-medium cursor-pointer transition-colors rounded-t-md border-t border-l border-r mr-1 ${
              activeTabId === tab.id
                ? 'bg-white border-gray-200 text-gray-800 -mb-px border-b border-b-white'
                : 'bg-gray-50/80 border-gray-200 text-gray-600 hover:bg-gray-100 hover:text-gray-800'
            }`}
            onClick={() => setActiveTabId(tab.id)}
          >
            <span className="font-mono">{tab.label}</span>
            {tabs.length > 1 && (
              <button
                className={`ml-1 -mr-1 p-0.5 rounded-sm opacity-0 group-hover:opacity-100 transition-opacity ${
                  activeTabId === tab.id
                    ? 'hover:bg-gray-100'
                    : 'hover:bg-gray-200'
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
          className="flex items-center justify-center p-1 ml-0 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors self-center"
          onClick={addTab}
        >
          <Plus className="h-3 w-3" />
        </button>
      </div>

      {/* Tab Content */}
      <div className="flex-1 bg-white border-l border-r border-b border-gray-200 rounded-b-md">
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
              <div className="h-full flex items-center justify-center text-xs text-gray-500">
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
  const statMarginals = useAppSelector(
    (state) => state.experimentViewer.statMarginals
  );
  const filtersMap = useAppSelector(
    (state) => state.experimentViewer.filtersMap
  );
  const chartType = useAppSelector((state) => state.experimentViewer.chartType);

  // frame slice
  const innerDimId = useAppSelector((state) => state.frame.innerDimId);
  const outerDimId = useAppSelector((state) => state.frame.outerDimId);
  const dimensionsMap = useAppSelector((state) => state.frame.dimensionsMap);

  const innerDimName = innerDimId
    ? dimensionsMap?.[innerDimId]?.name || innerDimId
    : innerDimId || '';

  const graphData = useMemo(() => {
    const result: GraphDatum[] = [];

    for (const [k, v] of Object.entries(statMarginals ?? {})) {
      const parts = k.split('|');
      if (parts.length > 2) {
        console.error('Expected at most 2 parts, got', parts.length);
        continue;
      }

      // const curDatum: GraphDatum = { value: Object.values(v)[0].n ?? 0 };
      const curDatum: GraphDatum = { value: Object.values(v)[0].mean ?? 0 };
      for (const loc of parts) {
        const [dimId, filterId] = loc.split(',');
        const dimName = dimensionsMap?.[dimId]?.name || dimId;
        const filterName = filtersMap?.[filterId]?.name || filterId;
        curDatum[dimName] = filterName;
      }

      result.push(curDatum);
    }

    return result;
  }, [statMarginals, innerDimId, outerDimId, dimensionsMap, filtersMap]);

  return (
    graphData.length > 0 &&
    innerDimId && (
      <div className="h-2/5 flex flex-col border rounded-md overflow-hidden">
        <Graph
          data={graphData}
          type={chartType === 'line' ? 'line' : 'bar'}
          xKey={innerDimName}
          yKey="value"
        />
      </div>
    )
  );
}
