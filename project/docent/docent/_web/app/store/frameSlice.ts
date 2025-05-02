import { createSlice, PayloadAction, createAsyncThunk } from '@reduxjs/toolkit';
import {
  AttributeWithCitation,
  MarginalizationResult,
  RegexSnippet,
  StreamedAttribute,
  TaskStats,
  TranscriptMetadataField,
} from '../types/experimentViewerTypes';
import {
  ComplexFrameFilter,
  FrameDimension,
  FrameFilter,
  FrameGrid,
  Marginals,
} from '../types/frameTypes';
import socketService from '../services/socketService';
import { apiBaseClient, apiRestClient } from '../services/apiService';
import { setToastNotification } from './toastSlice';
import { resetExperimentViewerSlice } from './experimentViewerSlice';
import { resetTranscriptSlice } from './transcriptSlice';
import { resetAttributeFinderSlice } from './attributeFinderSlice';

export interface FrameState {
  // Available eval IDs
  evalIds?: string[];
  // Available frame grids
  frameGrids?: FrameGrid[];
  isLoadingFrameGrids: boolean;
  // FrameGrid state
  dimensions?: FrameDimension[];
  baseFilter?: ComplexFrameFilter;
  // Metadata
  transcriptMetadataFields?: TranscriptMetadataField[];
  transcriptMetadata?: Record<string, Record<string, any>>;
  // Global variables
  frameGridId?: string;
  evalId?: string;
  sampleDimId?: string;
  experimentDimId?: string;
  marginals?: Marginals;
}

const initialState: FrameState = {
  isLoadingFrameGrids: false,
};

export const fetchFrameGrids = createAsyncThunk(
  'frame/fetchFrameGrids',
  async (_, { dispatch }) => {
    dispatch(setIsLoadingFrameGrids(true));
    try {
      const response = await apiRestClient.get('/framegrids');
      dispatch(setFrameGrids(response.data));
      return response.data;
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error fetching frame grids',
          description: 'Please try again in a moment',
          variant: 'destructive',
        })
      );
      throw error;
    } finally {
      dispatch(setIsLoadingFrameGrids(false));
    }
  }
);

export const fetchEvalIds = createAsyncThunk(
  'frame/fetchEvalIds',
  async (_, { dispatch }) => {
    try {
      const response = await apiBaseClient.get('/eval_ids');
      dispatch(setEvalIds(response.data));
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error fetching evaluation IDs',
          description: 'Please try again in a moment',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const initSession = createAsyncThunk(
  'frame/initSession',
  async (evalId: string, { dispatch }) => {
    try {
      // Reset all states
      // dispatch(resetFrameSlice());
      // dispatch(resetExperimentViewerSlice());
      // dispatch(resetAttributeFinderSlice());
      // dispatch(resetTranscriptSlice());

      const response = await apiRestClient.post('/join', {
        fg_id: evalId,
      });
      const { fg_id } = response.data;

      // Set various IDs
      dispatch(setFrameGridId(fg_id));
      dispatch(setEvalId(evalId));
      dispatch(setSampleDimId(response.data.sample_dim_id));
      dispatch(setExperimentDimId(response.data.experiment_dim_id));

      dispatch(getTranscriptMetadataFields());
      // Start a broker socket to listen for state updates
      await socketService.initSocket(fg_id);
      // Only request state after connection is established
      dispatch(getState(evalId));
    } catch (error) {
      // Cleanup on error
      socketService.closeSocket();
      dispatch(setFrameGridId(undefined));
      dispatch(setEvalId(undefined));
      dispatch(setSampleDimId(undefined));
      dispatch(setExperimentDimId(undefined));
      dispatch(
        setToastNotification({
          title: 'Error connecting to server',
          description: 'Please try again in a moment',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const getState = createAsyncThunk(
  'frame/getState',
  async (evalId: string, { dispatch, getState }) => {
    const state = getState() as { frame: FrameState };
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
      await apiRestClient.get(`/state?fg_id=${frameGridId}`);
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error getting state',
          description: 'Failed to retrieve application state',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const getTranscriptMetadataFields = createAsyncThunk(
  'frame/getTranscriptMetadataFields',
  async (_, { dispatch, getState }) => {
    const state = getState() as { frame: FrameState };
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
      const response = await apiRestClient.get(
        `/transcript_metadata_fields?fg_id=${frameGridId}`
      );
      dispatch(setTranscriptMetadataFields(response.data.fields));
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error fetching metadata fields',
          description: 'Failed to retrieve transcript metadata fields',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const getTranscriptMetadata = createAsyncThunk(
  'frame/getTranscriptMetadata',
  async (datapointIds: string[], { dispatch, getState }) => {
    const state = getState() as { frame: FrameState };
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
      const response = await apiRestClient.post('/datapoint_metadata', {
        fg_id: frameGridId,
        datapoint_ids: datapointIds,
      });
      dispatch(updateTranscriptMetadata(response.data));
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error fetching transcript metadata',
          description: 'Failed to retrieve datapoint metadata',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const addAttributeDimension = createAsyncThunk(
  'frame/addAttributeDimension',
  async (attribute: string, { dispatch, getState }) => {
    const state = getState() as { frame: FrameState };
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
      const response = await apiRestClient.post('/dimension', {
        fg_id: frameGridId,
        dim: {
          name: attribute,
          attribute: attribute,
        },
      });
      return response.data; // ID of the posted dimension
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error adding dimension',
          description: 'Failed to add attribute dimension',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const deleteDimension = createAsyncThunk(
  'frame/deleteDimension',
  async (dimensionId: string, { dispatch, getState }) => {
    const state = getState() as { frame: FrameState };
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
      await apiRestClient.delete(
        `/dimension?fg_id=${frameGridId}&dim_id=${dimensionId}`
      );
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error deleting dimension',
          description: 'Failed to delete dimension',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const deleteFilter = createAsyncThunk(
  'frame/deleteFilter',
  async (filterId: string, { dispatch, getState }) => {
    const state = getState() as { frame: FrameState };
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
      await apiRestClient.delete(
        `/filter?fg_id=${frameGridId}&filter_id=${filterId}`
      );
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error deleting filter',
          description: 'Failed to delete filter',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const editFilter = createAsyncThunk(
  'frame/editFilter',
  async (
    { filterId, newPredicate }: { filterId: string; newPredicate: string },
    { dispatch, getState }
  ) => {
    const state = getState() as { frame: FrameState };
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
      await apiRestClient.post('/filter', {
        fg_id: frameGridId,
        filter_id: filterId,
        new_predicate: newPredicate,
      });
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error editing filter',
          description: 'Failed to update filter predicate',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const frameSlice = createSlice({
  name: 'frame',
  initialState,
  reducers: {
    setMarginals: (state, action: PayloadAction<Marginals>) => {
      state.marginals = action.payload;
    },
    setDimensions: (state, action: PayloadAction<FrameDimension[]>) => {
      state.dimensions = action.payload;
    },
    setBaseFilter: (
      state,
      action: PayloadAction<ComplexFrameFilter | undefined>
    ) => {
      state.baseFilter = action.payload;
    },
    setTranscriptMetadataFields: (
      state,
      action: PayloadAction<TranscriptMetadataField[]>
    ) => {
      state.transcriptMetadataFields = action.payload;
    },
    updateTranscriptMetadata: (
      state,
      action: PayloadAction<Record<string, Record<string, any>>>
    ) => {
      state.transcriptMetadata = {
        ...state.transcriptMetadata,
        ...action.payload,
      };
    },
    setFrameGridId: (state, action: PayloadAction<string | undefined>) => {
      state.frameGridId = action.payload;
    },
    setEvalId: (state, action: PayloadAction<string | undefined>) => {
      state.evalId = action.payload;
    },
    setSampleDimId: (state, action: PayloadAction<string | undefined>) => {
      state.sampleDimId = action.payload;
    },
    setExperimentDimId: (state, action: PayloadAction<string | undefined>) => {
      state.experimentDimId = action.payload;
    },
    setEvalIds: (state, action: PayloadAction<string[]>) => {
      state.evalIds = action.payload;
    },
    setFrameGrids: (state, action: PayloadAction<FrameGrid[]>) => {
      state.frameGrids = action.payload;
    },
    setIsLoadingFrameGrids: (state, action: PayloadAction<boolean>) => {
      state.isLoadingFrameGrids = action.payload;
    },
    resetFrameSlice: () => initialState,
  },
});

export const {
  setMarginals,
  setDimensions,
  setBaseFilter,
  setTranscriptMetadataFields,
  updateTranscriptMetadata,
  setFrameGridId,
  setEvalId,
  setSampleDimId,
  setExperimentDimId,
  setEvalIds,
  setFrameGrids,
  setIsLoadingFrameGrids,
  resetFrameSlice,
} = frameSlice.actions;

export default frameSlice.reducer;
