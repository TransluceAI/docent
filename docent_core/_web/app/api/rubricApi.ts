import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import {
  Rubric,
  JudgeResultWithCitations,
  JudgeModel,
} from '@/app/store/rubricSlice';

// Types based on the backend models
export interface CreateRubricRequest {
  rubric: {
    id?: string;
    rubric_text: string;
  };
}

export interface UpdateRubricRequest {
  rubric: {
    id: string;
    rubric_text: string;
    judge_model: JudgeModel | null;
  };
}

export interface StartRubricJobResponse {
  job_id: string;
}

export interface RubricJobDetails {
  id: string;
  status: string;
  created_at: string;
  total_agent_runs: number | null;
}

export interface AssignmentJobDetails {
  id: string;
  status: string;
  created_at: string;
}

export interface RubricRunStateResponse {
  results: JudgeResultWithCitations[];
  job_id: string | null;
  total_agent_runs: number | null;
}

export interface StartClusteringJobRequest {
  clustering_feedback?: string;
  recluster: boolean;
}

export interface StartClusteringJobResponse {
  job_id: string;
}

export interface ClusteringStateResponse {
  job_id: string | null;
  centroids: RubricCentroid[];
  assignments: Record<string, string[]>;
}

// Type for the SSE payload
export interface JudgeResultsPayload {
  results: JudgeResultWithCitations[];
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
    'RubricJob',
    'JudgeResult',
    'ClusteringJob',
    'Centroids',
    'Assignments',
  ],
  endpoints: (build) => ({
    getRubrics: build.query<Rubric[], { collectionId: string }>({
      query: ({ collectionId }) => ({
        url: `/${collectionId}/rubrics`,
        method: 'GET',
      }),
      providesTags: ['Rubric'],
    }),
    getRubric: build.query<
      Rubric,
      { collectionId: string; rubricId: string; version: number | null }
    >({
      query: ({ collectionId, rubricId, version }) => ({
        url: `/${collectionId}/rubric/${rubricId}`,
        method: 'GET',
        params: version !== null ? { version } : undefined,
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'Rubric', id: rubricId },
      ],
    }),
    getLatestRubricVersion: build.query<
      number,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/rubric/${rubricId}/latest-version`,
        method: 'GET',
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'Rubric', id: rubricId },
      ],
    }),
    createRubric: build.mutation<
      string,
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
      invalidatesTags: (result, error, { rubricId }) => [
        'Rubric',
        { type: 'RubricJob', id: rubricId },
        { type: 'JudgeResult', id: rubricId },
        { type: 'ClusteringJob', id: rubricId },
        { type: 'Centroids', id: rubricId },
        { type: 'Assignments', id: rubricId },
      ],
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
    getJudgeModels: build.query<JudgeModel[], void>({
      query: () => ({
        url: `/judge-models`,
        method: 'GET',
      }),
    }),
    startEvaluation: build.mutation<
      StartRubricJobResponse,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/evaluate`,
        method: 'POST',
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'RubricJob', id: rubricId },
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
        { type: 'RubricJob', id: rubricId },
      ],
    }),
    cancelClusteringJob: build.mutation<
      { message: string },
      { collectionId: string; rubricId: string; jobId: string }
    >({
      query: ({ collectionId, jobId }) => ({
        url: `/${collectionId}/jobs/${jobId}`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'ClusteringJob', id: rubricId },
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
        { type: 'RubricJob', id: rubricId },
      ],
    }),
    getRubricRunState: build.query<
      RubricRunStateResponse,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/rubric_run_state`,
        method: 'GET',
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'RubricJob', id: rubricId },
        { type: 'JudgeResult', id: rubricId },
      ],
    }),
    startClusteringJob: build.mutation<
      StartClusteringJobResponse,
      {
        collectionId: string;
        rubricId: string;
        clustering_feedback?: string;
        recluster: boolean;
      }
    >({
      query: ({ collectionId, rubricId, clustering_feedback, recluster }) => ({
        url: `/${collectionId}/${rubricId}/cluster`,
        method: 'POST',
        body: { clustering_feedback, recluster },
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'ClusteringJob', id: rubricId },
        { type: 'Centroids', id: rubricId },
        { type: 'Assignments', id: rubricId },
      ],
    }),
    getClusteringState: build.query<
      ClusteringStateResponse,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/clustering_job`,
        method: 'GET',
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'ClusteringJob', id: rubricId },
        { type: 'Centroids', id: rubricId },
        { type: 'Assignments', id: rubricId },
      ],
    }),
    clearClusters: build.mutation<
      void,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/${rubricId}/clear_clusters`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'Centroids', id: rubricId },
        { type: 'Assignments', id: rubricId },
      ],
    }),
  }),
});

export const {
  useGetRubricsQuery,
  useGetRubricQuery,
  useGetLatestRubricVersionQuery,
  useGetJudgeModelsQuery,
  useCreateRubricMutation,
  useUpdateRubricMutation,
  useDeleteRubricMutation,
  useStartEvaluationMutation,
  useCancelEvaluationMutation,
  useCancelClusteringJobMutation,
  useGetRubricRunStateQuery,
  useStartClusteringJobMutation,
  useGetClusteringStateQuery,
  useGetRubricJobStatusQuery,
  useClearClustersMutation,
} = rubricApi;
