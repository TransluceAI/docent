import {
  createSlice,
  type PayloadAction,
  createAsyncThunk,
} from '@reduxjs/toolkit';

import { apiRestClient } from '../services/apiService';
import {
  RegexSnippet,
  TaskStats,
  TranscriptDiffViewport,
} from '../types/experimentViewerTypes';
import { PrimitiveFilter } from '../types/collectionTypes';
import { CollectionState } from './collectionSlice';
import { GraphDatum } from '../components/Graph';

import { RootState } from './store';
import { setToastNotification } from './toastSlice';

export interface ExperimentViewerState {
  // Global binning results
  binStats?: Record<string, TaskStats>;
  agentRunIds?: string[];
  outerBinStats?: Record<string, TaskStats>;
  dimIdsToFilterIds?: Record<string, string[]>;
  filtersMap?: Record<string, PrimitiveFilter>;
  // UI state of the viewer
  chartType?: 'bar' | 'line' | 'table';
  experimentViewerScrollPosition?: number;
  // paginationState?: ;
  // Diffing state
  selectedDiffTranscript?: string;
  selectedDiffSampleId?: string;
  transcriptDiffViewport?: TranscriptDiffViewport;
  // Regex snippets
  regexSnippets?: Record<string, RegexSnippet[]>;
  // Graph state
  graphData?: GraphDatum[];
  innerBinKey?: string;
  outerBinKey?: string;
}

const initialState: ExperimentViewerState = {
  chartType: 'table',
};

// Thunk to set inner and outer dimension IDs
export const setIODims = createAsyncThunk(
  'experimentViewer/setIODims',
  async (
    {
      innerBinKey,
      outerBinKey,
    }: {
      innerBinKey?: string;
      outerBinKey?: string;
    },
    { dispatch, getState }
  ) => {
    const state = getState() as { collection: CollectionState };
    const collectionId = state.collection.collectionId;

    if (!collectionId) {
      throw new Error('No collection ID available');
    }

    try {
      await apiRestClient.post(`/${collectionId}/set_io_bin_keys`, {
        inner_bin_key: innerBinKey,
        outer_bin_key: outerBinKey,
      });

      return { innerBinKey, outerBinKey };
    } catch (error) {
      console.error('Error setting IO dims:', error);
      throw error;
    }
  }
);

export const setIODimByMetadataKey = createAsyncThunk(
  'experimentViewer/setIODimByMetadataKey',
  async (
    {
      metadataKey,
      type,
    }: {
      metadataKey: string;
      type: 'inner' | 'outer';
    },
    { dispatch, getState }
  ) => {
    const state = getState() as RootState;
    const collectionId = state.collection.collectionId;

    if (!collectionId) {
      dispatch(
        setToastNotification({
          title: 'Configuration error',
          description: 'No collection ID available',
          variant: 'destructive',
        })
      );
      throw new Error('No collection ID available');
    }

    try {
      await apiRestClient.post(`/${collectionId}/io_bin_key_with_metadata_key`, {
        metadata_key: metadataKey,
        type: type,
      });
      // No specific data needs to be returned, success implies backend will publish updates
      return { metadataKey, type };
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error setting dimension by metadata key',
          description: `Failed to set ${type} dimension using metadata key ${metadataKey}`,
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

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
      state.binStats = stats;
    },
    setOuterBinStats: (state, action: PayloadAction<any>) => {
      let stats: Record<string, TaskStats> = {};
      if (action.payload && typeof action.payload === 'object') {
        if (
          'binIds' in action.payload &&
          typeof action.payload.binIds === 'object'
        ) {
          // Extract stats from the binIds field
          stats = action.payload.binIds;
        } else {
          stats = action.payload;
        }
      }
      state.outerBinStats = typeof stats === 'object' ? stats : {};
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
    setChartType: (state, action: PayloadAction<'bar' | 'line' | 'table'>) => {
      state.chartType = action.payload;
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
    setGraphData: (state, action: PayloadAction<GraphDatum[] | undefined>) => {
      state.graphData = action.payload;
    },
    resetExperimentViewerSlice: () => initialState,
  },
});

export const {
  setAgentRunIds,
  setBinStats,
  setOuterBinStats,
  setChartType,
  setExperimentViewerScrollPosition,
  setSelectedDiffTranscript,
  setSelectedDiffSampleId,
  setTranscriptDiffViewport,
  updateRegexSnippets,
  clearRegexSnippets,
  setGraphData,
  resetExperimentViewerSlice,
  setDimIdsToFilterIds,
  setFiltersMap,
} = experimentViewerSlice.actions;

export default experimentViewerSlice.reducer;
