import { useCallback, useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useUpdateDataTableMutation } from '@/app/api/dataTableApi';
import {
  hydrateChat,
  addUserMessage,
  addAssistantMessage,
  addToQueryHistory,
  setInputError,
  clearChat,
  markSaved,
  selectChatState,
  type DataTableChatState,
} from '@/app/store/dqlChatSlice';
import type { DqlAutogenMessage } from '@/app/types/dqlTypes';
import type { ChatStateData } from '@/app/types/dataTableTypes';
import type { ChatMessage } from '@/app/types/transcriptTypes';
import type { RootState } from '@/app/store/store';

type DiffRecord = { anchorIndex: number; message: ChatMessage };

interface UseDqlChatResult {
  chatState: DataTableChatState | null;
  addMessage: (
    message: DqlAutogenMessage,
    requestId: string,
    currentQuery: string
  ) => void;
  addResponse: (
    message: DqlAutogenMessage,
    requestId: string,
    diffRecord?: DiffRecord | null
  ) => void;
  addHistoryEntry: (
    query: string,
    source: 'user' | 'agent',
    rowCount?: number
  ) => void;
  setError: (error: string | null, requestId?: string | null) => void;
  handleClearChat: () => void;
  isHydrated: boolean;
}

const DEBOUNCE_MS = 1000;

export function useDqlChat(
  dataTableId: string | null,
  collectionId: string | null,
  initialChatState?: ChatStateData | null
): UseDqlChatResult {
  const dispatch = useDispatch();
  const chatState = useSelector((state: RootState) =>
    selectChatState(state, dataTableId)
  );
  const [updateDataTable] = useUpdateDataTableMutation();

  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef<string | null>(null);
  const lastTrackedQueryRef = useRef<string | null>(null);

  // Hydrate from backend on mount (if not already hydrated)
  useEffect(() => {
    if (!dataTableId) return;
    if (chatState?.isHydrated) return;

    dispatch(
      hydrateChat({
        dataTableId,
        chatState: initialChatState ?? null,
      })
    );
  }, [dataTableId, initialChatState, chatState?.isHydrated, dispatch]);

  // Debounced save to backend when chat state changes
  useEffect(() => {
    if (!dataTableId || !collectionId || !chatState?.isDirty) return;

    const stateSignature = JSON.stringify({
      messages: chatState.messages,
      queryHistory: chatState.queryHistory,
    });

    if (stateSignature === lastSavedRef.current) {
      dispatch(markSaved({ dataTableId }));
      return;
    }

    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }

    saveTimeoutRef.current = setTimeout(() => {
      const chatStateData: ChatStateData = {
        messages: chatState.messages,
        queryHistory: chatState.queryHistory,
      };

      updateDataTable({
        collectionId,
        dataTableId,
        state: { chatState: chatStateData },
      })
        .unwrap()
        .then(() => {
          lastSavedRef.current = stateSignature;
          dispatch(markSaved({ dataTableId }));
        })
        .catch((error) => {
          console.error('Failed to save chat state', error);
        });
    }, DEBOUNCE_MS);

    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, [
    dataTableId,
    collectionId,
    chatState?.isDirty,
    chatState?.messages,
    chatState?.queryHistory,
    dispatch,
    updateDataTable,
  ]);

  const addMessage = useCallback(
    (
      message: DqlAutogenMessage,
      requestId: string,
      currentQuery: string
    ): void => {
      if (!dataTableId) return;
      dispatch(
        addUserMessage({
          dataTableId,
          message,
          requestId,
          currentQuery,
        })
      );
    },
    [dataTableId, dispatch]
  );

  const addResponse = useCallback(
    (
      message: DqlAutogenMessage,
      requestId: string,
      diffRecord?: DiffRecord | null
    ): void => {
      if (!dataTableId) return;
      dispatch(
        addAssistantMessage({
          dataTableId,
          message,
          requestId,
          diffRecord: diffRecord ?? null,
        })
      );
    },
    [dataTableId, dispatch]
  );

  const addHistoryEntry = useCallback(
    (query: string, source: 'user' | 'agent', rowCount?: number): void => {
      if (!dataTableId) return;
      const trimmed = query.trim();
      if (!trimmed || trimmed === lastTrackedQueryRef.current) return;
      lastTrackedQueryRef.current = trimmed;

      const entry = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
        query: trimmed,
        timestamp: new Date().toISOString(),
        source,
        lines: trimmed.split('\n').length,
        chars: trimmed.length,
        rowCount,
      };

      dispatch(addToQueryHistory({ dataTableId, entry }));
    },
    [dataTableId, dispatch]
  );

  const setError = useCallback(
    (error: string | null, requestId?: string | null): void => {
      if (!dataTableId) return;
      dispatch(setInputError({ dataTableId, error, requestId }));
    },
    [dataTableId, dispatch]
  );

  const handleClearChat = useCallback((): void => {
    if (!dataTableId) return;
    const currentHistory = chatState?.queryHistory ?? [];
    dispatch(clearChat({ dataTableId }));
    lastTrackedQueryRef.current = null;

    // Immediately save cleared state to backend (preserve query history)
    if (collectionId) {
      updateDataTable({
        collectionId,
        dataTableId,
        state: { chatState: { messages: [], queryHistory: currentHistory } },
      })
        .unwrap()
        .then(() => {
          lastSavedRef.current = JSON.stringify({
            messages: [],
            queryHistory: currentHistory,
          });
          dispatch(markSaved({ dataTableId }));
        })
        .catch((error) => {
          console.error('Failed to clear chat state', error);
        });
    }
  }, [
    dataTableId,
    collectionId,
    chatState?.queryHistory,
    dispatch,
    updateDataTable,
  ]);

  return {
    chatState,
    addMessage,
    addResponse,
    addHistoryEntry,
    setError,
    handleClearChat,
    isHydrated: chatState?.isHydrated ?? false,
  };
}
