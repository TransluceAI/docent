import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import sseService from '../services/sseService';
import { ChatMessage } from '@/app/types/transcriptTypes';

import { ModelOption } from '@/app/store/rubricSlice';

export type LLMContextSpec = {
  version: string;
  root_items: string[];
  items: Record<
    string,
    | {
        type: 'agent_run';
        id: string;
        collection_id: string;
        selection_spec?: any;
      }
    | {
        type: 'transcript';
        id: string;
        agent_run_id: string;
        collection_id: string;
      }
    | {
        type: 'result_set';
        id: string;
        collection_id: string;
        cutoff_datetime?: string;
      }
    | {
        type: 'result';
        id: string;
        result_set_id: string;
        collection_id: string;
      }
  >;
  inline_data: Record<string, any>;
  visibility?: Record<string, boolean>;
};

export interface ChatSession {
  id: string;
  collection_id?: string | null;
  agent_run_id: string | null;
  judge_result_id: string | null;
  messages: ChatMessage[];
  chat_model: ModelOption;
  estimated_input_tokens: number;
  context_serialized?: LLMContextSpec | null;
  // Per-item token estimates for multi-run sessions (computed on read).
  // Maps alias (e.g., "R0", "R1") to token count.
  item_token_estimates?: Record<string, number> | null;
  error_message?: string;
  error_id?: string;
}

export interface ChatSessionSummary {
  id: string;
  collection_id?: string | null;
  message_count: number;
  context_item_count: number;
  updated_at: string;
  first_message_preview?: string | null;
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
        error_id?: string;
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
              draft.error_id = data.error_id;
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

    createConversation: build.mutation<
      { session_id: string },
      {
        context_serialized: Record<string, any>;
        chat_model?: ModelOption;
      }
    >({
      query: ({ context_serialized, chat_model }) => ({
        url: '/conversation/create',
        method: 'POST',
        body: {
          context_serialized,
          chat_model,
        },
      }),
    }),

    lookupConversationItem: build.query<
      {
        item_id: string;
        item_type: 'agent_run' | 'transcript';
        collection_id: string;
      },
      { itemId: string }
    >({
      query: ({ itemId }) => ({
        url: `/conversation/lookup/${itemId}`,
        method: 'GET',
      }),
    }),

    getConversationState: build.query<ChatSession, { sessionId: string }>({
      query: ({ sessionId }) => ({
        url: `/conversation/${sessionId}/state`,
        method: 'GET',
      }),
      providesTags: (result) =>
        result ? [{ type: 'ChatSession' as const, id: result.id }] : [],
    }),

    getActiveConversationJob: build.query<
      { job_id: string | null },
      { sessionId: string }
    >({
      query: ({ sessionId }) => ({
        url: `/conversation/${sessionId}/active-job`,
        method: 'GET',
      }),
      providesTags: (result, _err, arg) => [
        { type: 'ChatSession' as const, id: arg.sessionId },
      ],
    }),

    listenToConversationJob: build.query<
      {
        isSSEConnected: boolean;
        messages: ChatMessage[];
        error_message?: string;
        error_id?: string;
        estimated_input_tokens?: number;
      },
      { jobId: string }
    >({
      queryFn: () => ({
        data: {
          isSSEConnected: true,
          messages: [],
          error_message: undefined,
          estimated_input_tokens: undefined,
        },
      }),
      keepUnusedDataFor: 30,
      async onCacheEntryAdded(
        { jobId },
        { dispatch, updateCachedData, cacheEntryRemoved }
      ) {
        const url = `/rest/chat/conversation/job/${jobId}/listen`;

        const { onCancel } = sseService.createEventSource(
          url,
          (data: ChatSession) => {
            updateCachedData((draft) => {
              draft.messages = data.messages;
              draft.error_message = data.error_message;
              draft.error_id = data.error_id;
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

    postConversationMessage: build.mutation<
      { job_id: string; messages: ChatMessage[] },
      {
        sessionId: string;
        message: string;
        chatModel?: ModelOption;
      }
    >({
      query: ({ sessionId, message, chatModel }) => ({
        url: `/conversation/${sessionId}/message`,
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

    addConversationContextItem: build.mutation<
      ChatSession,
      { sessionId: string; itemId: string }
    >({
      query: ({ sessionId, itemId }) => ({
        url: `/conversation/${sessionId}/context`,
        method: 'POST',
        body: { item_id: itemId },
      }),
      invalidatesTags: (_result, _error, arg) => [
        { type: 'ChatSession' as const, id: arg.sessionId },
      ],
    }),

    removeConversationContextItem: build.mutation<
      ChatSession,
      { sessionId: string; itemId: string }
    >({
      query: ({ sessionId, itemId }) => ({
        url: `/conversation/${sessionId}/context/${itemId}`,
        method: 'DELETE',
      }),
      invalidatesTags: (_result, _error, arg) => [
        { type: 'ChatSession' as const, id: arg.sessionId },
      ],
    }),

    updateConversationContextSelection: build.mutation<
      ChatSession,
      {
        sessionId: string;
        itemId: string;
        selectionSpec?: Record<string, any>;
        visible?: boolean;
      }
    >({
      query: ({ sessionId, itemId, selectionSpec, visible }) => ({
        url: `/conversation/${sessionId}/context/${itemId}`,
        method: 'PATCH',
        body: { selection_spec: selectionSpec, visible },
      }),
      invalidatesTags: (_result, _error, arg) => [
        { type: 'ChatSession' as const, id: arg.sessionId },
      ],
    }),

    getCollectionChats: build.query<
      ChatSessionSummary[],
      { collectionId: string }
    >({
      query: ({ collectionId }) => ({
        url: `/${collectionId}/chats`,
        method: 'GET',
      }),
      providesTags: (result, _error, arg) => {
        const baseTag = {
          type: 'ChatSession' as const,
          id: `collection-${arg.collectionId}`,
        };
        if (!result) return [baseTag];
        return [
          ...result.map((chat) => ({
            type: 'ChatSession' as const,
            id: chat.id,
          })),
          baseTag,
        ];
      },
    }),

    createCollectionConversation: build.mutation<
      { session_id: string },
      {
        collectionId: string;
        context_serialized?: Record<string, any>;
        chat_model?: ModelOption;
      }
    >({
      query: ({ collectionId, context_serialized, chat_model }) => ({
        url: `/${collectionId}/chats`,
        method: 'POST',
        body: {
          context_serialized,
          chat_model,
        },
      }),
      invalidatesTags: (_result, _error, arg) => [
        { type: 'ChatSession' as const, id: `collection-${arg.collectionId}` },
      ],
    }),

    createFollowupFromResult: build.mutation<
      { session_id: string },
      { collectionId: string; resultId: string }
    >({
      query: ({ collectionId, resultId }) => ({
        url: `/${collectionId}/followup-from-result/${resultId}`,
        method: 'POST',
      }),
      invalidatesTags: (_result, _error, arg) => [
        { type: 'ChatSession' as const, id: `collection-${arg.collectionId}` },
      ],
    }),

    deleteConversation: build.mutation<
      { status: string },
      { sessionId: string; collectionId?: string }
    >({
      query: ({ sessionId }) => ({
        url: `/conversation/${sessionId}`,
        method: 'DELETE',
      }),
      invalidatesTags: (_result, _error, arg) => {
        const tags: Array<{ type: 'ChatSession'; id: string }> = [
          { type: 'ChatSession' as const, id: arg.sessionId },
        ];
        if (arg.collectionId) {
          tags.push({
            type: 'ChatSession' as const,
            id: `collection-${arg.collectionId}`,
          });
        }
        return tags;
      },
    }),
  }),
});

export const {
  // For legacy chat sessions that are tied to a collection
  useGetChatStateQuery,
  useLazyGetChatStateQuery,
  useGetOrCreateChatSessionMutation,
  usePostChatMessageMutation,
  useListenToChatJobQuery,
  useLazyListenToChatJobQuery,
  useGetActiveChatJobQuery,
  useGetChatModelsQuery,
  // For new chat sessions that aren't tied to a collection
  useCreateConversationMutation,
  useLookupConversationItemQuery,
  useLazyLookupConversationItemQuery,
  useGetConversationStateQuery,
  useGetActiveConversationJobQuery,
  useListenToConversationJobQuery,
  usePostConversationMessageMutation,
  useAddConversationContextItemMutation,
  useRemoveConversationContextItemMutation,
  useUpdateConversationContextSelectionMutation,
  useGetCollectionChatsQuery,
  useCreateCollectionConversationMutation,
  useCreateFollowupFromResultMutation,
  useDeleteConversationMutation,
} = chatApi;
