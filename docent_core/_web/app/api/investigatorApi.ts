import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';

// Types for Investigator Workspaces
export interface InvestigatorWorkspace {
  id: string;
  name: string | null;
  description: string | null;
  created_by: string;
  created_at: string;
}

interface CreateWorkspaceRequest {
  name?: string;
  description?: string;
}

interface CreateWorkspaceResponse {
  id: string;
}

interface UpdateWorkspaceRequest {
  workspace_id: string;
  name?: string;
  description?: string;
}

// Judge Config types
export interface JudgeConfig {
  id: string;
  name: string | null;
  rubric: string;
  workspace_id: string;
  created_at: string;
}

interface CreateJudgeConfigRequest {
  name?: string;
  rubric: string;
}

// OpenAI Compatible Backend types
export interface OpenAICompatibleBackend {
  id: string;
  name: string;
  provider: string; // openai, anthropic, google, custom
  model: string;
  api_key: string | null;
  base_url: string | null;
  workspace_id: string;
  created_at: string;
}

interface CreateOpenAICompatibleBackendRequest {
  name: string;
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
}

interface ListModelsRequest {
  provider: string;
  api_key?: string;
  base_url?: string;
}

interface ListModelsResponse {
  models: string[];
}

// Experiment Idea types
export interface ExperimentIdea {
  id: string;
  name: string;
  idea: string;
  workspace_id: string;
  created_at: string;
}

interface CreateExperimentIdeaRequest {
  name: string;
  idea: string;
}

// Base Interaction types
// Tool parameter schema for function tools
interface ToolParameters {
  type: 'object';
  properties: Record<string, any>;
  required: string[];
  additionalProperties: boolean;
}

// Function tool that takes JSON schema parameters
export interface FunctionToolInfo {
  type: 'function';
  name: string;
  description: string;
  parameters: ToolParameters;
  strict?: boolean;
}

// Custom tool that processes any text input
export interface CustomToolInfo {
  type: 'custom';
  name: string;
  description: string;
}

// Union type for all tool types
export type ToolInfo = FunctionToolInfo | CustomToolInfo;

export interface BaseContext {
  id: string;
  name: string;
  prompt: Array<{
    role: string;
    content: string;
    tool_calls?: any[];
    tool_call_id?: string;
  }>;
  tools?: ToolInfo[];
  workspace_id: string;
  created_at: string;
}

interface CreateBaseContextRequest {
  name: string;
  prompt: Array<{
    role: string;
    content: string;
    tool_calls?: any[];
    tool_call_id?: string;
  }>;
  tools?: ToolInfo[];
}

// Experiment Config types
export interface ExperimentConfig {
  id: string;
  workspace_id: string;
  created_at: string;
  judge_config_id: string;
  openai_compatible_backend_id: string;
  idea_id: string;
  base_context_id: string;
  num_counterfactuals: number;
  num_replicas: number;
  max_turns: number;
}

interface CreateExperimentConfigRequest {
  judge_config_id: string;
  openai_compatible_backend_id: string;
  idea_id: string;
  base_context_id: string;
  num_counterfactuals?: number;
  num_replicas?: number;
  max_turns?: number;
}

export interface AuthorizedUser {
  user_id: string;
  email: string;
  created_at: string;
}

interface AddAuthorizedUserRequest {
  email: string;
}

export const investigatorApi = createApi({
  reducerPath: 'investigatorApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/investigator`,
    credentials: 'include',
  }),
  tagTypes: [
    'Workspace',
    'JudgeConfig',
    'OpenAICompatibleBackend',
    'ExperimentIdea',
    'BaseContext',
    'ExperimentConfig',
    'ExperimentJob',
    'AuthorizedUser',
  ],
  endpoints: (build) => ({
    // Workspace endpoints
    getWorkspaces: build.query<InvestigatorWorkspace[], void>({
      query: () => '/workspaces',
      providesTags: ['Workspace'],
    }),

    getWorkspace: build.query<InvestigatorWorkspace, string>({
      query: (workspaceId) => `/workspaces/${workspaceId}`,
      providesTags: ['Workspace'],
    }),

    createWorkspace: build.mutation<
      CreateWorkspaceResponse,
      CreateWorkspaceRequest
    >({
      query: (body) => ({
        url: '/workspaces',
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Workspace'],
    }),

    updateWorkspace: build.mutation<void, UpdateWorkspaceRequest>({
      query: ({ workspace_id, ...body }) => ({
        url: `/workspaces/${workspace_id}`,
        method: 'PUT',
        body,
      }),
      invalidatesTags: ['Workspace'],
    }),

    deleteWorkspace: build.mutation<void, string>({
      query: (workspaceId) => ({
        url: `/workspaces/${workspaceId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['Workspace'],
    }),

    // Judge Config endpoints
    getJudgeConfigs: build.query<JudgeConfig[], string>({
      query: (workspaceId) => `/workspaces/${workspaceId}/judge-configs`,
      providesTags: ['JudgeConfig'],
    }),

    createJudgeConfig: build.mutation<
      { id: string },
      { workspaceId: string } & CreateJudgeConfigRequest
    >({
      query: ({ workspaceId, ...body }) => ({
        url: `/workspaces/${workspaceId}/judge-configs`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['JudgeConfig'],
    }),

    deleteJudgeConfig: build.mutation<void, string>({
      query: (judgeConfigId) => ({
        url: `/judge-configs/${judgeConfigId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['JudgeConfig'],
    }),

    // OpenAI Compatible Backend endpoints
    getOpenAICompatibleBackends: build.query<OpenAICompatibleBackend[], string>(
      {
        query: (workspaceId) =>
          `/workspaces/${workspaceId}/openai-compatible-backends`,
        providesTags: ['OpenAICompatibleBackend'],
      }
    ),

    createOpenAICompatibleBackend: build.mutation<
      { id: string },
      { workspaceId: string } & CreateOpenAICompatibleBackendRequest
    >({
      query: ({ workspaceId, ...body }) => ({
        url: `/workspaces/${workspaceId}/openai-compatible-backends`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['OpenAICompatibleBackend'],
    }),

    deleteOpenAICompatibleBackend: build.mutation<void, string>({
      query: (backendId) => ({
        url: `/openai-compatible-backends/${backendId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['OpenAICompatibleBackend'],
    }),

    listAvailableModels: build.mutation<ListModelsResponse, ListModelsRequest>({
      query: (body) => ({
        url: '/openai-compatible-backends/list-models',
        method: 'POST',
        body,
      }),
    }),

    // Experiment Idea endpoints
    getExperimentIdeas: build.query<ExperimentIdea[], string>({
      query: (workspaceId) => `/workspaces/${workspaceId}/experiment-ideas`,
      providesTags: ['ExperimentIdea'],
    }),

    createExperimentIdea: build.mutation<
      { id: string },
      { workspaceId: string } & CreateExperimentIdeaRequest
    >({
      query: ({ workspaceId, ...body }) => ({
        url: `/workspaces/${workspaceId}/experiment-ideas`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['ExperimentIdea'],
    }),

    deleteExperimentIdea: build.mutation<void, string>({
      query: (ideaId) => ({
        url: `/experiment-ideas/${ideaId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['ExperimentIdea'],
    }),

    // Base Interaction endpoints
    getBaseContexts: build.query<BaseContext[], string>({
      query: (workspaceId) => `/workspaces/${workspaceId}/base-contexts`,
      providesTags: ['BaseContext'],
    }),

    createBaseContext: build.mutation<
      { id: string },
      { workspaceId: string } & CreateBaseContextRequest
    >({
      query: ({ workspaceId, ...body }) => ({
        url: `/workspaces/${workspaceId}/base-contexts`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['BaseContext'],
    }),

    deleteBaseContext: build.mutation<void, string>({
      query: (contextId) => ({
        url: `/base-contexts/${contextId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['BaseContext'],
    }),

    // Experiment Config endpoints
    getExperimentConfigs: build.query<ExperimentConfig[], string>({
      query: (workspaceId) => `/workspaces/${workspaceId}/experiment-configs`,
      providesTags: ['ExperimentConfig'],
    }),

    createExperimentConfig: build.mutation<
      { id: string },
      { workspaceId: string } & CreateExperimentConfigRequest
    >({
      query: ({ workspaceId, ...body }) => ({
        url: `/workspaces/${workspaceId}/experiment-configs`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['ExperimentConfig'],
    }),

    deleteExperimentConfig: build.mutation<void, string>({
      query: (configId) => ({
        url: `/experiment-configs/${configId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['ExperimentConfig'],
    }),

    // Experiment run + SSE
    startExperiment: build.mutation<
      { job_id: string; experiment_config_id: string },
      { workspaceId: string; experimentConfigId: string }
    >({
      query: ({ workspaceId, experimentConfigId }) => ({
        url: `/${workspaceId}/experiment/${experimentConfigId}/run`,
        method: 'POST',
      }),
      invalidatesTags: (result) =>
        result ? [{ type: 'ExperimentJob' as const, id: result.job_id }] : [],
    }),

    cancelExperiment: build.mutation<
      { message: string; job_id: string },
      { workspaceId: string; experimentConfigId: string }
    >({
      query: ({ workspaceId, experimentConfigId }) => ({
        url: `/${workspaceId}/experiment/${experimentConfigId}/cancel`,
        method: 'POST',
      }),
      invalidatesTags: ['ExperimentJob'],
    }),

    // Bulk endpoint to get all active jobs for a workspace
    getActiveExperimentJobs: build.query<
      Record<string, { job_id: string | null; status: string | null }>,
      string
    >({
      query: (workspaceId) => ({
        url: `/${workspaceId}/active-jobs`,
        method: 'GET',
      }),
      providesTags: ['ExperimentJob'],
    }),

    // DEPRECATED: Use getActiveExperimentJobs instead
    getActiveExperimentJob: build.query<
      {
        job_id: string | null;
        experiment_config_id: string;
        status: string | null;
      },
      { workspaceId: string; experimentConfigId: string }
    >({
      query: ({ workspaceId, experimentConfigId }) => ({
        url: `/${workspaceId}/experiment/${experimentConfigId}/active-job`,
        method: 'GET',
      }),
      providesTags: ['ExperimentJob'],
    }),

    getExperimentResult: build.query<
      any | null, // This will be the CounterfactualExperimentSummary
      { workspaceId: string; experimentConfigId: string }
    >({
      query: ({ workspaceId, experimentConfigId }) => ({
        url: `/${workspaceId}/experiment/${experimentConfigId}/result`,
        method: 'GET',
      }),
      providesTags: ['ExperimentConfig'],
    }),

    // SSE endpoint - deprecated, streaming is now handled directly in components
    listenToExperimentJob: build.query<
      { isSSEConnected: boolean },
      { workspaceId: string; jobId: string; experimentConfigId: string }
    >({
      queryFn: () => ({ data: { isSSEConnected: false } }),
      providesTags: ['ExperimentJob'],
    }),

    // Admin endpoints
    getAuthorizedUsers: build.query<AuthorizedUser[], void>({
      query: () => '/admin/authorized-users',
      providesTags: ['AuthorizedUser'],
    }),

    addAuthorizedUser: build.mutation<
      { message: string },
      AddAuthorizedUserRequest
    >({
      query: (body) => ({
        url: '/admin/authorized-users',
        method: 'POST',
        body,
      }),
      invalidatesTags: ['AuthorizedUser'],
    }),

    removeAuthorizedUser: build.mutation<{ message: string }, string>({
      query: (userId) => ({
        url: `/admin/authorized-users/${userId}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['AuthorizedUser'],
    }),
  }),
});

export const {
  useGetWorkspacesQuery,
  useGetWorkspaceQuery,
  useCreateWorkspaceMutation,
  useUpdateWorkspaceMutation,
  useDeleteWorkspaceMutation,
  // Judge Config hooks
  useGetJudgeConfigsQuery,
  useCreateJudgeConfigMutation,
  useDeleteJudgeConfigMutation,
  // OpenAI Compatible Backend hooks
  useGetOpenAICompatibleBackendsQuery,
  useCreateOpenAICompatibleBackendMutation,
  useDeleteOpenAICompatibleBackendMutation,
  useListAvailableModelsMutation,
  // Experiment Idea hooks
  useGetExperimentIdeasQuery,
  useCreateExperimentIdeaMutation,
  useDeleteExperimentIdeaMutation,
  // Base Interaction hooks
  useGetBaseContextsQuery,
  useCreateBaseContextMutation,
  useDeleteBaseContextMutation,
  // Experiment Config hooks
  useGetExperimentConfigsQuery,
  useCreateExperimentConfigMutation,
  useDeleteExperimentConfigMutation,
  // Experiment run hooks
  useStartExperimentMutation,
  useCancelExperimentMutation,
  useGetActiveExperimentJobsQuery,
  useGetActiveExperimentJobQuery,
  useGetExperimentResultQuery,
  useListenToExperimentJobQuery,
  useLazyListenToExperimentJobQuery,
  useGetAuthorizedUsersQuery,
  useAddAuthorizedUserMutation,
  useRemoveAuthorizedUserMutation,
} = investigatorApi;
