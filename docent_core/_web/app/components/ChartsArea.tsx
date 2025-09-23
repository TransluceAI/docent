'use client';

import { useState, useEffect } from 'react';
import { useAppSelector, useAppDispatch } from '../store/hooks';
import dynamic from 'next/dynamic';

const Chart = dynamic(() => import('./Chart'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center p-4">
      <Loader2 size={16} className="animate-spin text-muted-foreground" />
    </div>
  ),
});
import {
  ChartColumn,
  ChartLine,
  Plus,
  Table,
  X,
  RefreshCw,
  Loader2,
} from 'lucide-react';
import ChartSettings from './ChartSettings';
import { getChartExportElementId } from '../utils/exportChart';
import {
  useCreateChartMutation,
  useUpdateChartMutation,
  useDeleteChartMutation,
  useGetChartsQuery,
  chartApi,
} from '../api/chartApi';
import { ChartSpec } from '../types/collectionTypes';
import { skipToken } from '@reduxjs/toolkit/query';
import { cn } from '@/lib/utils';

export function ChartsArea() {
  const collectionId = useAppSelector((state) => state.collection.collectionId);

  const {
    data: charts = [],
    isLoading,
    error,
  } = useGetChartsQuery(collectionId ? { collectionId } : skipToken);

  const [createChart] = useCreateChartMutation();
  const [updateChart] = useUpdateChartMutation();
  const [deleteChart] = useDeleteChartMutation();
  const dispatch = useAppDispatch();

  const handleRefresh = () => {
    dispatch(
      chartApi.util.invalidateTags(['Charts', 'ChartData', 'ChartMetadata'])
    );
  };

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
  const updateActiveTabId = (tabId: string | null) => {
    const nextTabId = tabId ?? '';
    setActiveTabId(nextTabId);

    if (!collectionId) {
      return;
    }

    const storageKey = `docent-active-chart-${collectionId}`;
    if (tabId) {
      localStorage.setItem(storageKey, tabId);
    } else {
      localStorage.removeItem(storageKey);
    }
  };

  const addTab = async () => {
    if (!collectionId) return;

    // Get the currently selected chart to copy its settings
    const currentChart = charts.find((chart) => chart.id === activeTabId);

    try {
      const response = await createChart({
        collectionId,
        seriesKey: currentChart?.series_key || undefined,
        xKey: currentChart?.x_key || undefined,
        yKey: currentChart?.y_key || undefined,
        chartType: currentChart?.chart_type || 'table',
      }).unwrap();
      updateActiveTabId(response.id);
    } catch (error) {
      console.error('Failed to create chart:', error);
    }
  };

  const removeTab = async (tabId: string) => {
    if (!collectionId) return;

    const remainingTabIds = charts
      .filter((chart) => chart.id !== tabId)
      .map((chart) => chart.id);
    const nextTabId = remainingTabIds[0] ?? null;

    try {
      await deleteChart({ collectionId, chartId: tabId }).unwrap();

      if (activeTabId === tabId) {
        updateActiveTabId(nextTabId);
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
          chart: {
            id: chartId,
            name: editingName.trim(),
            series_key: chart.series_key,
            x_key: chart.x_key,
            y_key: chart.y_key,
            chart_type: chart.chart_type,
          },
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

  // Ensure consistent SSR/CSR output before collectionId is known
  if (!collectionId) {
    return (
      <div className="flex flex-col resize-y overflow-y-auto min-h-[200px] h-[35%]">
        <div className="flex items-center justify-center p-4 text-sm">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  // Handle loading and error states
  if (isLoading) {
    return (
      <div className="flex flex-col resize-y overflow-y-auto min-h-[200px] h-[35%]">
        <div className="flex items-center justify-center p-4 text-sm">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col resize-y overflow-y-auto min-h-[200px] h-[35%]">
        <div className="flex items-center justify-center p-4 text-red-500 text-sm">
          Error loading charts
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        'flex flex-col overflow-y-auto',
        activeChart && 'resize-y h-[35%] min-h-[200px]'
      )}
    >
      {/* Tab Bar */}
      <div className="flex items-end">
        {charts.map((chart: ChartSpec) => (
          <div
            key={chart.id}
            className={`group relative flex items-center px-2 py-1 text-xs font-medium cursor-pointer transition-colors rounded-t-md border mr-1 -mb-px ${
              activeTabId === chart.id
                ? 'bg-background border-border text-primary border-b-background'
                : 'bg-secondary/80 border-border text-muted-foreground hover:bg-muted hover:text-primary'
            }`}
            onClick={() => updateActiveTabId(chart.id)}
            onDoubleClick={() => handleTabDoubleClick(chart)}
          >
            {chart.chart_type === 'bar' && (
              <ChartColumn className="inline w-4 h-4 mr-2" />
            )}
            {chart.chart_type === 'line' && (
              <ChartLine className="inline w-4 h-4 mr-2" />
            )}
            {chart.chart_type === 'table' && (
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
            <button
              className={`ml-1 -mr-1 p-0.5 rounded-sm opacity-0 group-hover:opacity-100 transition-opacity ${
                activeTabId === chart.id ? 'hover:bg-muted' : 'hover:bg-accent'
              }`}
              onClick={(e) => {
                e.stopPropagation();
                removeTab(chart.id);
              }}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}

        {/* Add Tab Button */}
        <button
          className="flex items-center justify-center p-1 ml-0 text-muted-foreground bg-muted rounded transition-colors self-center"
          onClick={addTab}
        >
          <Plus className="h-3 w-3" />
        </button>

        {/* Refresh Button */}
        <button
          className="flex items-center justify-center p-1 ml-1 text-muted-foreground bg-muted rounded transition-colors self-center hover:bg-secondary hover:text-primary"
          onClick={handleRefresh}
          title="Refresh charts and data"
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      {activeChart && (
        <div className="flex flex-col flex-1 bg-background border border-border rounded-b-md rounded-tr-md min-h-0">
          <ChartSettings
            chart={activeChart}
            onChange={async (chart: ChartSpec) => {
              if (collectionId) {
                try {
                  await updateChart({ collectionId, chart }).unwrap();
                } catch (error) {
                  console.error('Failed to update chart:', error);
                }
              }
            }}
          />
          <div
            id={getChartExportElementId(activeChart.id)}
            className="flex flex-col min-h-0 flex-1"
          >
            <Chart chart={activeChart} />
          </div>
        </div>
      )}
    </div>
  );
}
