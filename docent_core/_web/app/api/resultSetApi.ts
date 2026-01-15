import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';

export type JobStatus =
  | 'pending'
  | 'running'
  | 'cancelling'
  | 'canceled'
  | 'completed';

// Types based on the backend models
export interface ResultSetResponse {
  id: string;
  name: string | null;
  output_schema: Record<string, unknown>;
  created_at: string;
  result_count?: number | null;
  first_prompt_preview?: string | null;
  job_id?: string | null;
  job_status?: JobStatus | null;
}

export interface ResultResponse {
  id: string;
  result_set_id: string;
  llm_context_spec: Record<string, unknown>;
  prompt_segments: (string | { alias: string })[];
  user_metadata: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error_json: Record<string, unknown> | null;
  input_tokens: number | null;
  output_tokens: number | null;
  model: string | null;
  created_at: string | null;
  cost_cents: number | null;
  joined?: Record<string, Record<string, unknown>>;
}

export interface CreateResultSetRequest {
  name?: string | null;
  output_schema?: Record<string, unknown>;
}

export interface UpdateNameRequest {
  name: string | null;
}

export const resultSetApi = createApi({
  reducerPath: 'resultSetApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/results`,
    credentials: 'include',
  }),
  tagTypes: ['ResultSet', 'Result'],
  endpoints: (build) => ({
    getResultSets: build.query<
      ResultSetResponse[],
      { collectionId: string; prefix?: string }
    >({
      query: ({ collectionId, prefix }) => ({
        url: `/${collectionId}/result-sets`,
        method: 'GET',
        params: prefix ? { prefix } : undefined,
      }),
      providesTags: ['ResultSet'],
    }),

    getResultSet: build.query<
      ResultSetResponse,
      { collectionId: string; resultSetIdOrName: string }
    >({
      query: ({ collectionId, resultSetIdOrName }) => ({
        url: `/${collectionId}/result-sets/${encodeURIComponent(resultSetIdOrName)}`,
        method: 'GET',
      }),
      providesTags: (result, error, { resultSetIdOrName }) => [
        { type: 'ResultSet', id: resultSetIdOrName },
      ],
    }),

    createResultSet: build.mutation<
      ResultSetResponse,
      { collectionId: string; request: CreateResultSetRequest }
    >({
      query: ({ collectionId, request }) => ({
        url: `/${collectionId}/result-sets`,
        method: 'POST',
        body: request,
      }),
      invalidatesTags: ['ResultSet'],
    }),

    deleteResultSet: build.mutation<
      { deleted: boolean },
      { collectionId: string; resultSetIdOrName: string }
    >({
      query: ({ collectionId, resultSetIdOrName }) => ({
        url: `/${collectionId}/result-sets/${encodeURIComponent(resultSetIdOrName)}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['ResultSet'],
    }),

    updateResultSetName: build.mutation<
      ResultSetResponse,
      { collectionId: string; resultSetIdOrName: string; name: string | null }
    >({
      query: ({ collectionId, resultSetIdOrName, name }) => ({
        url: `/${collectionId}/result-sets/${encodeURIComponent(resultSetIdOrName)}/name`,
        method: 'PATCH',
        body: { name },
      }),
      invalidatesTags: (result, error, { resultSetIdOrName }) => [
        'ResultSet',
        { type: 'ResultSet', id: resultSetIdOrName },
      ],
    }),

    getResults: build.query<
      ResultResponse[],
      {
        collectionId: string;
        resultSetIdOrName: string;
        limit?: number;
        offset?: number;
        withAutoJoins?: boolean;
      }
    >({
      query: ({
        collectionId,
        resultSetIdOrName,
        limit,
        offset,
        withAutoJoins,
      }) => ({
        url: `/${collectionId}/results/${encodeURIComponent(resultSetIdOrName)}`,
        method: 'GET',
        params: {
          ...(limit !== undefined && { limit }),
          ...(offset !== undefined && { offset }),
          ...(withAutoJoins !== undefined && {
            with_auto_joins: withAutoJoins,
          }),
          include_incomplete: true,
        },
      }),
      providesTags: (result, error, { resultSetIdOrName }) => [
        { type: 'Result', id: resultSetIdOrName },
      ],
    }),

    getResult: build.query<
      ResultResponse,
      { collectionId: string; resultId: string }
    >({
      query: ({ collectionId, resultId }) => ({
        url: `/${collectionId}/result/${resultId}`,
        method: 'GET',
      }),
      providesTags: (result) =>
        result ? [{ type: 'Result', id: result.id }] : ['Result'],
    }),

    cancelJobs: build.mutation<
      { message: string },
      { collectionId: string; resultSetIdOrName: string }
    >({
      query: ({ collectionId, resultSetIdOrName }) => ({
        url: `/${collectionId}/result-jobs/${encodeURIComponent(resultSetIdOrName)}`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { resultSetIdOrName }) => [
        { type: 'ResultSet', id: resultSetIdOrName },
      ],
    }),
  }),
});

export const {
  useGetResultSetsQuery,
  useGetResultSetQuery,
  useCreateResultSetMutation,
  useDeleteResultSetMutation,
  useUpdateResultSetNameMutation,
  useGetResultsQuery,
  useGetResultQuery,
  useCancelJobsMutation,
} = resultSetApi;
