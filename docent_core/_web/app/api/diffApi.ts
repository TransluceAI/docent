import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import { DiffQuery } from '@/app/types/diffTypes';
import { diffResultReceived } from '@/app/store/diffSlice';
import sseService from '../services/sseService';

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
      { isSSEConnected: boolean },
      { collectionId: string; queryId: string }
    >({
      queryFn: () => ({ data: { isSSEConnected: true } }),
      async onCacheEntryAdded(
        { collectionId, queryId },
        { dispatch, updateCachedData, cacheEntryRemoved }
      ) {
        const url = `/rest/diff/${collectionId}/listen_diff?query_id=${queryId}`;
        sseService.createEventSource(
          url,
          (data) => dispatch(diffResultReceived({ queryId, diff: data })),
          () =>
            updateCachedData((draft) => {
              draft.isSSEConnected = false;
            })
        );

        // Suspends until the query completes
        await cacheEntryRemoved;
      },
      providesTags: ['DiffResult'],
    }),
  }),
});

export const {
  useGetAllDiffQueriesQuery,
  useStartDiffMutation,
  useListenForDiffResultsQuery,
} = diffApi;
