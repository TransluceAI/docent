import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import sseService from '../services/sseService';
import { RefinementAgentSession } from '@/app/store/refinementSlice';
import { Rubric } from '@/app/store/rubricSlice';

export const refinementApi = createApi({
  reducerPath: 'refinementApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/refinement`,
    credentials: 'include',
  }),
  tagTypes: ['RefinementSession'],
  endpoints: (build) => ({
    getRefinementSessionState: build.query<
      RefinementAgentSession,
      { collectionId: string; sessionId: string }
    >({
      query: ({ collectionId, sessionId }) => ({
        url: `/${collectionId}/refinement-session/${sessionId}/state`,
        method: 'GET',
      }),
      providesTags: (result) =>
        result ? [{ type: 'RefinementSession' as const, id: result.id }] : [],
    }),
    createOrGetRefinementSession: build.mutation<
      { id: string },
      { collectionId: string; rubricId: string; sessionType: string }
    >({
      query: ({ collectionId, rubricId, sessionType }) => ({
        url: `/${collectionId}/refinement-session/create/${rubricId}`,
        method: 'POST',
        body: { session_type: sessionType },
      }),
      invalidatesTags: (result) =>
        result ? [{ type: 'RefinementSession' as const, id: result.id }] : [],
    }),

    startRefinementSession: build.mutation<
      { session_id: string; job_id: string | null; rubric_id: string },
      { collectionId: string; sessionId: string }
    >({
      query: ({ collectionId, sessionId }) => ({
        url: `/${collectionId}/refinement-session/start/${sessionId}`,
        method: 'POST',
      }),
      invalidatesTags: (result) =>
        result
          ? [{ type: 'RefinementSession' as const, id: result.session_id }]
          : [],
    }),

    getRefinementSessionJob: build.mutation<
      { session_id: string; job_id: string | null; rubric_id: string },
      { collectionId: string; sessionId: string }
    >({
      query: ({ collectionId, sessionId }) => ({
        url: `/${collectionId}/refinement-session/${sessionId}/job`,
        method: 'GET',
      }),
      invalidatesTags: (result) =>
        result
          ? [{ type: 'RefinementSession' as const, id: result.session_id }]
          : [],
    }),

    listenToRefinementJob: build.query<
      {
        isSSEConnected: boolean;
        rSession: RefinementAgentSession | null;
        eval_rubric_job_id: string | null;
        error_message?: string;
      },
      { collectionId: string; jobId: string }
    >({
      queryFn: () => ({
        data: {
          isSSEConnected: true,
          rSession: null,
          eval_rubric_job_id: null,
          error_message: undefined,
        },
      }),
      keepUnusedDataFor: 0,
      async onCacheEntryAdded(
        { collectionId, jobId },
        { dispatch, updateCachedData, cacheEntryRemoved }
      ) {
        const url = `/rest/refinement/${collectionId}/refinement-job/${jobId}/listen`;

        const { onCancel } = sseService.createEventSource(
          url,
          (data: RefinementAgentSession) => {
            updateCachedData((draft) => {
              draft.rSession = data;
              draft.error_message = data.error_message;
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
      providesTags: ['RefinementSession'],
    }),

    postMessageToRefinementSession: build.mutation<
      { job_id: string; rSession: RefinementAgentSession },
      {
        collectionId: string;
        sessionId: string;
        message: string;
        showLabelsInContext: boolean;
      }
    >({
      query: ({ collectionId, sessionId, message, showLabelsInContext }) => ({
        url: `/${collectionId}/refinement-session/${sessionId}/message`,
        method: 'POST',
        body: {
          message,
          show_labels_in_context: showLabelsInContext,
        },
      }),
      invalidatesTags: (result, error, arg) => [
        { type: 'RefinementSession' as const, id: arg.sessionId },
      ],
    }),

    postRubricUpdateToRefinementSession: build.mutation<
      { job_id: string; rSession: RefinementAgentSession },
      { collectionId: string; sessionId: string; rubric: Rubric }
    >({
      query: ({ collectionId, sessionId, rubric }) => ({
        url: `/${collectionId}/refinement-session/${sessionId}/rubric-update`,
        method: 'POST',
        body: rubric,
      }),
      invalidatesTags: (result, error, arg) => [
        { type: 'RefinementSession' as const, id: arg.sessionId },
      ],
    }),

    retryLastMessage: build.mutation<
      { job_id: string; rSession: RefinementAgentSession },
      { collectionId: string; sessionId: string }
    >({
      query: ({ collectionId, sessionId }) => ({
        url: `/${collectionId}/refinement-session/${sessionId}/retry-last-message`,
        method: 'POST',
        body: undefined,
      }),
      invalidatesTags: (result, error, arg) => [
        { type: 'RefinementSession' as const, id: arg.sessionId },
      ],
    }),

    cancelRefinementJob: build.mutation<
      { message: string },
      { collectionId: string; sessionId: string }
    >({
      query: ({ collectionId, sessionId }) => ({
        url: `/${collectionId}/refinement-session/${sessionId}/cancel`,
        method: 'POST',
        body: undefined,
      }),
      invalidatesTags: (result, error, arg) => [
        { type: 'RefinementSession' as const, id: arg.sessionId },
      ],
    }),
  }),
});

export const {
  useGetRefinementSessionStateQuery,
  useCreateOrGetRefinementSessionMutation,
  useStartRefinementSessionMutation,
  useGetRefinementSessionJobMutation,
  usePostMessageToRefinementSessionMutation,
  usePostRubricUpdateToRefinementSessionMutation,
  useCancelRefinementJobMutation,
  useRetryLastMessageMutation,
  useListenToRefinementJobQuery,
  useLazyListenToRefinementJobQuery,
} = refinementApi;
