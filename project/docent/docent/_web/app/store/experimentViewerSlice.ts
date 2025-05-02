import { createSlice, PayloadAction, createAsyncThunk } from '@reduxjs/toolkit';
import {
  AttributeWithCitation,
  MarginalizationResult,
  OrganizationMethod,
  RegexSnippet,
  StreamedAttribute,
  TaskStats,
  TranscriptDiffViewport,
  TranscriptMetadataField,
} from '../types/experimentViewerTypes';
import {
  FrameDimension,
  FrameFilter,
  PrimitiveFilter,
} from '../types/frameTypes';
import { RootState } from './store';

export interface ExperimentViewerState {
  // Global marginalization results
  statMarginals?: Record<string, TaskStats>;
  idMarginals?: Record<string, string[]>;
  sampleStatMarginals?: Record<string, TaskStats>;
  experimentStatMarginals?: Record<string, TaskStats>;
  interventionDescriptionMarginals?: Record<string, string[]>;
  // Global filters
  sampleFilters?: PrimitiveFilter[];
  experimentFilters?: PrimitiveFilter[];
  // UI state of the viewer
  expandedOuter?: Record<string, boolean>; // Object replacement for Set
  expandedInner?: Record<string, Record<string, boolean>>;
  experimentViewerScrollPosition?: number;
  organizationMethod: OrganizationMethod;
  // Diffing state
  selectedDiffTranscript?: string;
  selectedDiffSampleId?: string;
  transcriptDiffViewport?: TranscriptDiffViewport;
  // Regex snippets
  regexSnippets?: Record<string, RegexSnippet[]>;
}

const initialState: ExperimentViewerState = {
  organizationMethod: 'experiment',
};

// Create a thunk that accesses both slices
export const setStatMarginalsAndFilters = createAsyncThunk(
  'experimentViewer/setStatMarginalsAndFilters',
  async (
    marginalizationResult: MarginalizationResult,
    { dispatch, getState }
  ) => {
    // First set the stat marginals
    dispatch(setStatMarginals(marginalizationResult));

    // Get the frame state to access sampleDimId and experimentDimId
    const state = getState() as RootState;
    const { sampleDimId, experimentDimId } = state.frame;

    // Update sample and experiment filters
    if (sampleDimId) {
      const sampleFilters = marginalizationResult.dim_ids_to_filter_ids[
        sampleDimId
      ].map(
        (filter_id) =>
          marginalizationResult.filters_dict[filter_id] as PrimitiveFilter
      );
      dispatch(setSampleFilters(sampleFilters));
    }
    if (experimentDimId) {
      const experimentFilters = marginalizationResult.dim_ids_to_filter_ids[
        experimentDimId
      ].map(
        (filter_id) =>
          marginalizationResult.filters_dict[filter_id] as PrimitiveFilter
      );
      dispatch(setExperimentFilters(experimentFilters));
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
    setSampleStatMarginals: (
      state,
      action: PayloadAction<MarginalizationResult>
    ) => {
      state.sampleStatMarginals = action.payload.marginals;
    },
    setExperimentStatMarginals: (
      state,
      action: PayloadAction<MarginalizationResult>
    ) => {
      state.experimentStatMarginals = action.payload.marginals;
    },
    setIdMarginals: (state, action: PayloadAction<MarginalizationResult>) => {
      state.idMarginals = action.payload.marginals;
    },
    setInterventionDescriptionMarginals: (
      state,
      action: PayloadAction<MarginalizationResult>
    ) => {
      state.interventionDescriptionMarginals = action.payload.marginals;
    },
    setSampleFilters: (state, action: PayloadAction<PrimitiveFilter[]>) => {
      state.sampleFilters = action.payload;
    },
    setExperimentFilters: (state, action: PayloadAction<PrimitiveFilter[]>) => {
      state.experimentFilters = action.payload;
    },
    clearExpandedOuter: (state) => {
      state.expandedOuter = {};
    },
    clearExpandedInner: (state) => {
      state.expandedInner = {};
    },
    addExpandedOuter: (state, action: PayloadAction<string>) => {
      state.expandedOuter = { ...state.expandedOuter, [action.payload]: true };
    },
    removeExpandedOuter: (state, action: PayloadAction<string>) => {
      const { [action.payload]: _, ...rest } = state.expandedOuter ?? {};
      state.expandedOuter = rest;
    },
    addExpandedInner: (
      state,
      action: PayloadAction<{ outerId: string; innerId: string }>
    ) => {
      const { outerId, innerId } = action.payload;
      state.expandedInner = {
        ...state.expandedInner,
        [outerId]: {
          ...(state.expandedInner?.[outerId] || {}),
          [innerId]: true,
        },
      };
    },
    removeExpandedInner: (
      state,
      action: PayloadAction<{ outerId: string; innerId: string }>
    ) => {
      const { outerId, innerId } = action.payload;
      if (state.expandedInner?.[outerId]) {
        const { [innerId]: _, ...rest } = state.expandedInner[outerId];
        state.expandedInner = {
          ...state.expandedInner,
          [outerId]: rest,
        };
      }
    },
    setExperimentViewerScrollPosition: (
      state,
      action: PayloadAction<number>
    ) => {
      state.experimentViewerScrollPosition = action.payload;
    },
    setOrganizationMethod: (
      state,
      action: PayloadAction<OrganizationMethod>
    ) => {
      state.organizationMethod = action.payload;
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
    resetExperimentViewerSlice: () => initialState,
  },
});

export const {
  setStatMarginals,
  setIdMarginals,
  setSampleStatMarginals,
  setExperimentStatMarginals,
  setInterventionDescriptionMarginals,
  setSampleFilters,
  setExperimentFilters,
  clearExpandedOuter,
  clearExpandedInner,
  addExpandedOuter,
  removeExpandedOuter,
  addExpandedInner,
  removeExpandedInner,
  setExperimentViewerScrollPosition,
  setOrganizationMethod,
  setSelectedDiffTranscript,
  setSelectedDiffSampleId,
  setTranscriptDiffViewport,
  updateRegexSnippets,
  clearRegexSnippets,
  resetExperimentViewerSlice,
} = experimentViewerSlice.actions;

export default experimentViewerSlice.reducer;
