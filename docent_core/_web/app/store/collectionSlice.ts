/**
 * Note(mengk): the patterns in this file are highly deprecated!
 * This is not very "React-ive" - having global state like this and using async thunks is highly discouraged.
 */

import {
  createSlice,
  type PayloadAction,
  createAsyncThunk,
} from '@reduxjs/toolkit';
import { v4 as uuid4 } from 'uuid';

import {
  ComplexFilter,
  CollectionFilter,
  PrimitiveFilter,
} from '../types/collectionTypes';
import { collectionApi } from '../api/collectionApi';

export interface Job {
  id: string;
  type: string;
  created_at: string;
  status: string;
  job_json: { query_id: string };
}

export interface CollectionState {
  // Jank state necessary to auto-scroll correctly:
  //   If there is an initial search query, then we wait until the search has loaded
  //   before we scroll to the specified transcript block
  hasInitSearchQuery?: boolean;
  // Collection state
  baseFilter?: ComplexFilter;
  // Global variables
  collectionId?: string;
  // Collection-specific sorting
  sortField: string | null;
  sortDirection: 'asc' | 'desc';
}

const initialState: CollectionState = {
  sortField: null,
  sortDirection: 'asc',
};

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

function createFilter(filters: CollectionFilter[], baseFilter?: ComplexFilter) {
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

  return newBaseFilter;
}

export const replaceFilters = createAsyncThunk(
  'collection/replaceFilters',
  async (filters: CollectionFilter[], { dispatch, getState }) => {
    const newFilter = createFilter(filters);
    dispatch(postFilter(newFilter));
  }
);

export const collectionSlice = createSlice({
  name: 'collection',
  initialState,
  reducers: {
    setCollectionId: (state, action: PayloadAction<string | undefined>) => {
      state.collectionId = action.payload;
    },
    setHasInitSearchQuery: (state, action: PayloadAction<boolean>) => {
      state.hasInitSearchQuery = action.payload;
    },
    setSortField: (state, action: PayloadAction<string | null>) => {
      state.sortField = action.payload;
    },
    setSortDirection: (state, action: PayloadAction<'asc' | 'desc'>) => {
      state.sortDirection = action.payload;
    },
    setSorting: (
      state,
      action: PayloadAction<{ field: string | null; direction: 'asc' | 'desc' }>
    ) => {
      state.sortField = action.payload.field;
      state.sortDirection = action.payload.direction;
    },
    resetCollectionSlice: (state) => {
      return initialState;
    },
  },
  extraReducers: (builder) => {
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
  },
});

export const {
  setCollectionId,
  setHasInitSearchQuery,
  setSortField,
  setSortDirection,
  setSorting,
  resetCollectionSlice,
} = collectionSlice.actions;

export default collectionSlice.reducer;
