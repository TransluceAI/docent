import { useGetRefinementSessionStateQuery } from '../api/refinementApi';
import { useState, useEffect, useCallback, useRef } from 'react';
import { skipToken } from '@reduxjs/toolkit/query';
import {
  usePostMessageToRefinementSessionMutation,
  useListenToRefinementJobQuery,
  useCancelRefinementJobMutation,
  useStartRefinementSessionMutation,
} from '../api/refinementApi';
import { RefinementAgentSession } from '../store/refinementSlice';
import { ChatMessage } from '../types/transcriptTypes';
import { useRubricVersion } from '@/providers/use-rubric-version';
import { useRefinementTab } from '@/providers/use-refinement-tab';
import { toast } from '@/hooks/use-toast';
import { useAppDispatch } from '@/app/store/hooks';

interface UseRefinementChatOptions {
  collectionId: string;
  sessionId?: string;
  rubricId: string;
  showLabelsInContext: boolean;
}

interface UseRefinementChatReturn {
  rSession: RefinementAgentSession | null;
  onSendMessage: (message: string) => void;
  onCancelMessage: () => Promise<void>;
  messages: ChatMessage[];
  isSSEConnected: boolean;
  inputErrorMessage?: string;
}

const useRefinementChat = ({
  collectionId,
  sessionId,
  rubricId,
  showLabelsInContext,
}: UseRefinementChatOptions): UseRefinementChatReturn => {
  const dispatch = useAppDispatch();
  const { refinementJobId, setRefinementJobId } = useRefinementTab();
  const { refetchLatestVersion } = useRubricVersion();

  // Start or get active refinement job
  const [startRefinementSession] = useStartRefinementSessionMutation();
  useEffect(() => {
    if (!sessionId) return;
    startRefinementSession({ collectionId, sessionId })
      .unwrap()
      .then((res) => {
        if (res?.job_id) {
          setRefinementJobId(res.job_id);
        }
      })
      .catch(() => {});
  }, [collectionId, sessionId, startRefinementSession, setRefinementJobId]);

  // Handle sending messages to the refinement session
  const [postMessage] = usePostMessageToRefinementSessionMutation();
  const onSendMessage = useCallback(
    (message: string) => {
      if (!sessionId) return;
      postMessage({
        collectionId,
        sessionId,
        message,
        showLabelsInContext,
      })
        .unwrap()
        .then((res) => {
          if (res?.job_id) setRefinementJobId(res.job_id);
        })
        .catch(() => {});
    },
    [
      collectionId,
      sessionId,
      showLabelsInContext,
      postMessage,
      setRefinementJobId,
    ]
  );

  // Handle canceling the refinement session and cleaning up local state
  const [cancelRefinementSession] = useCancelRefinementJobMutation();
  const onCancelMessage = useCallback(async () => {
    if (!sessionId) return;
    setRefinementJobId(null);
    await cancelRefinementSession({ collectionId, sessionId })
      .unwrap()
      .catch(() => {
        toast({
          title: 'Error',
          description: 'Failed to cancel refinement session',
          variant: 'destructive',
        });
      });
  }, [collectionId, sessionId, cancelRefinementSession, setRefinementJobId]);

  // Start listening to the job state via SSE when we have a jobId
  const {
    data: { isSSEConnected, rSession } = {
      isSSEConnected: false,
      rSession: null,
    },
  } = useListenToRefinementJobQuery(
    refinementJobId ? { collectionId, jobId: refinementJobId } : skipToken
  );

  // Get the session state from DB if there was no active job to grab it from
  const { data: initialState } = useGetRefinementSessionStateQuery(
    !rSession && sessionId ? { collectionId, sessionId } : skipToken
  );

  // Persist the latest non-null session to prevent UI flicker when a new SSE
  // connection is established and the query briefly returns null before the
  // first message arrives.
  const [persistedSession, setPersistedSession] =
    useState<RefinementAgentSession | null>(null);

  // Keep a state to prevent flickering when sending a message
  useEffect(() => {
    if (rSession) {
      setPersistedSession(rSession);
    } else if (initialState) {
      setPersistedSession(initialState);
    }
  }, [rSession, initialState]);

  // Listen for rubric version changes on the refinement session
  const lastSeenRubricVersionRef = useRef<number | null>(null);
  useEffect(() => {
    const currentVersion = persistedSession?.rubric_version ?? null;
    if (
      currentVersion !== null &&
      currentVersion !== lastSeenRubricVersionRef.current
    ) {
      lastSeenRubricVersionRef.current = currentVersion;
      refetchLatestVersion();
    }
  }, [refetchLatestVersion, persistedSession?.rubric_version]);

  return {
    rSession: persistedSession,
    onSendMessage,
    onCancelMessage,
    messages: persistedSession?.messages ?? [],
    isSSEConnected: Boolean(refinementJobId) && isSSEConnected,
    inputErrorMessage: persistedSession?.error_message,
  };
};

export default useRefinementChat;
