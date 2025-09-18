import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import sseService from '../services/sseService';
import { ChatMessage } from '@/app/types/transcriptTypes';
import { ModelOption } from '@/app/store/rubricSlice';

export interface ChatSession {
  id: string;
  agent_run_id: string | null;
  judge_result_id: string | null;
  messages: ChatMessage[];
  chat_model: ModelOption;
  estimated_input_tokens: number;
  error_message?: string;
}

export const chatApi = createApi({
  reducerPath: 'chatApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/chat`,
    credentials: 'include',
  }),
  tagTypes: ['ChatSession'],
  endpoints: (build) => ({
    getActiveChatJob: build.query<
      { job_id: string | null },
      { collectionId: string; runId: string; sessionId: string }
    >({
      query: ({ collectionId, runId, sessionId }) => ({
        url: `/${collectionId}/${runId}/session/${sessionId}/active-job`,
        method: 'GET',
      }),
      providesTags: (result, _err, arg) => [
        { type: 'ChatSession' as const, id: arg.sessionId },
      ],
    }),
    getChatState: build.query<
      ChatSession,
      { collectionId: string; runId: string; sessionId: string }
    >({
      query: ({ collectionId, runId, sessionId }) => ({
        url: `/${collectionId}/${runId}/session/${sessionId}/state`,
        method: 'GET',
      }),
      providesTags: (result) =>
        result ? [{ type: 'ChatSession' as const, id: result.id }] : [],
    }),

    getOrCreateChatSession: build.mutation<
      { session_id: string },
      {
        collectionId: string;
        runId: string;
        resultId: string | null;
        forceCreate?: boolean;
      }
    >({
      query: ({ collectionId, runId, resultId, forceCreate }) => {
        const baseUrl = resultId
          ? `/${collectionId}/${runId}/session/get?result_id=${resultId}`
          : `/${collectionId}/${runId}/session/get`;
        const url = forceCreate
          ? `${baseUrl}${resultId ? '&' : '?'}force_create=true`
          : baseUrl;

        return {
          url,
          method: 'POST',
        };
      },
      invalidatesTags: (result) =>
        result ? [{ type: 'ChatSession' as const, id: result.session_id }] : [],
    }),

    listenToChatJob: build.query<
      {
        isSSEConnected: boolean;
        messages: ChatMessage[];
        error_message?: string;
        estimated_input_tokens?: number;
      },
      { collectionId: string; runId: string; jobId: string }
    >({
      queryFn: () => ({
        data: {
          isSSEConnected: true,
          messages: [],
          error_message: undefined,
          estimated_input_tokens: undefined,
        },
      }),
      keepUnusedDataFor: 30, // Keep cache for 30 seconds to allow state updates
      async onCacheEntryAdded(
        { collectionId, runId, jobId },
        { dispatch, updateCachedData, cacheEntryRemoved }
      ) {
        const url = `/rest/chat/${collectionId}/${runId}/job/${jobId}/listen`;

        const { onCancel } = sseService.createEventSource(
          url,
          (data: ChatSession) => {
            updateCachedData((draft) => {
              draft.messages = data.messages;
              draft.error_message = data.error_message;
              draft.estimated_input_tokens = data.estimated_input_tokens;
            });
          },
          () => {
            updateCachedData((draft) => {
              draft.isSSEConnected = false;
            });
          },
          dispatch
        );

        await cacheEntryRemoved;
        onCancel();
      },
    }),

    postChatMessage: build.mutation<
      { job_id: string; messages: ChatMessage[] },
      {
        collectionId: string;
        runId: string;
        sessionId: string;
        message: string;
        chatModel?: ModelOption;
      }
    >({
      query: ({ collectionId, runId, sessionId, message, chatModel }) => ({
        url: `/${collectionId}/${runId}/session/${sessionId}/message`,
        method: 'POST',
        body: {
          message,
          chat_model: chatModel,
        },
      }),
      invalidatesTags: (result, error, arg) => [
        { type: 'ChatSession' as const, id: arg.sessionId },
      ],
    }),

    getChatModels: build.query<ModelOption[], void>({
      query: () => ({
        url: '/chat-models',
        method: 'GET',
      }),
    }),
  }),
});

export const {
  useGetChatStateQuery,
  useLazyGetChatStateQuery,
  useGetOrCreateChatSessionMutation,
  usePostChatMessageMutation,
  useListenToChatJobQuery,
  useLazyListenToChatJobQuery,
  useGetActiveChatJobQuery,
  useGetChatModelsQuery,
} = chatApi;
