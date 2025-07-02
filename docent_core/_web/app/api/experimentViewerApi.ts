import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';

export const experimentViewerApi = createApi({
  reducerPath: 'experimentViewerApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest`,
    credentials: 'include',
  }),
  tagTypes: ['IODims'],
  endpoints: (build) => ({
    setIODims: build.mutation<
      { innerBinKey?: string; outerBinKey?: string },
      { collectionId: string; innerBinKey?: string; outerBinKey?: string }
    >({
      query: ({ collectionId, innerBinKey, outerBinKey }) => ({
        url: `/${collectionId}/set_io_bin_keys`,
        method: 'POST',
        body: {
          inner_bin_key: innerBinKey,
          outer_bin_key: outerBinKey,
        },
      }),
      invalidatesTags: ['IODims'],
    }),
    setIODimByMetadataKey: build.mutation<
      { metadataKey: string; type: 'inner' | 'outer' },
      { collectionId: string; metadataKey: string; type: 'inner' | 'outer' }
    >({
      query: ({ collectionId, metadataKey, type }) => ({
        url: `/${collectionId}/io_bin_key_with_metadata_key`,
        method: 'POST',
        body: {
          metadata_key: metadataKey,
          type: type,
        },
      }),
      invalidatesTags: ['IODims'],
    }),
  }),
});

export const {
  useSetIODimsMutation,
  useSetIODimByMetadataKeyMutation,
} = experimentViewerApi;
