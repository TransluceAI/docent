import {
  createSlice,
  type PayloadAction,
  createAsyncThunk,
} from '@reduxjs/toolkit';

import { apiRestClient } from '../services/apiService';
import socketService from '../services/socketService';
import { TranscriptMetadataField as AgentRunMetadataField } from '../types/experimentViewerTypes';
import {
  ComplexFilter,
  FrameDimension,
  FrameGrid,
  Marginals,
} from '../types/frameTypes';
import { BaseAgentRunMetadata } from '../types/transcriptTypes';

import { setToastNotification } from './toastSlice';

export interface FrameState {
  // Jank state necessary to auto-scroll correctly:
  //   If there is an initial attributeDimId, then we wait until the attributes have loaded
  //   before we scroll to the specified transcript block
  hasInitAttributeDimId?: boolean;
  // Available frame grids
  frameGrids?: FrameGrid[];
  isLoadingFrameGrids: boolean;
  // FrameGrid state
  dimensionsMap?: Record<string, FrameDimension>;
  baseFilter?: ComplexFilter;
  // Metadata
  agentRunMetadataFields?: AgentRunMetadataField[];
  agentRunMetadata?: Record<string, Record<string, BaseAgentRunMetadata>>;
  // Global variables
  frameGridId?: string;
  evalId?: string;
  innerDimId?: string;
  outerDimId?: string;
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

export const initSession = createAsyncThunk(
  'frame/initSession',
  async (evalId: string, { dispatch }) => {
    try {
      const response = await apiRestClient.post('/join', {
        fg_id: evalId,
      });
      const { fg_id } = response.data;

      // Set various IDs
      dispatch(setFrameGridId(fg_id));
      dispatch(setEvalId(evalId));

      dispatch(getAgentRunMetadataFields());
      // Start a broker socket to listen for state updates
      await socketService.initSocket(fg_id);
      // Only request state after connection is established
      dispatch(getState(evalId));
    } catch (error) {
      // Cleanup on error
      socketService.closeSocket();
      dispatch(setFrameGridId(undefined));
      dispatch(setEvalId(undefined));
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

export const getAgentRunMetadataFields = createAsyncThunk(
  'frame/getAgentRunMetadataFields',
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
        `/agent_run_metadata_fields?fg_id=${frameGridId}`
      );
      dispatch(setAgentRunMetadataFields(response.data.fields));
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error fetching metadata fields',
          description: 'Failed to retrieve metadata fields',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const getAgentRunMetadata = createAsyncThunk(
  'frame/getAgentRunMetadata',
  async (agentRunIds: string[], { dispatch, getState }) => {
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
      const response = await apiRestClient.post('/agent_run_metadata', {
        fg_id: frameGridId,
        agent_run_ids: agentRunIds,
      });
      dispatch(updateAgentRunMetadata(response.data));
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error fetching metadata',
          description: 'Failed to retrieve metadata',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const getDimensions = createAsyncThunk(
  'frame/getDimensions',
  async (dimIds: string[] | undefined, { dispatch, getState }) => {
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
      const response = await apiRestClient.post('/get_dimensions', {
        fg_id: frameGridId,
        dim_ids: dimIds,
      });
      dispatch(setDimensions(response.data));
      return response.data;
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error fetching dimensions',
          description: 'Failed to retrieve dimensions',
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

export const updateFrameGrid = createAsyncThunk(
  'frame/updateFrameGrid',
  async (
    {
      fg_id,
      name,
      description,
    }: { fg_id: string; name?: string; description?: string },
    { dispatch }
  ) => {
    try {
      await apiRestClient.put('/framegrid', {
        fg_id,
        name,
        description,
      });
      return { fg_id };
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error updating frame grid',
          description: 'Failed to update frame grid',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const deleteFrameGrid = createAsyncThunk(
  'frame/deleteFrameGrid',
  async (fg_id: string, { dispatch }) => {
    try {
      await apiRestClient.delete(`/framegrid?fg_id=${fg_id}`);
      dispatch(
        setToastNotification({
          title: 'Frame grid deleted',
          description: 'The frame grid has been successfully deleted',
        })
      );
      return { fg_id };
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error deleting frame grid',
          description: 'Failed to delete frame grid',
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
      state.dimensionsMap = action.payload.reduce(
        (map, dimension) => {
          map[dimension.id] = dimension;
          return map;
        },
        {} as Record<string, FrameDimension>
      );
    },
    setBaseFilter: (
      state,
      action: PayloadAction<ComplexFilter | undefined>
    ) => {
      state.baseFilter = action.payload;
    },
    setAgentRunMetadataFields: (
      state,
      action: PayloadAction<AgentRunMetadataField[]>
    ) => {
      state.agentRunMetadataFields = action.payload;
    },
    updateAgentRunMetadata: (
      state,
      action: PayloadAction<
        Record<string, Record<string, BaseAgentRunMetadata>>
      >
    ) => {
      state.agentRunMetadata = {
        ...state.agentRunMetadata,
        ...action.payload,
      };
    },
    setFrameGridId: (state, action: PayloadAction<string | undefined>) => {
      state.frameGridId = action.payload;
    },
    setEvalId: (state, action: PayloadAction<string | undefined>) => {
      state.evalId = action.payload;
    },
    setInnerDimId: (state, action: PayloadAction<string | undefined>) => {
      state.innerDimId = action.payload;
    },
    setOuterDimId: (state, action: PayloadAction<string | undefined>) => {
      state.outerDimId = action.payload;
    },
    setFrameGrids: (state, action: PayloadAction<FrameGrid[]>) => {
      state.frameGrids = action.payload;
    },
    setIsLoadingFrameGrids: (state, action: PayloadAction<boolean>) => {
      state.isLoadingFrameGrids = action.payload;
    },
    setHasInitAttributeDimId: (state, action: PayloadAction<boolean>) => {
      state.hasInitAttributeDimId = action.payload;
    },
    resetFrameSlice: () => initialState,
  },
});

export const {
  setMarginals,
  setDimensions,
  setBaseFilter,
  setAgentRunMetadataFields,
  updateAgentRunMetadata,
  setFrameGridId,
  setEvalId,
  setInnerDimId,
  setOuterDimId,
  setFrameGrids,
  setIsLoadingFrameGrids,
  setHasInitAttributeDimId,
  resetFrameSlice,
} = frameSlice.actions;

export default frameSlice.reducer;
