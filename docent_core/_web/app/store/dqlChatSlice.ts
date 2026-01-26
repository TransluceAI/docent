import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { DqlAutogenMessage } from '@/app/types/dqlTypes';
import type {
  ChatStateData,
  QueryHistoryEntry,
} from '@/app/types/dataTableTypes';
import type { ChatMessage } from '@/app/types/transcriptTypes';

type DiffRecord = { anchorIndex: number; message: ChatMessage };

export interface DataTableChatState {
  messages: DqlAutogenMessage[];
  diffMessages: DiffRecord[];
  queryHistory: QueryHistoryEntry[];
  lastSubmittedQuery: string | null;
  inputError: string | null;
  pendingRequestId: string | null;
  isDirty: boolean;
  isHydrated: boolean;
}

interface DqlChatState {
  chats: Record<string, DataTableChatState>;
}

const initialState: DqlChatState = {
  chats: {},
};

const createEmptyChatState = (): DataTableChatState => ({
  messages: [],
  diffMessages: [],
  queryHistory: [],
  lastSubmittedQuery: null,
  inputError: null,
  pendingRequestId: null,
  isDirty: false,
  isHydrated: false,
});

const ensureChatState = (
  state: DqlChatState,
  dataTableId: string
): DataTableChatState => {
  if (!state.chats[dataTableId]) {
    state.chats[dataTableId] = createEmptyChatState();
  }
  return state.chats[dataTableId];
};

export const dqlChatSlice = createSlice({
  name: 'dqlChat',
  initialState,
  reducers: {
    hydrateChat: (
      state,
      action: PayloadAction<{
        dataTableId: string;
        chatState: ChatStateData | null;
      }>
    ) => {
      const { dataTableId, chatState } = action.payload;
      const chat = ensureChatState(state, dataTableId);
      chat.messages = chatState?.messages ?? [];
      chat.queryHistory = chatState?.queryHistory ?? [];
      chat.diffMessages = [];
      chat.lastSubmittedQuery = null;
      chat.inputError = null;
      chat.pendingRequestId = null;
      chat.isDirty = false;
      chat.isHydrated = true;
    },

    addUserMessage: (
      state,
      action: PayloadAction<{
        dataTableId: string;
        message: DqlAutogenMessage;
        requestId: string;
        currentQuery: string;
      }>
    ) => {
      const { dataTableId, message, requestId, currentQuery } = action.payload;
      const chat = ensureChatState(state, dataTableId);
      chat.messages.push(message);
      chat.pendingRequestId = requestId;
      chat.lastSubmittedQuery = currentQuery;
      chat.inputError = null;
      chat.isDirty = true;
    },

    addAssistantMessage: (
      state,
      action: PayloadAction<{
        dataTableId: string;
        message: DqlAutogenMessage;
        requestId: string;
        diffRecord?: DiffRecord | null;
      }>
    ) => {
      const { dataTableId, message, requestId, diffRecord } = action.payload;
      const chat = state.chats[dataTableId];
      if (!chat || chat.pendingRequestId !== requestId) {
        return;
      }
      chat.messages.push(message);
      if (diffRecord) {
        const filtered = chat.diffMessages.filter(
          (entry) => entry.anchorIndex !== diffRecord.anchorIndex
        );
        filtered.push(diffRecord);
        chat.diffMessages = filtered;
      }
      chat.pendingRequestId = null;
      chat.isDirty = true;
    },

    addToQueryHistory: (
      state,
      action: PayloadAction<{
        dataTableId: string;
        entry: QueryHistoryEntry;
      }>
    ) => {
      const { dataTableId, entry } = action.payload;
      const chat = ensureChatState(state, dataTableId);
      const filtered = chat.queryHistory.filter((e) => e.query !== entry.query);
      chat.queryHistory = [entry, ...filtered].slice(0, 20);
      chat.isDirty = true;
    },

    setInputError: (
      state,
      action: PayloadAction<{
        dataTableId: string;
        error: string | null;
        requestId?: string | null;
      }>
    ) => {
      const { dataTableId, error, requestId } = action.payload;
      const chat = state.chats[dataTableId];
      if (!chat) return;
      if (requestId && chat.pendingRequestId !== requestId) {
        return;
      }
      chat.inputError = error;
      if (requestId) {
        chat.pendingRequestId = null;
      }
    },

    clearChat: (state, action: PayloadAction<{ dataTableId: string }>) => {
      const { dataTableId } = action.payload;
      const chat = state.chats[dataTableId];
      if (!chat) return;
      chat.messages = [];
      chat.diffMessages = [];
      // Preserve queryHistory - only clear the conversation
      chat.lastSubmittedQuery = null;
      chat.inputError = null;
      chat.pendingRequestId = null;
      chat.isDirty = true;
    },

    markSaved: (state, action: PayloadAction<{ dataTableId: string }>) => {
      const { dataTableId } = action.payload;
      const chat = state.chats[dataTableId];
      if (!chat) return;
      chat.isDirty = false;
    },

    removeChat: (state, action: PayloadAction<{ dataTableId: string }>) => {
      const { dataTableId } = action.payload;
      delete state.chats[dataTableId];
    },
  },
});

export const {
  hydrateChat,
  addUserMessage,
  addAssistantMessage,
  addToQueryHistory,
  setInputError,
  clearChat,
  markSaved,
  removeChat,
} = dqlChatSlice.actions;

export const selectChatState = (
  state: { dqlChat: DqlChatState },
  dataTableId: string | null
): DataTableChatState | null => {
  if (!dataTableId) return null;
  return state.dqlChat.chats[dataTableId] ?? null;
};

export default dqlChatSlice.reducer;
