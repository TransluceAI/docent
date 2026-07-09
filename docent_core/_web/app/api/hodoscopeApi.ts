import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';

export type HodoscopeAnalysisStatus =
  'pending' | 'running' | 'complete' | 'error' | 'canceled';

export type HodoscopeProjectionMethod =
  'pca' | 'tsne' | 'umap' | 'trimap' | 'pacmap';

export interface HodoscopeAnalysisConfig {
  name?: string;
  group_by?: string | null;
  limit?: number;
  seed?: number;
  projection_method?: HodoscopeProjectionMethod;
}

export interface HodoscopeAnalysisSummary {
  id: string;
  collection_id: string;
  job_id: string | null;
  name: string;
  status: HodoscopeAnalysisStatus;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  config: Record<string, unknown>;
  error: string | null;
  stage: string | null;
  progress: number | null;
  point_count: number;
  group_count: number;
}

export interface HodoscopeProjectionPoint {
  id: string;
  trajectory_id: string;
  turn_id: number;
  agent_run_id: string;
  transcript_id: string;
  transcript_idx: number;
  action_unit_idx: number;
  first_block_idx: number | null;
  summary: string;
  action_text: string;
  task_context: string;
  metadata: Record<string, unknown>;
  group: string;
  embedding: string;
  x: number;
  y: number;
  fps_rank: number;
}

export interface HodoscopeProjection {
  version: number;
  created_at: string;
  group_by: string;
  projection_method: string;
  requested_projection_method?: string;
  groups: Array<{ name: string; count: number }>;
  points: HodoscopeProjectionPoint[];
}

export const hodoscopeApi = createApi({
  reducerPath: 'hodoscopeApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/hodoscope`,
    credentials: 'include',
  }),
  tagTypes: ['HodoscopeAnalysis', 'HodoscopeProjection'],
  endpoints: (build) => ({
    listHodoscopeAnalyses: build.query<
      HodoscopeAnalysisSummary[],
      { collectionId: string }
    >({
      query: ({ collectionId }) => `/${collectionId}/analyses`,
      providesTags: ['HodoscopeAnalysis'],
    }),
    getHodoscopeAnalysis: build.query<
      HodoscopeAnalysisSummary,
      { collectionId: string; analysisId: string }
    >({
      query: ({ collectionId, analysisId }) =>
        `/${collectionId}/analyses/${analysisId}`,
      providesTags: (_result, _error, { analysisId }) => [
        { type: 'HodoscopeAnalysis', id: analysisId },
      ],
    }),
    getHodoscopeProjection: build.query<
      HodoscopeProjection,
      { collectionId: string; analysisId: string }
    >({
      query: ({ collectionId, analysisId }) =>
        `/${collectionId}/analyses/${analysisId}/projection`,
      providesTags: (_result, _error, { analysisId }) => [
        { type: 'HodoscopeProjection', id: analysisId },
      ],
    }),
    getHodoscopeArtifact: build.query<
      Record<string, unknown>,
      { collectionId: string; analysisId: string }
    >({
      query: ({ collectionId, analysisId }) =>
        `/${collectionId}/analyses/${analysisId}/artifact`,
    }),
    startHodoscopeAnalysis: build.mutation<
      HodoscopeAnalysisSummary,
      { collectionId: string; config: HodoscopeAnalysisConfig }
    >({
      query: ({ collectionId, config }) => ({
        url: `/${collectionId}/analyses`,
        method: 'POST',
        body: config,
      }),
      invalidatesTags: ['HodoscopeAnalysis'],
    }),
    cancelHodoscopeAnalysis: build.mutation<
      HodoscopeAnalysisSummary,
      { collectionId: string; analysisId: string }
    >({
      query: ({ collectionId, analysisId }) => ({
        url: `/${collectionId}/analyses/${analysisId}/cancel`,
        method: 'POST',
      }),
      invalidatesTags: (_result, _error, { analysisId }) => [
        'HodoscopeAnalysis',
        { type: 'HodoscopeAnalysis', id: analysisId },
      ],
    }),
  }),
});

export const {
  useListHodoscopeAnalysesQuery,
  useGetHodoscopeAnalysisQuery,
  useGetHodoscopeProjectionQuery,
  useLazyGetHodoscopeArtifactQuery,
  useStartHodoscopeAnalysisMutation,
  useCancelHodoscopeAnalysisMutation,
} = hodoscopeApi;
