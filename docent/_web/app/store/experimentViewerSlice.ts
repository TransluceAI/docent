import {
  createSlice,
  type PayloadAction,
  createAsyncThunk,
} from '@reduxjs/toolkit';

import { apiRestClient } from '../services/apiService';
import {
  MarginalizationResult,
  RegexSnippet,
  TaskStats,
  TranscriptDiffViewport,
} from '../types/experimentViewerTypes';
import { PrimitiveFilter } from '../types/frameTypes';

import { RootState } from './store';
import { setToastNotification } from './toastSlice';
import { GraphDatum } from '../components/Graph';

export interface ExperimentViewerState {
  // Global marginalization results
  statMarginals?: Record<string, TaskStats>;
  idMarginals?: Record<string, string[]>;
  outerStatMarginals?: Record<string, TaskStats>;
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
}

const initialState: ExperimentViewerState = {
  chartType: 'table',
};

// Create a thunk that accesses both slices
export const setStatMarginalsAndFilters = createAsyncThunk(
  'experimentViewer/setStatMarginalsAndFilters',
  async (marginalizationResult: MarginalizationResult, { dispatch }) => {
    dispatch(setStatMarginals(marginalizationResult));
    dispatch(setDimIdsToFilterIds(marginalizationResult.dim_ids_to_filter_ids));
    dispatch(
      setFiltersMap(
        marginalizationResult.filters_dict as Record<string, PrimitiveFilter>
      )
    );
  }
);

// Thunk to set inner and outer dimension IDs
export const setIODims = createAsyncThunk(
  'experimentViewer/setIODims',
  async (
    {
      innerDimId,
      outerDimId,
    }: {
      innerDimId?: string;
      outerDimId?: string;
    },
    { dispatch, getState }
  ) => {
    const state = getState() as RootState;
    const frameGridId = state.frame.frameGridId;

    if (!frameGridId) {
      dispatch(
        setToastNotification({
          title: 'Configuration error',
          description: 'No frame grid ID available',
          variant: 'destructive',
        })
      );
      throw new Error('No frame grid ID available');
    }

    try {
      await apiRestClient.post(`/${frameGridId}/io_dims`, {
        inner_dim_id: innerDimId,
        outer_dim_id: outerDimId,
      });

      return { innerDimId, outerDimId };
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error setting dimensions',
          description: 'Failed to set inner/outer dimensions',
          variant: 'destructive',
        })
      );
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
    const frameGridId = state.frame.frameGridId;

    if (!frameGridId) {
      dispatch(
        setToastNotification({
          title: 'Configuration error',
          description: 'No frame grid ID available',
          variant: 'destructive',
        })
      );
      throw new Error('No frame grid ID available');
    }

    try {
      await apiRestClient.post(`/${frameGridId}/io_dims_with_metadata_key`, {
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
    setStatMarginals: (state, action: PayloadAction<MarginalizationResult>) => {
      state.statMarginals = action.payload.marginals;
    },
    setOuterStatMarginals: (
      state,
      action: PayloadAction<MarginalizationResult>
    ) => {
      state.outerStatMarginals = action.payload.marginals;
    },
    setIdMarginals: (state, action: PayloadAction<MarginalizationResult>) => {
      state.idMarginals = action.payload.marginals;
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
  setStatMarginals,
  setIdMarginals,
  setOuterStatMarginals,
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
