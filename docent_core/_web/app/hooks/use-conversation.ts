import { useEffect, useState, useCallback } from 'react';
import { skipToken } from '@reduxjs/toolkit/query';
import {
  useGetConversationStateQuery,
  useGetActiveConversationJobQuery,
  useListenToConversationJobQuery,
  usePostConversationMessageMutation,
} from '@/app/api/chatApi';
import { ModelOption } from '@/app/store/rubricSlice';
import { ChatMessage } from '@/app/types/transcriptTypes';

export interface UseConversationOptions {
  sessionId: string | null;
}

export interface UseConversationReturn {
  sessionId: string | null;
  chatState: any;
  messages: ChatMessage[];
  isLoading: boolean;
  sendMessage: (message: string, chatModel?: ModelOption) => void;
  errorMessage?: string;
  errorId?: string;
  estimatedInputTokens?: number;
}

export function useConversation({
  sessionId,
}: UseConversationOptions): UseConversationReturn {
  const chatStateQuery = useGetConversationStateQuery(
    sessionId ? { sessionId } : skipToken
  );

  const activeJobQuery = useGetActiveConversationJobQuery(
    sessionId ? { sessionId } : skipToken
  );

  const [jobId, setJobId] = useState<string | null>(null);
  const [persistedMessages, setPersistedMessages] = useState<
    ChatMessage[] | undefined
  >(undefined);

  const chatState = chatStateQuery.data;
  const enabled = !!sessionId;

  useEffect(() => {
    if (!enabled) return;
    setJobId(activeJobQuery.data?.job_id || null);
  }, [activeJobQuery.data?.job_id, enabled]);

  useEffect(() => {
    setJobId(null);
  }, [sessionId]);

  const jobListenQuery = useListenToConversationJobQuery(
    jobId ? { jobId } : skipToken
  );

  const sse = jobId && enabled ? jobListenQuery.currentData : undefined;
  const isSSEConnected = sse?.isSSEConnected ?? false;
  const sseMessages = sse?.messages ?? [];
  const sseError = sse?.error_message;
  const sseErrorId = sse?.error_id;
  const estimatedInputTokens =
    sse?.estimated_input_tokens ?? chatState?.estimated_input_tokens;

  useEffect(() => {
    if (sseMessages && sseMessages.length > 0) {
      setPersistedMessages(sseMessages);
    }
  }, [sseMessages]);

  useEffect(() => {
    setPersistedMessages(undefined);
  }, [chatState]);

  const messages = persistedMessages || chatState?.messages || [];

  const [postMessageMutation] = usePostConversationMessageMutation();

  const sendMessage = useCallback(
    (message: string, chatModel?: ModelOption) => {
      if (!enabled || !chatState) return;

      postMessageMutation({
        sessionId: chatState.id,
        message,
        chatModel,
      })
        .unwrap()
        .then((res: any) => {
          if (res?.job_id) setJobId(res.job_id);
        })
        .catch((error: any) => {
          console.error('Failed to post chat message:', error);
        });
    },
    [enabled, chatState, postMessageMutation]
  );

  return {
    sessionId,
    chatState,
    messages,
    isLoading: isSSEConnected,
    sendMessage,
    errorMessage: sseError,
    errorId: sseErrorId,
    estimatedInputTokens,
  };
}
