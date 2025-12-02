import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';

export interface FreeUsageModelBreakdown {
  model: string;
  total_cents: number;
  fraction_used?: number;
}

export interface FreeUsageResponse {
  has_cap: boolean;
  total_cents: number;
  models: FreeUsageModelBreakdown[];
  fraction_used?: number;
}

export interface ByokModelBreakdown {
  model: string;
  total_cents: number;
}

export interface ByokKeyUsage {
  api_key_id: string;
  total_cents: number;
  models: ByokModelBreakdown[];
}

export interface ByokUsageResponse {
  window_seconds: number | null;
  keys: ByokKeyUsage[];
}

export interface UsageSummaryResponse {
  window_seconds: number;
  free: FreeUsageResponse;
  byok: ByokUsageResponse;
}

export interface ModelApiKey {
  id: string;
  provider: string;
  masked_api_key: string;
}

export interface ChangePasswordRequest {
  old_password: string;
  new_password: string;
}

export interface ChangePasswordResponse {
  message: string;
}

export const settingsApi = createApi({
  reducerPath: 'settingsApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/settings`,
    credentials: 'include',
  }),
  endpoints: (build) => ({
    getUsageSummary: build.query<UsageSummaryResponse, void>({
      query: () => `/usage/summary`,
    }),
    getModelApiKeys: build.query<ModelApiKey[], void>({
      query: () => `/model-api-keys`,
    }),
    upsertModelApiKey: build.mutation<
      ModelApiKey,
      { provider: string; api_key: string }
    >({
      query: (body) => ({
        url: `/model-api-keys`,
        method: 'PUT',
        body,
      }),
    }),
    deleteModelApiKey: build.mutation<
      { message: string },
      { provider: string }
    >({
      query: ({ provider }) => ({
        url: `/model-api-keys/${provider}`,
        method: 'DELETE',
      }),
    }),
    changePassword: build.mutation<
      ChangePasswordResponse,
      ChangePasswordRequest
    >({
      query: (body) => ({
        url: `../change_password`,
        method: 'POST',
        body,
      }),
    }),
  }),
});

export const {
  useGetUsageSummaryQuery,
  useGetModelApiKeysQuery,
  useUpsertModelApiKeyMutation,
  useDeleteModelApiKeyMutation,
  useChangePasswordMutation,
} = settingsApi;
