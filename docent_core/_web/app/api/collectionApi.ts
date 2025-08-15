import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import { Collection, ComplexFilter } from '@/app/types/collectionTypes';
import { TranscriptMetadataField } from '@/app/types/experimentViewerTypes';
import { BaseAgentRunMetadata } from '@/app/types/transcriptTypes';
import sseService from '../services/sseService';

interface CreateCollectionRequest {
  collection_id?: string;
  name?: string;
  description?: string;
}

interface CreateCollectionResponse {
  collection_id: string;
}

interface UpdateCollectionRequest {
  collection_id: string;
  name?: string;
  description?: string;
}

interface AgentRunMetadataRequest {
  agent_run_ids: string[];
}

interface AgentRunMetadataFieldsResponse {
  fields: TranscriptMetadataField[];
}

interface PostBaseFilterRequest {
  filter: ComplexFilter | null;
}

export const collectionApi = createApi({
  reducerPath: 'collectionApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest`,
    credentials: 'include',
  }),
  tagTypes: [
    'Collection',
    'AgentRunMetadata',
    'AgentRunMetadataFields',
    'BaseFilter',
    'AgentRunIds',
  ],
  endpoints: (build) => ({
    getCollections: build.query<Collection[], void>({
      query: () => '/collections',
      providesTags: ['Collection'],
    }),
    createCollection: build.mutation<
      CreateCollectionResponse,
      CreateCollectionRequest
    >({
      query: (body) => ({
        url: '/create',
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Collection'],
    }),
    updateCollection: build.mutation<void, UpdateCollectionRequest>({
      query: ({ collection_id, ...body }) => ({
        url: `/${collection_id}/collection`,
        method: 'PUT',
        body,
      }),
      invalidatesTags: ['Collection'],
    }),
    deleteCollection: build.mutation<void, string>({
      query: (collection_id) => ({
        url: `/${collection_id}/collection`,
        method: 'DELETE',
      }),
      invalidatesTags: ['Collection'],
    }),
    getBaseFilter: build.query<ComplexFilter | null, string>({
      query: (collectionId) => `/${collectionId}/base_filter`,
      providesTags: ['BaseFilter'],
    }),
    postBaseFilter: build.mutation<
      ComplexFilter | null,
      { collection_id: string } & PostBaseFilterRequest
    >({
      query: ({ collection_id, ...body }) => ({
        url: `/${collection_id}/base_filter`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['BaseFilter', 'AgentRunIds'],
    }),
    getAgentRunIds: build.query<string[], { collectionId: string }>({
      query: ({ collectionId }) => `/${collectionId}/agent_run_ids`,
      providesTags: ['AgentRunIds'],
    }),
    getAgentRunMetadataFields: build.query<
      AgentRunMetadataFieldsResponse,
      string
    >({
      query: (collectionId) => `/${collectionId}/agent_run_metadata_fields`,
      providesTags: ['AgentRunMetadataFields'],
    }),
    getAgentRunMetadata: build.query<
      Record<string, BaseAgentRunMetadata>,
      { collectionId: string } & AgentRunMetadataRequest
    >({
      query: ({ collectionId, ...body }) => ({
        url: `/${collectionId}/agent_run_metadata`,
        method: 'POST',
        body,
      }),
    }),
    previewImportRunsFromFile: build.mutation<
      {
        status: string;
        would_import: {
          num_agent_runs: number;
          models: string[];
          task_ids: string[];
          score_types: string[];
        };
        file_info: {
          filename: string;
          task?: string | null;
          model?: string | null;
          total_samples: number;
        };
        sample_preview: Array<{
          metadata: Record<string, any>;
          num_messages: number;
        }>;
      },
      { collectionId: string; file: File }
    >({
      query: ({ collectionId, file }) => {
        const formData = new FormData();
        formData.append('file', file);
        return {
          url: `/${collectionId}/preview_import_runs_from_file`,
          method: 'POST',
          body: formData,
        } as any;
      },
    }),
    importRunsFromFileStream: build.query<
      {
        phase: 'progress' | 'complete' | 'error';
        uploaded: number | null;
        total: number | null;
      },
      { collectionId: string; file: File }
    >({
      queryFn: () => ({
        data: {
          phase: 'progress',
          uploaded: 0,
          total: null,
        },
      }),
      keepUnusedDataFor: 0,
      async onCacheEntryAdded(
        { collectionId, file },
        { updateCachedData, cacheEntryRemoved, dispatch }
      ) {
        const formData = new FormData();
        formData.append('file', file);

        const { onCancel } = sseService.postEventStream(
          `/rest/${collectionId}/import_runs_from_file`,
          formData,
          (data) => {
            updateCachedData((_) => data);
            if (data.phase === 'complete') {
              // Refresh dependent data after import completes
              dispatch(
                collectionApi.util.invalidateTags([
                  'AgentRunIds',
                  'AgentRunMetadata',
                ])
              );
            }
          },
          () => {
            // no-op; cached data is already up to date, and cacheEntryRemoved below will finalize
          },
          dispatch as any
        );

        await cacheEntryRemoved;
        onCancel();
      },
    }),
  }),
});

export const {
  useGetCollectionsQuery,
  useCreateCollectionMutation,
  useUpdateCollectionMutation,
  useDeleteCollectionMutation,
  useGetBaseFilterQuery,
  usePostBaseFilterMutation,
  useGetAgentRunMetadataFieldsQuery,
  useGetAgentRunMetadataQuery,
  useGetAgentRunIdsQuery,
  usePreviewImportRunsFromFileMutation,
  useImportRunsFromFileStreamQuery,
  useLazyImportRunsFromFileStreamQuery,
} = collectionApi;
