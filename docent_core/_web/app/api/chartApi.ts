import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import { ChartDimension, ChartSpec, ChartType } from '../types/collectionTypes';
import { TaskStats } from '../types/experimentViewerTypes';

export const chartApi = createApi({
  reducerPath: 'chartApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/chart`,
    credentials: 'include',
  }),
  tagTypes: ['Charts', 'ChartData', 'ChartMetadata'],
  endpoints: (build) => ({
    createChart: build.mutation<
      { id: string },
      {
        collectionId: string;
        seriesKey?: string;
        xKey?: string;
        yKey?: string;
        chartType?: ChartType;
        rubricFilter?: string;
      }
    >({
      query: ({
        collectionId,
        seriesKey,
        xKey,
        yKey,
        chartType = 'table',
      }) => ({
        url: `/${collectionId}/create`,
        method: 'POST',
        body: {
          series_key: seriesKey,
          x_key: xKey,
          y_key: yKey,
          chart_type: chartType,
        },
      }),
      invalidatesTags: ['Charts', 'ChartData'],
    }),
    updateChart: build.mutation<
      { status: string },
      { collectionId: string; chart: ChartSpec }
    >({
      query: ({ collectionId, chart }) => ({
        url: `/${collectionId}`,
        method: 'POST',
        body: chart,
      }),
      invalidatesTags: ['Charts', 'ChartData'],
    }),
    deleteChart: build.mutation<
      { status: string },
      { collectionId: string; chartId: string }
    >({
      query: ({ collectionId, chartId }) => ({
        url: `/${collectionId}/${chartId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['Charts', 'ChartData'],
    }),
    getCharts: build.query<ChartSpec[], { collectionId: string }>({
      query: ({ collectionId }) => ({
        url: `/${collectionId}`,
        method: 'GET',
      }),
      providesTags: ['Charts'],
    }),
    getChartData: build.query<
      {
        request_type: string;
        result: {
          binStats: Record<string, TaskStats>;
        };
      },
      { collectionId: string; chartId: string }
    >({
      query: ({ collectionId, chartId }) => ({
        url: `/${collectionId}/${chartId}/data`,
        method: 'GET',
      }),
      providesTags: (result, error, { chartId }) => [
        { type: 'ChartData', id: chartId },
      ],
    }),
    getChartMetadata: build.query<
      {
        dimensions: ChartDimension[];
        measures: ChartDimension[];
      },
      { collectionId: string }
    >({
      query: ({ collectionId }) => ({
        url: `/${collectionId}/metadata`,
        method: 'GET',
      }),
      providesTags: ['ChartMetadata'],
    }),
  }),
});

export const {
  useCreateChartMutation,
  useUpdateChartMutation,
  useDeleteChartMutation,
  useGetChartMetadataQuery,
  useGetChartsQuery,
  useGetChartDataQuery,
} = chartApi;
