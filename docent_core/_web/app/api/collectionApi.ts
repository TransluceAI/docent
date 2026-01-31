import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import { Collection, ComplexFilter } from '@/app/types/collectionTypes';
import {
  DqlAutogenMessage,
  DqlExecutePayload,
  DqlExecuteResponse,
  DqlGenerateResponse,
  DqlSchemaResponse,
} from '@/app/types/dqlTypes';
import { TranscriptMetadataField } from '@/app/types/experimentViewerTypes';
import { AgentRun, BaseAgentRunMetadata } from '@/app/types/transcriptTypes';
import sseService from '../services/sseService';

// Node types matching the backend NodeType enum
type NodeType = 'ar' | 't' | 'tg';

interface AgentRunTreeNode {
  id: string;
  node_type: NodeType;
  children_ids: string[];
  has_transcript_in_subtree: boolean;
}

interface AgentRunTree {
  nodes: Record<string, AgentRunTreeNode>;
  transcript_id_to_idx: Record<string, number>;
  parent_map: Record<string, string>;
  otel_message_ids_by_transcript_id?: Record<string, string[]>;
}

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

interface CloneCollectionRequest {
  collection_id: string;
  name?: string;
  description?: string;
}

interface CloneCollectionResponse {
  collection_id: string;
  status: string;
  agent_runs_cloned: number;
}

interface AgentRunMetadataRequest {
  agent_run_ids: string[];
  fields?: string[];
}

export interface AgentRunIngestJob {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'canceled';
  type: string;
  created_at: string;
  collection_id: string;
  error_message?: string | null;
}

interface AgentRunIngestJobsResponse {
  jobs: AgentRunIngestJob[];
  count: number;
}

interface AgentRunMetadataFieldsResponse {
  fields: TranscriptMetadataField[];
}

interface AgentRunSortableFieldsResponse {
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
    'AgentRunMetadataFieldValues',
    'AgentRunMetadataRange',
    'BaseFilter',
    'AgentRunIds',
    'DqlSchema',
    'Jobs',
  ],
  endpoints: (build) => ({
    getCollectionName: build.query<
      { name: string | null; agent_run_count: number | null },
      string
    >({
      query: (collectionId) => `/${collectionId}/collection_details`,
      providesTags: ['Collection'],
      transformResponse: (response: Collection | null) => ({
        name: response?.name ?? null,
        agent_run_count: response?.agent_run_count ?? null,
      }),
    }),
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
    cloneCollection: build.mutation<
      CloneCollectionResponse,
      CloneCollectionRequest
    >({
      query: ({ collection_id, ...body }) => ({
        url: `/${collection_id}/clone`,
        method: 'POST',
        body,
      }),
      invalidatesTags: [
        'Collection',
        'AgentRunIds',
        'AgentRunMetadata',
        'AgentRunMetadataFields',
      ],
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
      invalidatesTags: [
        'BaseFilter',
        'AgentRunMetadataFieldValues',
        'AgentRunMetadataRange',
      ],
    }),
    getAgentRunIds: build.query<
      string[],
      {
        collectionId: string;
        sortField?: string;
        sortDirection?: 'asc' | 'desc';
      }
    >({
      query: ({ collectionId, sortField, sortDirection }) => {
        const params = new URLSearchParams();
        if (sortField) params.append('sort_field', sortField);
        if (sortDirection) params.append('sort_direction', sortDirection);
        const queryString = params.toString();
        return `/${collectionId}/agent_run_ids${queryString ? `?${queryString}` : ''}`;
      },
      providesTags: ['AgentRunIds'],
    }),
    getAgentRunMetadataFields: build.query<
      AgentRunMetadataFieldsResponse,
      string
    >({
      query: (collectionId) => `/${collectionId}/agent_run_metadata_fields`,
      providesTags: ['AgentRunMetadataFields'],
    }),
    getMetadataFieldRange: build.query<
      { min: number | null; max: number | null },
      { collectionId: string; fieldName: string }
    >({
      query: ({ collectionId, fieldName }) =>
        `/${collectionId}/metadata_range/${encodeURIComponent(fieldName)}`,
      providesTags: ['AgentRunMetadataRange'],
    }),
    getAgentRunSortableFields: build.query<
      AgentRunSortableFieldsResponse,
      string
    >({
      query: (collectionId) => `/${collectionId}/agent_run_sortable_fields`,
      providesTags: ['AgentRunMetadataFields'],
    }),
    getFieldValues: build.query<
      { values: string[] },
      {
        collectionId: string;
        fieldName: string;
        search?: string;
        filter?: ComplexFilter | null;
      }
    >({
      query: ({ collectionId, fieldName, search, filter }) => {
        const url = `/${collectionId}/field_values/${encodeURIComponent(fieldName)}`;
        const params = new URLSearchParams();
        if (search) params.append('search', search);
        if (filter) params.append('filter', JSON.stringify(filter));
        const queryString = params.toString();
        return queryString ? `${url}?${queryString}` : url;
      },
      providesTags: ['AgentRunMetadataFieldValues'],
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
    getAgentRun: build.query<
      AgentRun,
      { collectionId: string; agentRunId: string }
    >({
      query: ({ collectionId, agentRunId }) => ({
        url: `/${collectionId}/agent_run?agent_run_id=${agentRunId}`,
        method: 'GET',
      }),
    }),
    getAgentRunWithTree: build.query<
      [AgentRun, AgentRunTree],
      { collectionId: string; agentRunId: string; fullTree?: boolean }
    >({
      query: ({ collectionId, agentRunId, fullTree = false }) => ({
        url: `/${collectionId}/agent_run_with_tree?agent_run_id=${agentRunId}&full_tree=${fullTree}`,
        method: 'GET',
      }),
    }),
    getAgentRunIngestJobs: build.query<AgentRunIngestJob[], string>({
      query: (collectionId) => `/${collectionId}/agent_run_ingest_jobs`,
      providesTags: ['Jobs'],
      transformResponse: (response: AgentRunIngestJobsResponse) =>
        response.jobs,
    }),
    getAgentRunIngestJob: build.query<
      AgentRunIngestJob,
      { collectionId: string; jobId: string }
    >({
      query: ({ collectionId, jobId }) =>
        `/${collectionId}/agent_runs/jobs/${jobId}`,
      providesTags: ['Jobs'],
    }),
    getDqlSchema: build.query<DqlSchemaResponse, string>({
      query: (collectionId) => `/dql/${collectionId}/schema`,
      providesTags: ['DqlSchema'],
    }),
    executeDqlQuery: build.mutation<
      DqlExecuteResponse,
      { collectionId: string } & DqlExecutePayload
    >({
      query: ({ collectionId, dql }) => ({
        url: `/dql/${collectionId}/execute`,
        method: 'POST',
        body: { dql },
      }),
    }),
    generateDql: build.mutation<
      DqlGenerateResponse,
      {
        collectionId: string;
        messages: DqlAutogenMessage[];
        current_query: string | null;
        model: string | null;
      }
    >({
      query: ({ collectionId, messages, current_query, model }) => ({
        url: `/dql/${collectionId}/generate`,
        method: 'POST',
        body: { messages, current_query, model },
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
                  'AgentRunMetadataRange',
                ])
              );
            }
          },
          () => {
            // no-op; cached data is already up to date, and cacheEntryRemoved below will finalize
          },
          dispatch
        );

        await cacheEntryRemoved;
        onCancel();
      },
    }),
  }),
});

export const {
  useGetCollectionNameQuery,
  useGetCollectionsQuery,
  useCreateCollectionMutation,
  useUpdateCollectionMutation,
  useCloneCollectionMutation,
  useDeleteCollectionMutation,
  useGetBaseFilterQuery,
  usePostBaseFilterMutation,
  useGetAgentRunMetadataFieldsQuery,
  useGetMetadataFieldRangeQuery,
  useGetAgentRunSortableFieldsQuery,
  useGetFieldValuesQuery,
  useGetAgentRunMetadataQuery,
  useGetAgentRunIdsQuery,
  useGetAgentRunIngestJobsQuery,
  useGetAgentRunIngestJobQuery,
  useGetDqlSchemaQuery,
  useExecuteDqlQueryMutation,
  useGenerateDqlMutation,
  usePreviewImportRunsFromFileMutation,
  useImportRunsFromFileStreamQuery,
  useLazyImportRunsFromFileStreamQuery,
  useGetAgentRunQuery,
  useGetAgentRunWithTreeQuery,
} = collectionApi;
