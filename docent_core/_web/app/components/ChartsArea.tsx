'use client';

import { useMemo, useState, useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import Chart from './Chart';
import { ChartColumn, ChartLine, Plus, Table, X } from 'lucide-react';
import ChartSettings from './ChartSettings';
import {
  useCreateChartMutation,
  useUpdateChartMutation,
  useDeleteChartMutation,
} from '../api/experimentViewerApi';
import { getFieldsByPrefix } from '../utils/chartDataUtils';
import { ChartSpec } from '../types/collectionTypes';

export function ChartsArea() {
  const dispatch = useAppDispatch();

  const charts: ChartSpec[] = useAppSelector(
    (state) => state.experimentViewer.charts || []
  );
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const agentRunMetadataFields =
    useAppSelector((state) => state.collection.agentRunMetadataFields) || [];

  const [createChart] = useCreateChartMutation();
  const [updateChart] = useUpdateChartMutation();
  const [deleteChart] = useDeleteChartMutation();

  const metadataKeys = useMemo(
    () =>
      getFieldsByPrefix(agentRunMetadataFields, 'metadata.').filter(
        (key) => !key.startsWith('scores.')
      ),
    [agentRunMetadataFields]
  );
  const scoreKeys = useMemo(
    () => getFieldsByPrefix(agentRunMetadataFields, 'metadata.scores.'),
    [agentRunMetadataFields]
  );

  const [activeTabId, setActiveTabId] = useState('');
  const [editingTabId, setEditingTabId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');

  // Initialize active tab from localStorage or default to first chart
  useEffect(() => {
    if (charts.length > 0 && !activeTabId) {
      const storageKey = `docent-active-chart-${collectionId}`;
      const storedActiveTabId = localStorage.getItem(storageKey);

      // Check if stored chart still exists
      const storedChartExists =
        storedActiveTabId &&
        charts.some((chart) => chart.id === storedActiveTabId);

      const tabToSelect = storedChartExists ? storedActiveTabId : charts[0].id;
      setActiveTabId(tabToSelect);

      // Update localStorage if we're using a different chart than stored
      if (tabToSelect !== storedActiveTabId) {
        localStorage.setItem(storageKey, tabToSelect);
      }
    }
  }, [charts, collectionId, activeTabId]);

  // Helper function to update active tab and persist to localStorage
  const updateActiveTabId = (tabId: string) => {
    setActiveTabId(tabId);
    if (collectionId) {
      const storageKey = `docent-active-chart-${collectionId}`;
      localStorage.setItem(storageKey, tabId);
    }
  };

  const addTab = async () => {
    if (!collectionId) return;

    try {
      const response = await createChart({
        collectionId,
        seriesKey: undefined,
        xKey: metadataKeys.length > 0 ? metadataKeys[0] : '',
        yKey: scoreKeys.length > 0 ? scoreKeys[0] : '',
      }).unwrap();
      updateActiveTabId(response.chart_id);
    } catch (error) {
      console.error('Failed to create chart:', error);
    }
  };

  const removeTab = async (tabId: string) => {
    if (charts.length <= 1 || !collectionId) return; // Don't allow removing the last tab

    try {
      await deleteChart({ collectionId, chartId: tabId }).unwrap();

      // If we're removing the active tab, switch to the first remaining tab
      if (activeTabId === tabId) {
        const otherTabIds = charts
          .filter((chart) => chart.id !== tabId)
          .map((chart) => chart.id);
        updateActiveTabId(otherTabIds[0]);
      }
    } catch (error) {
      console.error('Failed to delete chart:', error);
    }
  };

  const handleTabDoubleClick = (chart: ChartSpec) => {
    setEditingTabId(chart.id);
    setEditingName(chart.name);
  };

  const handleNameSave = async (chartId: string) => {
    const chart = charts.find((c) => c.id === chartId);
    if (chart && editingName.trim() && collectionId) {
      try {
        await updateChart({
          collectionId,
          id: chartId,
          name: editingName.trim(),
          seriesKey: chart.seriesKey,
          xKey: chart.xKey,
          yKey: chart.yKey,
          chartType: chart.chartType,
        }).unwrap();
      } catch (error) {
        console.error('Failed to update chart:', error);
      }
    }
    setEditingTabId(null);
    setEditingName('');
  };

  const handleNameCancel = () => {
    setEditingTabId(null);
    setEditingName('');
  };

  const handleKeyDown = (e: React.KeyboardEvent, chartId: string) => {
    if (e.key === 'Enter') {
      handleNameSave(chartId);
    } else if (e.key === 'Escape') {
      handleNameCancel();
    }
  };

  const activeChart = charts.find((chart) => chart.id === activeTabId);

  return (
    <div className="max-h-[35%] flex flex-col">
      {/* Tab Bar */}
      <div className="flex items-end">
        {charts.map((chart: ChartSpec) => (
          <div
            key={chart.id}
            className={`group relative flex items-center px-2 py-1 text-xs font-medium cursor-pointer transition-colors rounded-t-md border-t border-l border-r mr-1 ${
              activeTabId === chart.id
                ? 'bg-background border-border text-primary -mb-px border-b'
                : 'bg-secondary/80 border-border text-muted-foreground hover:bg-muted hover:text-primary'
            }`}
            onClick={() => updateActiveTabId(chart.id)}
            onDoubleClick={() => handleTabDoubleClick(chart)}
          >
            {chart.chartType === 'bar' && (
              <ChartColumn className="inline w-4 h-4 mr-2" />
            )}
            {chart.chartType === 'line' && (
              <ChartLine className="inline w-4 h-4 mr-2" />
            )}
            {chart.chartType === 'table' && (
              <Table className="inline w-4 h-4 mr-2" />
            )}
            {editingTabId === chart.id ? (
              <input
                type="text"
                value={editingName}
                onChange={(e) => setEditingName(e.target.value)}
                onBlur={() => handleNameSave(chart.id)}
                onKeyDown={(e) => handleKeyDown(e, chart.id)}
                className="bg-transparent border-none outline-none font-mono text-xs min-w-0 w-20"
                autoFocus
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span className="font-mono">{chart.name}</span>
            )}
            {charts.length > 1 && (
              <button
                className={`ml-1 -mr-1 p-0.5 rounded-sm opacity-0 group-hover:opacity-100 transition-opacity ${
                  activeTabId === chart.id
                    ? 'hover:bg-muted'
                    : 'hover:bg-accent'
                }`}
                onClick={(e) => {
                  e.stopPropagation();
                  removeTab(chart.id);
                }}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        ))}

        {/* Add Tab Button */}
        <button
          className="flex items-center justify-center p-1 ml-0 text-muted-foreground bg-muted rounded transition-colors self-center"
          onClick={addTab}
        >
          <Plus className="h-3 w-3" />
        </button>
      </div>

      {activeChart && (
        <div className="flex flex-col flex-1 bg-background border border-border rounded-b-md rounded-tr-md min-h-0">
          <ChartSettings
            chart={activeChart}
            onChange={async (chart) => {
              if (collectionId) {
                try {
                  await updateChart({ collectionId, ...chart }).unwrap();
                } catch (error) {
                  console.error('Failed to update chart:', error);
                }
              }
            }}
          />
          <Chart chart={activeChart} />
        </div>
      )}
    </div>
  );
}
