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
  //   If there is an initial search query, then we wait until the search has loaded
  //   before we scroll to the specified transcript block
  hasInitSearchQuery?: boolean;
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
  async (frameGridId: string, { dispatch }) => {
    try {
      const response = await apiRestClient.post(`/${frameGridId}/join`);
      const { fg_id, view_id } = response.data;

      if (fg_id !== frameGridId) {
        throw new Error('Frame grid ID mismatch');
      }

      // Set various IDs
      dispatch(setFrameGridId(frameGridId));
      dispatch(setFrameGridId(frameGridId));

      dispatch(getAgentRunMetadataFields());
      // Start a broker socket to listen for state updates with dual-channel support
      await socketService.initSocket(fg_id, view_id);
      // Only request state after connection is established
      dispatch(getState());
    } catch (error) {
      // Cleanup on error
      socketService.closeSocket();
      dispatch(setFrameGridId(undefined));
      dispatch(setFrameGridId(undefined));
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
      await apiRestClient.get(`/${frameGridId}/state`);
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
        `/${frameGridId}/agent_run_metadata_fields`
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
      const response = await apiRestClient.post(
        `/${frameGridId}/agent_run_metadata`,
        {
          agent_run_ids: agentRunIds,
        }
      );
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
      const response = await apiRestClient.post(
        `/${frameGridId}/get_dimensions`,
        {
          dim_ids: dimIds,
        }
      );
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

export const addSearchDimension = createAsyncThunk(
  'frame/addSearchDimension',
  async (searchQuery: string, { dispatch, getState }) => {
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
      const response = await apiRestClient.post(`/${frameGridId}/dimension`, {
        dim: {
          name: searchQuery,
          search_query: searchQuery,
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
        `/${frameGridId}/dimension?dim_id=${dimensionId}`
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
        `/${frameGridId}/filter?filter_id=${filterId}`
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

export const deleteSearch = createAsyncThunk(
  'frame/deleteSearch',
  async (searchQueryId: string, { dispatch, getState }) => {
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
        `/${frameGridId}/search?search_query_id=${searchQueryId}`
      );
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error deleting search',
          description: 'Failed to delete search query',
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
      await apiRestClient.put(`/${fg_id}/framegrid`, {
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
      await apiRestClient.delete(`/${fg_id}/framegrid`);
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
      await apiRestClient.post(`/${frameGridId}/filter`, {
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
    setHasInitSearchQuery: (state, action: PayloadAction<boolean>) => {
      state.hasInitSearchQuery = action.payload;
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
  setInnerDimId,
  setOuterDimId,
  setFrameGrids,
  setIsLoadingFrameGrids,
  setHasInitSearchQuery,
  resetFrameSlice,
} = frameSlice.actions;

export default frameSlice.reducer;
