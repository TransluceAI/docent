import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import {
  Rubric,
  JudgeResultWithCitations,
  ModelOption,
} from '@/app/store/rubricSlice';
import { ComplexFilter, CollectionFilter } from '@/app/types/collectionTypes';

// Types based on the backend models
export interface CreateRubricRequest {
  rubric: {
    id?: string;
    rubric_text: string;
    output_schema: Record<string, any>;
    judge_model: ModelOption;
  };
}

export interface UpdateRubricRequest {
  rubric: {
    id: string;
    rubric_text: string;
    judge_model: ModelOption;
    output_schema: Record<string, any>;
    n_rollouts_per_input?: number;
  };
}

export interface StartRubricJobResponse {
  job_id: string;
}

export type JobStatus =
  | 'pending'
  | 'running'
  | 'cancelling'
  | 'canceled'
  | 'completed';

export interface RubricJobDetails {
  id: string;
  status: JobStatus;
  created_at: string;
  total_agent_runs: number | null;
}

export interface AssignmentJobDetails {
  id: string;
  status: string;
  created_at: string;
}

export interface AgentRunJudgeResults {
  agent_run_id: string;
  rubric_id: string;
  rubric_version: number;
  results: JudgeResultWithCitations[];
  reflection: JudgeReflection | null;
}

export interface RubricRunStateResponse {
  results: AgentRunJudgeResults[];
  job_id: string | null;
  job_status: JobStatus | null;
  total_results_needed: number | null;
  current_results_count: number | null;
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
  job_status: JobStatus | null;
  centroids: RubricCentroid[];
  assignments: Record<string, string[]>;
}

export interface RubricMetricsResponse {
  latest_version: number;
  judge_result_count: number;
}

// Type for the SSE payload
export interface JudgeResultsPayload {
  results: JudgeResultWithCitations[];
  total_agent_runs: number | null;
  job_id: string;
}

// Clustering types
export type ResultTypeValue = 'direct_result' | 'near_miss';

export interface RubricCentroid {
  id: string;
  collection_id: string;
  rubric_id: string;
  rubric_version: number;
  centroid: string;
  result_type: ResultTypeValue;
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

export interface EstimateCostResponse {
  cost_cents: number;
  rollouts_needed: number;
  fraction_of_daily_limit: number | null;
  provider: string;
}

export interface ReflectionSummary {
  rollout_indices: number[];
  text: string;
  classification?: 'human_miss' | 'ai_miss' | 'disagree' | 'agree';
}

export interface ReflectionIssue {
  rollout_indices: number[];
  type: 'false_negative' | 'false_positive' | 'human_miss' | 'ai_miss';
  summary: string;
}

export interface JudgeReflection {
  id: string;
  judge_result_id: string;
  judge_result_ids?: string[] | null;
  summaries: ReflectionSummary[] | null;
  issues: ReflectionIssue[] | null;
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
    'RubricMetrics',
    'JudgeReflection',
    'CostEstimate',
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
    getResultById: build.query<
      JudgeResultWithCitations,
      { collectionId: string; resultId: string }
    >({
      query: ({ collectionId, resultId }) => ({
        url: `/${collectionId}/result/${resultId}`,
        method: 'GET',
      }),
      providesTags: (result) =>
        result
          ? [{ type: 'JudgeResult', id: result.rubric_id }]
          : ['JudgeResult'],
    }),
    recomputeAgentRunReflection: build.mutation<
      JudgeReflection,
      {
        collectionId: string;
        rubricId: string;
        agentRunId: string;
        version: number;
        labelSetId?: string | null;
      }
    >({
      query: ({ collectionId, rubricId, agentRunId, version, labelSetId }) => ({
        url: `/${collectionId}/rubric/${rubricId}/agent_run/${agentRunId}/reflection`,
        method: 'GET',
        params: {
          version,
          force_recompute: true,
          label_set_id: labelSetId ?? undefined,
        },
      }),
      invalidatesTags: (result, error, { rubricId, labelSetId }) => [
        { type: 'JudgeReflection', id: rubricId, label_set_id: labelSetId },
      ],
    }),
    getRubricMetrics: build.query<
      RubricMetricsResponse,
      { collectionId: string; rubricId: string }
    >({
      query: ({ collectionId, rubricId }) => ({
        url: `/${collectionId}/rubric/${rubricId}/metrics`,
        method: 'GET',
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'RubricMetrics', id: rubricId },
        { type: 'JudgeResult', id: rubricId },
      ],
    }),
    getJudgeResultFilterFields: build.query<
      { fields: { name: string; type: 'str' | 'int' | 'float' | 'bool' }[] },
      { collectionId: string; rubricId: string; version?: number | null }
    >({
      query: ({ collectionId, rubricId, version }) => ({
        url: `/${collectionId}/rubric/${rubricId}/filter_fields`,
        method: 'GET',
        params: version != null ? { version } : undefined,
      }),
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
        { type: 'RubricMetrics', id: rubricId },
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
      invalidatesTags: ['Rubric', 'RubricMetrics'],
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
        max_agent_runs?: number | null;
        n_rollouts_per_input?: number;
        label_set_id?: string | null;
        filter?: ComplexFilter | null;
      }
    >({
      query: ({
        collectionId,
        rubricId,
        max_agent_runs,
        n_rollouts_per_input,
        label_set_id,
        filter,
      }) => ({
        url: `/${collectionId}/${rubricId}/evaluate`,
        method: 'POST',
        body: {
          max_agent_runs: max_agent_runs ?? null,
          n_rollouts_per_input: n_rollouts_per_input ?? 1,
          label_set_id: label_set_id ?? null,
          filter: filter ?? null,
        },
      }),
      invalidatesTags: (result, error, { rubricId }) => [
        { type: 'RubricJob', id: rubricId },
        { type: 'RubricMetrics', id: rubricId },
        { type: 'CostEstimate', id: rubricId },
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
        { type: 'RubricMetrics', id: rubricId },
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
      {
        collectionId: string;
        rubricId: string;
        version?: number | null;
        labelSetId?: string | null;
        filter?: CollectionFilter | null;
      }
    >({
      query: ({ collectionId, rubricId, version, labelSetId, filter }) => ({
        url: `/${collectionId}/${rubricId}/rubric_run_state`,
        method: 'POST',
        params: {
          version: version ?? undefined,
          label_set_id: labelSetId ?? undefined,
        },
        body: {
          filter_dict: filter ?? undefined,
        },
      }),
      providesTags: (result, error, { rubricId, version, labelSetId }) => [
        { type: 'RubricJob', id: rubricId },
        { type: 'JudgeResult', id: rubricId, label_set_id: labelSetId },
        { type: 'JudgeReflection', id: rubricId, label_set_id: labelSetId },
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
    estimateCost: build.query<
      EstimateCostResponse,
      {
        collectionId: string;
        rubricId: string;
        max_agent_runs?: number | null;
        n_rollouts_per_input?: number;
        label_set_id?: string | null;
        filter?: ComplexFilter | null;
      }
    >({
      query: ({
        collectionId,
        rubricId,
        max_agent_runs,
        n_rollouts_per_input,
        label_set_id,
        filter,
      }) => ({
        url: `/${collectionId}/${rubricId}/estimate_cost`,
        method: 'POST',
        body: {
          max_agent_runs: max_agent_runs ?? null,
          n_rollouts_per_input: n_rollouts_per_input ?? 1,
          label_set_id: label_set_id ?? null,
          filter: filter ?? null,
        },
      }),
      providesTags: (result, error, { rubricId }) => [
        { type: 'CostEstimate', id: rubricId },
      ],
    }),
  }),
});

export const {
  useGetRubricsQuery,
  useGetRubricQuery,
  useGetLatestRubricVersionQuery,
  useGetResultByIdQuery,
  useRecomputeAgentRunReflectionMutation,
  useGetRubricMetricsQuery,
  useGetJudgeResultFilterFieldsQuery,
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
  useEstimateCostQuery,
} = rubricApi;
