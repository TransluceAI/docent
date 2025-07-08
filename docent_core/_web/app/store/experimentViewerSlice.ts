import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import {
  RegexSnippet,
  TaskStats,
  TranscriptDiffViewport,
} from '../types/experimentViewerTypes';
import { ChartSpec, PrimitiveFilter } from '../types/collectionTypes';

export interface ExperimentViewerState {
  // Global binning results
  binStats?: Record<string, Record<string, TaskStats>>;
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
  // Hover state for highlighting agent run cards
  hoveredAgentRunId?: string;
}

const initialState: ExperimentViewerState = {};

function parseKeys(binStats: Record<string, TaskStats>) {
  const key = Object.keys(binStats)[0];
  const pieces = key.split('|');
  if (pieces.length == 1) {
    const key1 = pieces[0].split(',')[0];
    return key1;
  }
  const key1 = pieces[0].split(',')[0];
  const key2 = pieces[1].split(',')[0];
  return `${key1}|${key2}`;
}

export const experimentViewerSlice = createSlice({
  name: 'experimentViewer',
  initialState,
  reducers: {
    setAgentRunIds: (state, action: PayloadAction<string[]>) => {
      state.agentRunIds = action.payload;
    },
    setBinStats: (state, action: PayloadAction<any>) => {
      let stats: Record<string, TaskStats> = {};
      if (action.payload && typeof action.payload === 'object') {
        if (
          'binStats' in action.payload &&
          typeof action.payload.binStats === 'object'
        ) {
          // The backend now sends computed statistics in the format: {bin_key: {score_key: {mean, ci, n}}}
          stats = action.payload.binStats;
        } else {
          stats = action.payload;
        }
      }
      if (!state.binStats) {
        state.binStats = {};
      }
      if (Object.keys(stats).length > 0) {
        state.binStats[parseKeys(stats)] = stats;
      }
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
    setHoveredAgentRunId: (state, action: PayloadAction<string | undefined>) => {
      state.hoveredAgentRunId = action.payload;
    },
    resetExperimentViewerSlice: () => initialState,
  },
});

export const {
  setAgentRunIds,
  setBinStats,
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
  setHoveredAgentRunId,
} = experimentViewerSlice.actions;

export default experimentViewerSlice.reducer;
