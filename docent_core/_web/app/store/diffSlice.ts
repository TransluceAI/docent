import {
  createSlice,
  type PayloadAction,
  createAction,
} from '@reduxjs/toolkit';
import { diffApi } from '@/app/api/diffApi';
import { DiffQuery, DiffResult } from '@/app/types/diffTypes';

// Define the action for when a diff event arrives via SSE
export const diffResultReceived = createAction<{
  queryId: string;
  diff: DiffResult;
}>('diff/eventReceived');

export interface DiffState {
  queries: DiffQuery[];
  selectedQueryId: string | null;
  results: Record<string, DiffResult[]>;
}

const initialState: DiffState = {
  queries: [],
  selectedQueryId: null,
  results: {},
};

export const diffSlice = createSlice({
  name: 'diff',
  initialState,
  reducers: {
    setSelectedQueryId: (state, action: PayloadAction<string | null>) => {
      state.selectedQueryId = action.payload;
    },
    setDiffResults: (
      state,
      action: PayloadAction<{ queryId: string; results: DiffResult[] }>
    ) => {
      state.results[action.payload.queryId] = action.payload.results;
    },
  },
  extraReducers: (builder) => {
    builder
      // Handle diff results from SSE
      .addCase(diffResultReceived, (state, { payload }) => {
        const { queryId, diff } = payload;
        (state.results[queryId] ??= []).push(diff);
      })
      // Handle getAllDiffQueries
      .addMatcher(
        diffApi.endpoints.getAllDiffQueries.matchFulfilled,
        (state, action) => {
          state.queries = action.payload;
        }
      );
  },
});

export const { setSelectedQueryId, setDiffResults } = diffSlice.actions;

export const diffReducer = diffSlice.reducer;
