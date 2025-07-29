import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import {
  JudgeResult,
  setJudgeResults,
  setIsPollingResults,
  setTotalAgentRuns,
  Rubric,
  setActiveRubricJobId,
  setCentroidAssignments,
  setIsPollingAssignments,
  setActiveCentroidAssignmentJob,
} from '@/app/store/rubricSlice';
import { chartApi } from './chartApi';
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
  job_id: string;
}

// Clustering types
export interface RubricCentroid {
  id: string;
  collection_id: string;
  rubric_id: string;
  centroid: string;
}

export interface CentroidsResponse {
  centroids: RubricCentroid[];
}

export interface CentroidAssignmentsResponse {
  assignments: Record<string, string[]>; // centroid_id -> judge_result_ids
}

export interface CentroidAssignmentsPayload {
  assignments: Record<string, string[]>;
  job_id: string;
}

export interface ProposeCentroidsRequest {
  feedback?: string;
}

export const rubricApi = createApi({
  reducerPath: 'rubricApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/rubric`,
    credentials: 'include',
  }),
  tagTypes: [
    'Rubric',
    'EvalJob',
    'JudgeResult',
    'Centroid',
    'CentroidAssignment',
  ],
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
    cancelAssignment: build.mutation<
      { message: string },
      { collectionId: string; rubricId: string; jobId: string }
    >({
      query: ({ collectionId, jobId }) => ({
        url: `/${collectionId}/jobs/${jobId}`,
        method: 'DELETE',
      }),
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
            dispatch(setActiveRubricJobId(data.job_id));
            // Invalidate chart data when judge results stream in
            dispatch(chartApi.util.invalidateTags(['ChartData']));
          },
          () => {
            dispatch(setIsPollingResults(false));
            dispatch(setActiveRubricJobId(null));
            // Invalidate EvalJob tags to refresh job status
            dispatch(
              rubricApi.util.invalidateTags([{ type: 'EvalJob', id: rubricId }])
            );
          },
          dispatch
        );

        // Suspends until the query completes
        await cacheEntryRemoved;
        onCancel();
      },
      providesTags: ['JudgeResult'],
    }),
    // Clustering endpoints
    proposeCentroids: build.mutation<
      CentroidsResponse,
      { collectionId: string; rubricId: string; feedback?: string }
    >({
      query: ({ collectionId, rubricId, feedback }) => ({
        url: `/${collectionId}/${rubricId}/propose-centroids`,
        method: 'POST',
        body: {
          feedback: feedback || null,
        },
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'Centroid', id: rubricId },
      ],
    }),
    getCentroids: build.query<
      CentroidsResponse,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/centroids`,
        method: 'GET',
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'Centroid', id: rubricId },
      ],
    }),
    clearCentroids: build.mutation<
      { message: string },
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/centroids`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'Centroid', id: rubricId },
        { type: 'CentroidAssignment', id: rubricId },
      ],
    }),
    startCentroidAssignment: build.mutation<
      StartEvalJobResponse,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/assign-centroids`,
        method: 'POST',
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'CentroidAssignment', id: rubricId },
      ],
    }),
    getCentroidAssignments: build.query<
      CentroidAssignmentsResponse,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/assignments`,
        method: 'GET',
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'CentroidAssignment', id: rubricId },
      ],
    }),
    listenForCentroidAssignments: build.query<
      { assignments: Record<string, string[]> | null },
      { collectionId: string; rubricId: string }
    >({
      queryFn: () => ({ data: { assignments: null } }),
      keepUnusedDataFor: 0, // Ensures that the SSE is killed by the cache clear immediately when the component unmounts
      async onCacheEntryAdded(
        { collectionId, rubricId },
        { dispatch, updateCachedData, cacheEntryRemoved }
      ) {
        const url = `/rest/rubric/${collectionId}/${rubricId}/assignments/poll`;

        // Set polling to true when we start the SSE connection
        dispatch(setIsPollingAssignments(true));

        const { onCancel } = sseService.createEventSource(
          url,
          (data: CentroidAssignmentsPayload) => {
            updateCachedData((draft) => {
              draft.assignments = data.assignments;
            });
            dispatch(setCentroidAssignments(data.assignments));
            dispatch(setActiveCentroidAssignmentJob(data.job_id));
            // Invalidate chart data when cluster assignments stream in
            dispatch(chartApi.util.invalidateTags(['ChartData']));
          },
          () => {
            dispatch(setIsPollingAssignments(false));
            dispatch(setActiveCentroidAssignmentJob(null));
          },
          dispatch
        );

        // Suspends until the query completes
        await cacheEntryRemoved;
        onCancel();
      },
      providesTags: ['CentroidAssignment'],
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
  useCancelAssignmentMutation,
  useGetRubricJobStatusQuery,
  useListenForJudgeResultsQuery,
  useProposeCentroidsMutation,
  useGetCentroidsQuery,
  useLazyGetCentroidsQuery,
  useClearCentroidsMutation,
  useStartCentroidAssignmentMutation,
  useGetCentroidAssignmentsQuery,
  useListenForCentroidAssignmentsQuery,
} = rubricApi;
