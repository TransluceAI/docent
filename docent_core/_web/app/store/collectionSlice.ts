import {
  createSlice,
  type PayloadAction,
  createAsyncThunk,
} from '@reduxjs/toolkit';
import { v4 as uuid4 } from 'uuid';

import { apiRestClient } from '../services/apiService';
import {
  ComplexFilter,
  CollectionFilter,
  Collection,
  Bins,
  PrimitiveFilter,
} from '../types/collectionTypes';
import { BaseAgentRunMetadata } from '../types/transcriptTypes';
import { collectionApi } from '../api/collectionApi';

import { setToastNotification } from './toastSlice';
import { Job } from './searchSlice';

export interface CollectionState {
  agentRunIds?: string[];
  // Jank state necessary to auto-scroll correctly:
  //   If there is an initial search query, then we wait until the search has loaded
  //   before we scroll to the specified transcript block
  hasInitSearchQuery?: boolean;
  // Available collections
  collections?: Collection[];
  // Collection state
  filtersMap?: Record<string, CollectionFilter>;
  baseFilter?: ComplexFilter;
  // Metadata
  agentRunMetadata?: Record<string, Record<string, BaseAgentRunMetadata>>;
  // Global variables
  collectionId?: string;
  viewId?: string;
  bins?: Bins;
}

const initialState: CollectionState = {};

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
      dispatch(setViewId(view_id));

      // dispatch(getAgentRunMetadataFields());
      // Start a broker socket to listen for state updates with dual-channel support
      // await socketService.initSocket(collection_id, view_id);
    } catch (error) {
      // Cleanup on error
      // socketService.closeSocket();
      dispatch(setCollectionId(undefined));
      dispatch(setViewId(undefined));
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

export const deleteSearch = createAsyncThunk(
  'collection/deleteSearch',
  async (
    { searchQueryId, job }: { searchQueryId: string; job: Job },
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
      if (job.status === 'running') {
        await apiRestClient.post(`/${job.id}/cancel_compute_search`);
      }
      console.log('deleting search', searchQueryId, job);
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

export const postFilter = createAsyncThunk(
  'collection/postFilter',
  async (filter: ComplexFilter | null, { dispatch, getState }) => {
    const state = getState() as { collection: CollectionState };
    const collectionId = state.collection.collectionId;

    if (!collectionId) return;

    dispatch(
      collectionApi.endpoints.postBaseFilter.initiate({
        collection_id: collectionId,
        filter: filter,
      })
    );
  }
);

export const clearFilters = createAsyncThunk(
  'collection/clearFilters',
  async (_, { dispatch, getState }) => {
    const state = getState() as { collection: CollectionState };
    dispatch(postFilter(null));
  }
);

export const addFilters = createAsyncThunk(
  'collection/addFilters',
  async (filters: CollectionFilter[], { dispatch, getState }) => {
    const state = getState() as { collection: CollectionState };
    const baseFilter = state.collection.baseFilter;

    // Create new base filter with all filters added
    const newBaseFilter: ComplexFilter = baseFilter
      ? {
          ...baseFilter,
          filters: [...baseFilter.filters, ...filters],
        }
      : {
          filters: [...filters],
          type: 'complex',
          op: 'and',
          id: uuid4(),
          name: null,
          supports_sql: true,
        };

    // Remove duplicate primitive filters
    const seenFilterKeys = new Set<string>();
    newBaseFilter.filters = newBaseFilter.filters.reduceRight((acc, filter) => {
      if (filter.type === 'primitive') {
        const primitiveFilter = filter as PrimitiveFilter;
        const keyPath = primitiveFilter.key_path?.join('.') || '';
        const value = primitiveFilter.value;
        const op = primitiveFilter.op;
        const filterKey = `${keyPath}:${value}:${op}`;

        if (seenFilterKeys.has(filterKey)) {
          return acc;
        }
        seenFilterKeys.add(filterKey);
      }
      return [filter, ...acc];
    }, [] as CollectionFilter[]);

    dispatch(postFilter(newBaseFilter));
  }
);

export const removeFilter = createAsyncThunk(
  'collection/removeFilter',
  async (filterId: string, { dispatch, getState }) => {
    const state = getState() as { collection: CollectionState };
    const baseFilter = state.collection.baseFilter;

    if (!baseFilter) return;

    // Clone the current filter
    let newBaseFilter: ComplexFilter | null = {
      ...baseFilter,
      filters: [...baseFilter.filters],
    };

    // Remove the internal filter from the base filter
    const newSubFilters = newBaseFilter.filters.filter(
      (f) => f.id !== filterId
    );

    // If there are still subfilters, update the base filter
    // Otherwise, remove the base filter completely
    if (newSubFilters && newSubFilters.length > 0) {
      newBaseFilter.filters = newSubFilters;
    } else {
      newBaseFilter = null;
    }

    dispatch(postFilter(newBaseFilter));
  }
);

export const collectionSlice = createSlice({
  name: 'collection',
  initialState,
  reducers: {
    setBins: (state, action: PayloadAction<Bins>) => {
      state.bins = action.payload;
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
    setViewId: (state, action: PayloadAction<string | undefined>) => {
      state.viewId = action.payload;
    },
    setHasInitSearchQuery: (state, action: PayloadAction<boolean>) => {
      state.hasInitSearchQuery = action.payload;
    },
    resetCollectionSlice: (state) => {
      const collectionsToKeep = state.collections;
      return {
        ...initialState,
        collections: collectionsToKeep,
      };
    },
  },
  extraReducers: (builder) => {
    builder.addMatcher(
      collectionApi.endpoints.getCollections.matchFulfilled,
      (state, action) => {
        state.collections = action.payload;
      }
    );
    builder.addMatcher(
      collectionApi.endpoints.getBaseFilter.matchFulfilled,
      (state, action) => {
        state.baseFilter = action.payload ?? undefined;
      }
    );
    builder.addMatcher(
      collectionApi.endpoints.postBaseFilter.matchFulfilled,
      (state, action) => {
        state.baseFilter = action.payload ?? undefined;
      }
    );
    builder.addMatcher(
      collectionApi.endpoints.getAgentRunIds.matchFulfilled,
      (state, action) => {
        state.agentRunIds = action.payload;
      }
    );
  },
});

export const {
  setBins,
  updateAgentRunMetadata,
  setCollectionId,
  setViewId,
  setHasInitSearchQuery,
  resetCollectionSlice,
} = collectionSlice.actions;

export default collectionSlice.reducer;
