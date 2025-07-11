import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import {
  JudgeResult,
  setJudgeResults,
  setIsPollingResults,
  setTotalAgentRuns,
  Rubric,
  setActiveJobId,
} from '@/app/store/rubricSlice';
import sseService from '../services/sseService';

// Types based on the backend models
export interface CreateRubricRequest {
  rubric: {
    high_level_description: string;
    inclusion_rules: string[];
    exclusion_rules: string[];
  };
}

export interface UpdateRubricRequest {
  rubric: {
    id: string;
    high_level_description: string;
    inclusion_rules: string[];
    exclusion_rules: string[];
  };
}

export interface StartEvalJobResponse {
  job_id: string;
}

export interface RubricJobDetails {
  id: string;
  status: string;
  created_at: string;
  total_agent_runs: number | null;
}

// Type for the SSE payload
export interface JudgeResultsPayload {
  results: JudgeResult[];
  total_agent_runs: number | null;
}

export const rubricApi = createApi({
  reducerPath: 'rubricApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/rubric`,
    credentials: 'include',
  }),
  tagTypes: ['Rubric', 'EvalJob', 'JudgeResult'],
  endpoints: (build) => ({
    getRubrics: build.query<Rubric[], { collectionId: string }>({
      query: ({ collectionId }) => ({
        url: `/${collectionId}/rubrics`,
        method: 'GET',
      }),
      providesTags: ['Rubric'],
    }),
    createRubric: build.mutation<
      Rubric[],
      { collectionId: string; rubric: CreateRubricRequest['rubric'] }
    >({
      query: ({ collectionId, rubric }) => ({
        url: `/${collectionId}/rubric`,
        method: 'POST',
        body: {
          rubric,
        },
      }),
      invalidatesTags: ['Rubric'],
    }),
    updateRubric: build.mutation<
      Rubric[],
      {
        collectionId: string;
        rubricId: string;
        rubric: UpdateRubricRequest['rubric'];
      }
    >({
      query: ({ collectionId, rubricId, rubric }) => ({
        url: `/${collectionId}/rubric/${rubricId}`,
        method: 'PUT',
        body: {
          rubric,
        },
      }),
      invalidatesTags: ['Rubric'],
    }),
    deleteRubric: build.mutation<
      Rubric[],
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/rubric/${rubricId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['Rubric'],
    }),
    startEvaluation: build.mutation<
      StartEvalJobResponse,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/evaluate`,
        method: 'POST',
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'EvalJob', id: rubricId },
      ],
    }),
    cancelEvaluation: build.mutation<
      { message: string },
      { collectionId: string; rubricId: string; jobId: string }
    >({
      query: ({ collectionId, jobId }) => ({
        url: `/${collectionId}/jobs/${jobId}`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'EvalJob', id: rubricId },
      ],
    }),
    getRubricJobStatus: build.query<
      RubricJobDetails | null,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/job`,
        method: 'GET',
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'EvalJob', id: rubricId },
      ],
    }),
    listenForJudgeResults: build.query<
      { results: JudgeResult[] | null },
      { collectionId: string; rubricId: string }
    >({
      queryFn: () => ({ data: { results: null } }),
      keepUnusedDataFor: 0, // Ensures that the SSE is killed by the cache clear immediately when the component unmounts
      async onCacheEntryAdded(
        { collectionId, rubricId },
        { dispatch, updateCachedData, cacheEntryRemoved }
      ) {
        const url = `/rest/rubric/${collectionId}/${rubricId}/results/poll`;

        // Set polling to true when we start the SSE connection
        dispatch(setIsPollingResults(true));

        const { onCancel } = sseService.createEventSource(
          url,
          (data: JudgeResultsPayload) => {
            updateCachedData((draft) => {
              draft.results = data.results;
            });
            dispatch(setJudgeResults(data.results));
            dispatch(setTotalAgentRuns(data.total_agent_runs));
          },
          () => {
            dispatch(setIsPollingResults(false));
            dispatch(setActiveJobId(null));
          },
          dispatch
        );

        // Suspends until the query completes
        await cacheEntryRemoved;
        onCancel();
      },
      providesTags: ['JudgeResult'],
    }),
  }),
});

export const {
  useGetRubricsQuery,
  useCreateRubricMutation,
  useUpdateRubricMutation,
  useDeleteRubricMutation,
  useStartEvaluationMutation,
  useCancelEvaluationMutation,
  useGetRubricJobStatusQuery,
  useListenForJudgeResultsQuery,
} = rubricApi;
