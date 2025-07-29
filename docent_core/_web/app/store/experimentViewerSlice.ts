import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import {
  RegexSnippet,
  TranscriptDiffViewport,
} from '../types/experimentViewerTypes';
import { ChartSpec, PrimitiveFilter } from '../types/collectionTypes';

export interface ExperimentViewerState {
  agentRunIds?: string[];
  dimIdsToFilterIds?: Record<string, string[]>;
  filtersMap?: Record<string, PrimitiveFilter>;
  experimentViewerScrollPosition?: number;
  // paginationState?: ;
  // Diffing state
  selectedDiffTranscript?: string;
  selectedDiffSampleId?: string;
  transcriptDiffViewport?: TranscriptDiffViewport;
  // Regex snippets
  regexSnippets?: Record<string, RegexSnippet[]>;
  // Graph state
  charts?: ChartSpec[];
}

const initialState: ExperimentViewerState = {};

export const experimentViewerSlice = createSlice({
  name: 'experimentViewer',
  initialState,
  reducers: {
    setAgentRunIds: (state, action: PayloadAction<string[]>) => {
      state.agentRunIds = action.payload;
    },
    setDimIdsToFilterIds: (
      state,
      action: PayloadAction<Record<string, string[]>>
    ) => {
      state.dimIdsToFilterIds = action.payload;
    },
    setFiltersMap: (
      state,
      action: PayloadAction<Record<string, PrimitiveFilter>>
    ) => {
      state.filtersMap = action.payload;
    },
    setExperimentViewerScrollPosition: (
      state,
      action: PayloadAction<number>
    ) => {
      state.experimentViewerScrollPosition = action.payload;
    },
    setSelectedDiffTranscript: (state, action: PayloadAction<string>) => {
      state.selectedDiffTranscript = action.payload;
    },
    setSelectedDiffSampleId: (state, action: PayloadAction<string>) => {
      state.selectedDiffSampleId = action.payload;
    },
    setTranscriptDiffViewport: (
      state,
      action: PayloadAction<TranscriptDiffViewport>
    ) => {
      state.transcriptDiffViewport = action.payload;
    },
    updateRegexSnippets: (
      state,
      action: PayloadAction<Record<string, RegexSnippet[]>>
    ) => {
      state.regexSnippets = {
        ...state.regexSnippets,
        ...action.payload,
      };
    },
    clearRegexSnippets: (state) => {
      state.regexSnippets = undefined;
    },
    setCharts: (state, action: PayloadAction<ChartSpec[]>) => {
      state.charts = action.payload;
    },
    resetExperimentViewerSlice: () => initialState,
  },
});

export const {
  setAgentRunIds,
  setExperimentViewerScrollPosition,
  setSelectedDiffTranscript,
  setSelectedDiffSampleId,
  setTranscriptDiffViewport,
  updateRegexSnippets,
  clearRegexSnippets,
  resetExperimentViewerSlice,
  setDimIdsToFilterIds,
  setFiltersMap,
  setCharts,
} = experimentViewerSlice.actions;

export default experimentViewerSlice.reducer;
