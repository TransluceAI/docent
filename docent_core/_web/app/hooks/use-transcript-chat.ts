import { useCallback, useEffect, useState, useMemo } from 'react';
import { skipToken } from '@reduxjs/toolkit/query';
import {
  useGetChatStateQuery,
  useGetOrCreateChatSessionMutation,
  usePostChatMessageMutation,
  useListenToChatJobQuery,
  useGetActiveChatJobQuery,
  chatApi,
} from '@/app/api/chatApi';
import { useAppDispatch } from '@/app/store/hooks';
import { setRunCitations } from '@/app/store/transcriptSlice';
import { JudgeResultWithCitations, ModelOption } from '@/app/store/rubricSlice';

export interface UseTranscriptChatOptions {
  runId: string;
  collectionId: string;
  judgeResult?: JudgeResultWithCitations | null;
}

export function useTranscriptChat({
  runId,
  collectionId,
  judgeResult,
}: UseTranscriptChatOptions) {
  const judgeResultCitations = judgeResult?.output.explanation?.citations;
  const dispatch = useAppDispatch();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  // Get current chat state when session is available (for initial load)
  const { data: chatState } = useGetChatStateQuery(
    sessionId ? { collectionId, runId, sessionId } : skipToken
  );

  // Check if there is an active job for this session (to resume SSE after refresh)
  const { data: activeJobData } = useGetActiveChatJobQuery(
    sessionId ? { collectionId, runId, sessionId } : skipToken
  );
  useEffect(() => {
    setJobId(activeJobData?.job_id || null);
  }, [activeJobData?.job_id]);

  const [getOrCreateChatSession] = useGetOrCreateChatSessionMutation();

  const jobQueryParams =
    jobId && collectionId ? { collectionId, runId, jobId } : skipToken;
  // Start listening to the job state via SSE when we have a jobId
  const jobQuery = useListenToChatJobQuery(jobQueryParams);
  const sse = jobId ? jobQuery.currentData : undefined;
  const isSSEConnected = sse?.isSSEConnected ?? false;
  const sseMessages = sse?.messages ?? [];
  const sseError = sse?.error_message;
  const estimatedInputTokens =
    sse?.estimated_input_tokens ?? chatState?.estimated_input_tokens;

  // Get messages from SSE if available, otherwise from initial state
  const messages = useMemo(() => {
    if (jobId && sseMessages && sseMessages.length > 0) {
      return sseMessages;
    }
    return chatState?.messages || [];
  }, [jobId, sseMessages, chatState?.messages]);

  // Start the session
  useEffect(() => {
    if (!collectionId || !runId) return;

    getOrCreateChatSession({
      collectionId,
      runId,
      resultId: judgeResult?.id || null,
    })
      .unwrap()
      .then((res) => {
        setSessionId(res.session_id);
      })
      .catch((error) => {
        console.error(
          'Failed to create or get transcript chat session:',
          error
        );
      });
  }, [collectionId, runId, judgeResult?.id, getOrCreateChatSession]);

  // Auto-populate citations from chat messages to enable transcript highlighting
  useEffect(() => {
    if (messages.length > 0) {
      // Extract citations from all assistant messages
      const chatCitations = messages
        .filter(
          (msg) =>
            msg.role === 'assistant' &&
            'citations' in msg &&
            msg.citations &&
            msg.citations.length > 0
        )
        .flatMap((msg) => (msg as any).citations!);

      // Merge with existing judge result citations if they exist
      const allCitationsArray = [...chatCitations];
      if (judgeResultCitations && judgeResultCitations.length > 0) {
        allCitationsArray.push(...judgeResultCitations);
      }

      // Only update if we have citations to avoid unnecessary dispatches
      if (allCitationsArray.length > 0) {
        dispatch(setRunCitations({ [runId]: allCitationsArray }));
      }
    }
  }, [messages, judgeResultCitations, dispatch]);

  // Handle sending messages
  const [postMessage] = usePostChatMessageMutation();
  const sendMessage = useCallback(
    (message: string, chatModel?: ModelOption) => {
      if (!sessionId) return;
      postMessage({ collectionId, runId, sessionId, message, chatModel })
        .unwrap()
        .then((res) => {
          if (res?.job_id) setJobId(res.job_id);
        })
        .catch((error) => {
          console.error('Failed to post transcript chat message:', error);
        });
    },
    [collectionId, runId, sessionId, postMessage]
  );

  // Handle reset chat
  const resetChat = useCallback(() => {
    if (!sessionId) return;

    dispatch(setRunCitations({ [runId]: judgeResultCitations || [] }));

    // Clear current session's cache before creating new one
    dispatch(
      chatApi.util.invalidateTags([{ type: 'ChatSession', id: sessionId }])
    );

    // Create a new session with force_create=true
    getOrCreateChatSession({
      collectionId,
      runId,
      resultId: judgeResult?.id || null,
      forceCreate: true,
    })
      .unwrap()
      .then((res) => {
        setSessionId(res.session_id);
        setJobId(null);
      })
      .catch((error) => {
        console.error('Failed to reset transcript chat session:', error);
      });
  }, [
    dispatch,
    collectionId,
    runId,
    sessionId,
    judgeResult?.id,
    getOrCreateChatSession,
  ]);

  return {
    sessionId,
    messages,
    isLoading: isSSEConnected,
    sendMessage,
    resetChat,
    chatState,
    errorMessage: sseError,
    estimatedInputTokens,
  };
}
