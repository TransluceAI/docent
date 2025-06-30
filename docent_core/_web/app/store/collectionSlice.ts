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
  CollectionDimension,
  CollectionFilter,
  Collection,
  Bins,
} from '../types/collectionTypes';
import { BaseAgentRunMetadata } from '../types/transcriptTypes';

import { setToastNotification } from './toastSlice';
import { Job } from './searchSlice';

export interface CollectionState {
  // Jank state necessary to auto-scroll correctly:
  //   If there is an initial search query, then we wait until the search has loaded
  //   before we scroll to the specified transcript block
  hasInitSearchQuery?: boolean;
  // Available collections
  collections?: Collection[];
  isLoadingCollections: boolean;
  // Collection state
  dimensionsMap?: Record<string, CollectionDimension>;
  filtersMap?: Record<string, CollectionFilter>;
  baseFilter?: ComplexFilter;
  // Metadata
  agentRunMetadataFields?: AgentRunMetadataField[];
  agentRunMetadata?: Record<string, Record<string, BaseAgentRunMetadata>>;
  // Global variables
  collectionId?: string;
  innerBinKey?: string;
  outerBinKey?: string;
  bins?: Bins;
}

const initialState: CollectionState = {
  isLoadingCollections: false,
};

export const fetchCollections = createAsyncThunk(
  'collection/fetchCollections',
  async (_, { dispatch }) => {
    dispatch(setIsLoadingCollections(true));
    try {
      const response = await apiRestClient.get('/collections');
      dispatch(setCollections(response.data));
      return response.data;
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error fetching collections',
          description: 'Please try again in a moment',
          variant: 'destructive',
        })
      );
      throw error;
    } finally {
      dispatch(setIsLoadingCollections(false));
    }
  }
);

export const initSession = createAsyncThunk(
  'collection/initSession',
  async (collectionId: string, { dispatch }) => {
    try {
      const response = await apiRestClient.post(`/${collectionId}/join`);
      const { collection_id, view_id } = response.data;

      if (collection_id !== collectionId) {
        throw new Error('Collection ID mismatch');
      }

      // Set various IDs
      dispatch(setCollectionId(collectionId));
      dispatch(setCollectionId(collectionId));

      dispatch(getAgentRunMetadataFields());
      // Start a broker socket to listen for state updates with dual-channel support
      await socketService.initSocket(collection_id, view_id);
      // Only request state after connection is established
      dispatch(getState());
    } catch (error) {
      // Cleanup on error
      socketService.closeSocket();
      dispatch(setCollectionId(undefined));
      dispatch(setCollectionId(undefined));
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
  'collection/getState',
  async (_, { dispatch, getState }) => {
    const state = getState() as { collection: CollectionState };
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
      await apiRestClient.get(`/${collectionId}/state`);
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
  'collection/getAgentRunMetadataFields',
  async (_, { dispatch, getState }) => {
    const state = getState() as { collection: CollectionState };
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
      const response = await apiRestClient.get(
        `/${collectionId}/agent_run_metadata_fields`
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
  'collection/getAgentRunMetadata',
  async (agentRunIds: string[], { dispatch, getState }) => {
    const state = getState() as { collection: CollectionState };
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
      const response = await apiRestClient.post(
        `/${collectionId}/agent_run_metadata`,
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
  'collection/getDimensions',
  async (dimIds: string[] | undefined, { dispatch, getState }) => {
    const state = getState() as { collection: CollectionState };
    const collectionId = state.collection.collectionId;
    const curDimensions = Object.values(state.collection.dimensionsMap ?? {});

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
      const response = await apiRestClient.post(
        `/${collectionId}/get_dimensions`,
        {
          dim_ids: dimIds,
        }
      );
      dispatch(setDimensions([...curDimensions, ...response.data]));
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

export const deleteSearch = createAsyncThunk(
  'collection/deleteSearch',
  async ({ searchQueryId, job }: { searchQueryId: string; job: Job }, { dispatch, getState }) => {
    const state = getState() as { collection: CollectionState };
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
      if (job.status === "running") {
        await apiRestClient.post(`/${job.id}/cancel_compute_search`);
      }
      console.log("deleting search", searchQueryId, job);
      await apiRestClient.delete(
        `/${collectionId}/search?search_query_id=${searchQueryId}`
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

export const updateCollection = createAsyncThunk(
  'collection/updateCollection',
  async (
    {
      collection_id,
      name,
      description,
    }: { collection_id: string; name?: string; description?: string },
    { dispatch }
  ) => {
    try {
      await apiRestClient.put(`/${collection_id}/collection`, {
        name,
        description,
      });
      return { collection_id };
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error updating collection',
          description: 'Failed to update collection',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const deleteCollection = createAsyncThunk(
  'collection/deleteCollection',
  async (collection_id: string, { dispatch }) => {
    try {
      await apiRestClient.delete(`/${collection_id}/collection`);
      dispatch(
        setToastNotification({
          title: 'Collection deleted',
          description: 'The collection has been successfully deleted',
        })
      );
      return { collection_id };
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error deleting collection',
          description: 'Failed to delete collection',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const editFilter = createAsyncThunk(
  'collection/editFilter',
  async (
    { filterId, newPredicate }: { filterId: string; newPredicate: string },
    { dispatch, getState }
  ) => {
    const state = getState() as { collection: CollectionState };
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
      await apiRestClient.post(`/${collectionId}/filter`, {
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

export const collectionSlice = createSlice({
  name: 'collection',
  initialState,
  reducers: {
    setBins: (state, action: PayloadAction<Bins>) => {
      state.bins = action.payload;
    },
    setDimensions: (state, action: PayloadAction<CollectionDimension[]>) => {
      state.dimensionsMap = action.payload.reduce(
        (map, dimension) => {
          map[dimension.id] = dimension;
          return map;
        },
        {} as Record<string, CollectionDimension>
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
    setCollectionId: (state, action: PayloadAction<string | undefined>) => {
      state.collectionId = action.payload;
    },
    setInnerBinKey: (state, action: PayloadAction<string | undefined>) => {
      state.innerBinKey = action.payload;
    },
    setOuterBinKey: (state, action: PayloadAction<string | undefined>) => {
      state.outerBinKey = action.payload;
    },
    setCollections: (state, action: PayloadAction<Collection[]>) => {
      state.collections = action.payload;
    },
    setIsLoadingCollections: (state, action: PayloadAction<boolean>) => {
      state.isLoadingCollections = action.payload;
    },
    setHasInitSearchQuery: (state, action: PayloadAction<boolean>) => {
      state.hasInitSearchQuery = action.payload;
    },
    resetCollectionSlice: () => initialState,
  },
});

export const {
  setBins,
  setDimensions,
  setBaseFilter,
  setAgentRunMetadataFields,
  updateAgentRunMetadata,
  setCollectionId,
  setInnerBinKey,
  setOuterBinKey,
  setCollections,
  setIsLoadingCollections,
  setHasInitSearchQuery,
  resetCollectionSlice,
} = collectionSlice.actions;

export default collectionSlice.reducer;
