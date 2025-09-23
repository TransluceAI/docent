import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import {
  Rubric,
  JudgeResultWithCitations,
  ModelOption,
  JudgeRunLabel,
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
    judge_model: ModelOption;
    output_schema: Record<string, any>;
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

export interface CopyRubricRequest {
  target_collection_id: string;
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
    'JudgeRunLabel',
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
      { collectionId: string; rubricId: string; version?: number | null }
    >({
      query: ({ collectionId, rubricId, version }) => ({
        url: `/${collectionId}/rubric/${rubricId}`,
        method: 'GET',
        params: version ? { version } : undefined,
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'Rubric', id: rubricId, version: result?.version },
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
        { type: 'Rubric', id: rubricId, version: result },
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
    getJudgeModels: build.query<ModelOption[], void>({
      query: () => ({
        url: `/judge-models`,
        method: 'GET',
      }),
    }),
    startEvaluation: build.mutation<
      StartRubricJobResponse,
      {
        collectionId: string;
        rubricId: string;
        max_results?: number | null;
      }
    >({
      query: ({ collectionId, rubricId, max_results }) => ({
        url: `/${collectionId}/${rubricId}/evaluate`,
        method: 'POST',
        body: {
          max_results: max_results ?? null,
        },
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
      { collectionId: string; rubricId: string; version?: number | null }
    >({
      query: ({ collectionId, rubricId, version }) => ({
        url: `/${collectionId}/${rubricId}/rubric_run_state`,
        method: 'GET',
        params: version ? { version } : undefined,
      }),
      providesTags: (result, error, { rubricId, version }) => [
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

    // LABELS
    deleteAllJudgeRunLabels: build.mutation<
      void,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/rubric/${rubricId}/labels`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'JudgeRunLabel', id: `LIST-${rubricId}` },
        'JudgeRunLabel', // Invalidate all JudgeRunLabel caches to clear individual labels
      ],
    }),
    createJudgeRunLabel: build.mutation<
      void,
      {
        collectionId: string;
        rubricId: string;
        agentRunId: string;
        label: Record<string, any>;
      }
    >({
      query: ({ collectionId, rubricId, agentRunId, label }) => ({
        url: `/${collectionId}/rubric/${rubricId}/label`,
        method: 'POST',
        body: {
          label: {
            agent_run_id: agentRunId,
            rubric_id: rubricId,
            label: label,
          } as JudgeRunLabel,
        },
      }),
      invalidatesTags: (result, error, { rubricId, agentRunId }) => [
        { type: 'JudgeRunLabel', id: `LIST-${rubricId}` },
        { type: 'JudgeRunLabel', id: agentRunId },
      ],
    }),
    updateJudgeRunLabel: build.mutation<
      void,
      {
        collectionId: string;
        rubricId: string;
        agentRunId: string;
        label: Record<string, any>;
      }
    >({
      query: ({ collectionId, rubricId, agentRunId, label }) => ({
        url: `/${collectionId}/rubric/${rubricId}/label`,
        method: 'PUT',
        body: { agent_run_id: agentRunId, label },
      }),
      invalidatesTags: (result, error, { rubricId, agentRunId }) => [
        { type: 'JudgeRunLabel', id: `LIST-${rubricId}` },
        { type: 'JudgeRunLabel', id: agentRunId },
      ],
    }),
    getJudgeRunLabels: build.query<
      JudgeRunLabel[],
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/rubric/${rubricId}/labels`,
        method: 'GET',
      }),
      providesTags: (result, error, { rubricId }) =>
        result
          ? [
              { type: 'JudgeRunLabel', id: `LIST-${rubricId}` },
              ...result.map((label) => ({
                type: 'JudgeRunLabel' as const,
                id: label.agent_run_id,
              })),
            ]
          : [{ type: 'JudgeRunLabel', id: `LIST-${rubricId}` }],
    }),
    getJudgeRunLabel: build.query<
      JudgeRunLabel,
      { collectionId: string; rubricId: string; agentRunId: string }
    >({
      query: ({ collectionId, rubricId, agentRunId }) => ({
        url: `/${collectionId}/rubric/${rubricId}/label/${agentRunId}`,
        method: 'GET',
      }),
      providesTags: (result, error, { agentRunId }) => [
        { type: 'JudgeRunLabel', id: agentRunId },
      ],
    }),
    deleteJudgeRunLabel: build.mutation<
      void,
      {
        collectionId: string;
        rubricId: string;
        agentRunId: string;
      }
    >({
      query: ({ collectionId, rubricId, agentRunId }) => ({
        url: `/${collectionId}/rubric/${rubricId}/label`,
        method: 'DELETE',
        body: { agent_run_id: agentRunId },
      }),
      invalidatesTags: (result, error, { rubricId, agentRunId }) => [
        { type: 'JudgeRunLabel', id: `LIST-${rubricId}` },
        { type: 'JudgeRunLabel', id: agentRunId },
      ],
    }),
    copyRubric: build.mutation<
      { rubric_id: string },
      {
        collectionId: string;
        rubricId: string;
        target_collection_id: string;
      }
    >({
      query: ({ collectionId, rubricId, target_collection_id }) => ({
        url: `/${collectionId}/rubric/${rubricId}/copy`,
        method: 'POST',
        body: { target_collection_id },
      }),
      invalidatesTags: ['Rubric'],
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
  useCopyRubricMutation,
  useCancelClusteringJobMutation,
  useGetRubricRunStateQuery,
  useStartClusteringJobMutation,
  useGetClusteringStateQuery,
  useGetRubricJobStatusQuery,
  useClearClustersMutation,

  // LABELS
  useDeleteAllJudgeRunLabelsMutation,
  useGetJudgeRunLabelsQuery,
  useGetJudgeRunLabelQuery,
  useDeleteJudgeRunLabelMutation,
  useCreateJudgeRunLabelMutation,
  useUpdateJudgeRunLabelMutation,
} = rubricApi;
