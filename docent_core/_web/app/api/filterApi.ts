import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import {
  StoredFilter,
  FilterListItem,
  CreateFilterRequest,
  UpdateFilterRequest,
} from '@/app/types/filterTypes';

export const filterApi = createApi({
  reducerPath: 'filterApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest`,
    credentials: 'include',
  }),
  tagTypes: ['SavedFilters'],
  endpoints: (build) => ({
    listFilters: build.query<FilterListItem[], string>({
      query: (collectionId) => `/${collectionId}/filters`,
      providesTags: ['SavedFilters'],
    }),

    getFilter: build.query<
      StoredFilter,
      { collectionId: string; filterId: string }
    >({
      query: ({ collectionId, filterId }) =>
        `/${collectionId}/filters/${filterId}`,
      providesTags: (_result, _error, { filterId }) => [
        { type: 'SavedFilters', id: filterId },
      ],
    }),

    createFilter: build.mutation<
      StoredFilter,
      { collectionId: string } & CreateFilterRequest
    >({
      query: ({ collectionId, ...body }) => ({
        url: `/${collectionId}/filters`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['SavedFilters'],
    }),

    updateFilter: build.mutation<
      StoredFilter,
      { collectionId: string; filterId: string } & UpdateFilterRequest
    >({
      query: ({ collectionId, filterId, ...body }) => ({
        url: `/${collectionId}/filters/${filterId}`,
        method: 'PUT',
        body,
      }),
      invalidatesTags: ['SavedFilters'],
    }),

    deleteFilter: build.mutation<
      { status: string; filter_id: string },
      { collectionId: string; filterId: string }
    >({
      query: ({ collectionId, filterId }) => ({
        url: `/${collectionId}/filters/${filterId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['SavedFilters'],
    }),
  }),
});

export const {
  useListFiltersQuery,
  useGetFilterQuery,
  useCreateFilterMutation,
  useUpdateFilterMutation,
  useDeleteFilterMutation,
} = filterApi;
