import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import { ChartType } from '../types/collectionTypes';

export const experimentViewerApi = createApi({
  reducerPath: 'experimentViewerApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest`,
    credentials: 'include',
  }),
  tagTypes: ['Charts'],
  endpoints: (build) => ({
    createChart: build.mutation<
      { chart_id: string },
      {
        collectionId: string;
        seriesKey?: string;
        xKey?: string;
        yKey?: string;
        sqlQuery?: string;
        chartType?: ChartType;
      }
    >({
      query: ({
        collectionId,
        seriesKey,
        xKey,
        yKey,
        sqlQuery,
        chartType = 'table',
      }) => ({
        url: `/${collectionId}/charts/create`,
        method: 'POST',
        body: {
          series_key: seriesKey,
          x_key: xKey,
          y_key: yKey,
          sql_query: sqlQuery,
          chart_type: chartType,
        },
      }),
      invalidatesTags: ['Charts'],
    }),
    updateChart: build.mutation<
      { status: string },
      {
        collectionId: string;
        id?: string;
        name: string;
        seriesKey?: string;
        xKey?: string;
        yKey?: string;
        sqlQuery?: string;
        chartType?: string;
      }
    >({
      query: ({
        collectionId,
        id,
        name,
        seriesKey,
        xKey,
        yKey,
        sqlQuery,
        chartType,
      }) => ({
        url: `/${collectionId}/charts`,
        method: 'POST',
        body: {
          chart_id: id,
          name,
          series_key: seriesKey,
          x_key: xKey,
          y_key: yKey,
          sql_query: sqlQuery,
          chart_type: chartType,
        },
      }),
      invalidatesTags: ['Charts'],
    }),
    deleteChart: build.mutation<
      { status: string },
      { collectionId: string; chartId: string }
    >({
      query: ({ collectionId, chartId }) => ({
        url: `/${collectionId}/charts/${chartId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['Charts'],
    }),
  }),
});

export const {
  useCreateChartMutation,
  useUpdateChartMutation,
  useDeleteChartMutation,
} = experimentViewerApi;
