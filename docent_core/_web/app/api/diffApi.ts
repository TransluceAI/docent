import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import { DiffQuery, DiffResult } from '@/app/types/diffTypes';

export const diffApi = createApi({
  reducerPath: 'diffApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/diff`,
    credentials: 'include',
  }),
  tagTypes: ['DiffQuery', 'DiffResult'],
  endpoints: (build) => ({
    getAllDiffQueries: build.query<DiffQuery[], { collectionId: string }>({
      query: ({ collectionId }) => `/${collectionId}/queries`,
      providesTags: ['DiffQuery'],
    }),
    startDiff: build.mutation<
      string,
      { collectionId: string; query: DiffQuery }
    >({
      query: ({ collectionId, query }) => ({
        url: `/${collectionId}/start_diff`,
        method: 'POST',
        body: { query },
      }),
      invalidatesTags: ['DiffQuery'],
    }),
    listenForDiffResults: build.query<
      DiffResult[],
      { collectionId: string; queryId: string }
    >({
      query: ({ collectionId, queryId }) => ({
        url: `/${collectionId}/listen_diff`,
        method: 'POST',
        body: { query_id: queryId },
      }),
      providesTags: ['DiffResult'],
    }),
  }),
});

export const {
  useGetAllDiffQueriesQuery,
  useStartDiffMutation,
  useListenForDiffResultsQuery,
} = diffApi;
