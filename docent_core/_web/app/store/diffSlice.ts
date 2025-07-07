import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { diffApi } from '@/app/api/diffApi';
import { DiffQuery, DiffResult } from '@/app/types/diffTypes';

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
      // Handle getAllDiffQueries
      .addMatcher(
        diffApi.endpoints.getAllDiffQueries.matchFulfilled,
        (state, action) => {
          state.queries = action.payload;
        }
      )
      // Handle listenForDiffResults
      .addMatcher(
        diffApi.endpoints.listenForDiffResults.matchFulfilled,
        (state, action) => {
          // Store results by query ID (extract from the query params)
          const queryId = state.selectedQueryId;
          if (queryId) {
            state.results[queryId] = action.payload;
          }
        }
      );
  },
});

export const { setSelectedQueryId, setDiffResults } = diffSlice.actions;

export const diffReducer = diffSlice.reducer;
