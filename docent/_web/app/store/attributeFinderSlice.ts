import {
  createSlice,
  type PayloadAction,
  createAsyncThunk,
} from '@reduxjs/toolkit';
import { v4 as uuid4 } from 'uuid';

import { apiRestClient } from '../services/apiService';
import sseService from '../services/sseService';
import {
  AttributeFeedback,
  StreamedAttribute,
} from '../types/experimentViewerTypes';
import {
  AttributeWithCitations,
  ComplexFilter,
  FrameFilter,
} from '../types/frameTypes';

import { clearRegexSnippets } from './experimentViewerSlice';
import { addAttributeDimension, getDimensions } from './frameSlice';
import { RootState } from './store';
import { setToastNotification } from './toastSlice';

// Map to store cancel functions for active SSE connections
const cancelFunctionsMap: Record<string, () => void> = {};

export interface AttributeFinderState {
  attributeQueryTextboxValue?: string;
  searchHistory?: string[];
  attributeMap?: Record<string, Record<string, AttributeWithCitations[]>>;
  // Current attribute query
  attributeQueryDimId?: string;
  // Clustering
  activeClusterTaskId?: string;
  // Parts of the lifecycle of a query
  loadingProgress?: [number, number]; // [num_done, num_total]
  loadingAttributesForId?: string;
  activeAttributeTaskId?: string;
  // Feedback
  voteState?: Record<string, Record<string, 'up' | 'down'>>; // agent_run_id -> attribute -> vote
  // Attribute searches with completion status
  attributeSearches?: Array<{
    dim_id: string;
    attribute: string;
    num_judgments_computed: number;
    num_total: number;
  }>;
}

const initialState: AttributeFinderState = {};

export const requestRegexSnippetsIfExist = createAsyncThunk(
  'experimentViewer/requestRegexSnippetsIfExist',
  async (
    { filterId, agentRunIds }: { filterId: string; agentRunIds: string[] },
    { dispatch, getState }
  ) => {
    try {
      const state = getState() as { frame: { frameGridId?: string } };
      const frameGridId = state.frame.frameGridId;

      if (!frameGridId) {
        throw new Error('No frame grid ID available');
      }

      const response = await apiRestClient.post('/get_regex_snippets', {
        fg_id: frameGridId,
        filter_id: filterId,
        agent_run_ids: agentRunIds,
      });

      return response.data;
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error requesting regex snippets',
          description: 'Failed to get regex snippets',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const requestAttributes = createAsyncThunk(
  'experimentViewer/requestAttributes',
  async (
    {
      attribute,
      existingDimId,
    }: { attribute?: string; existingDimId?: string },
    { dispatch, getState }
  ) => {
    try {
      const state = getState() as RootState;

      // Cancel any existing attribute task
      await dispatch(cancelCurrentAttributeRequest());

      // Set the UI loading state that doesn't depend on `attribute`
      dispatch(setLoadingProgress([0, 0]));

      let dimId: string;
      if (existingDimId) {
        dimId = existingDimId;
        // We also need to explicitly get the corresponding dimension to extract the relevant attribute
        await dispatch(getDimensions());
        // Parse the attribute out
        const dimensionsMap = state.frame.dimensionsMap;
        if (!dimensionsMap) {
          throw new Error('No dimensions map available');
        }
        const dim = dimensionsMap[dimId];
        if (!dim) {
          throw new Error('Could not find search with the provided ID');
        }
        if (!dim.attribute) {
          throw new Error('No attribute found for existing dimension');
        }
        attribute = dim.attribute;
      } else {
        if (!attribute) {
          throw new Error(
            'No attribute, nor existing dimension ID provided. This should never happen!'
          );
        }

        // If there isn't an existing dimension, add one corresponding to the attribute
        // This method auto-triggers the push of a new filter
        dimId = await dispatch(addAttributeDimension(attribute)).unwrap();
      }

      // Set the UI loading state that depends on `attribute`
      dispatch(setLoadingAttributesForId(attribute));
      dispatch(setAttributeQueryDimId(dimId));

      // Send the request via REST API
      const frameGridId = state.frame.frameGridId;
      if (!frameGridId) {
        throw new Error('No frame grid ID available');
      }

      // Start the compute attributes job
      const response = await apiRestClient.post('/start_compute_attributes', {
        fg_id: frameGridId,
        attribute,
      });

      const jobId = response.data;

      // Set the job ID as the active attribute task ID
      dispatch(setActiveAttributeTaskId(jobId));

      // Set up event source to listen for streaming updates using sseService
      const { eventSource, onCancel } = sseService.createEventSource(
        `/rest/listen_compute_attributes?job_id=${jobId}`,
        (data: StreamedAttribute) => {
          dispatch(handleAttributesUpdate(data));
        },
        () => {
          dispatch(setLoadingAttributesForId(undefined));
          dispatch(setActiveAttributeTaskId(undefined));
        },
        (title, description, variant) => {
          dispatch(
            setToastNotification({
              title,
              description,
              variant,
            })
          );
        }
      );
      // Store the cancel function for potential cleanup
      cancelFunctionsMap[jobId] = onCancel;
    } catch (error) {
      // Cleanup on error
      dispatch(setLoadingAttributesForId(undefined));
      dispatch(setActiveAttributeTaskId(undefined));
      dispatch(
        setToastNotification({
          title: 'Error performing search',
          description:
            error instanceof Error
              ? error.message
              : 'Failed with unknown error',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const requestClusters = createAsyncThunk(
  'experimentViewer/requestClusters',
  async (
    payload: { dimensionId: string; feedback?: string },
    { dispatch, getState }
  ) => {
    // Get the frame grid ID from the state
    const state = getState() as { frame: { frameGridId?: string } };
    const frameGridId = state.frame.frameGridId;

    try {
      if (!frameGridId) {
        throw new Error('No frame grid ID available');
      }

      // Cancel any previous cluster requests
      await dispatch(cancelCurrentClusterRequest());

      // Start the cluster dimension job
      const response = await apiRestClient.post('/start_cluster_dimension', {
        fg_id: frameGridId,
        dim_id: payload.dimensionId,
        feedback: payload.feedback,
      });

      const jobId = response.data;
      dispatch(setActiveClusterTaskId(jobId));

      // Set up event source to listen for streaming updates using sseService
      const { eventSource, onCancel } = sseService.createEventSource(
        `/rest/listen_cluster_dimension?job_id=${jobId}`,
        (data) => {
          // Handle any cluster updates if needed
          // Currently the backend doesn't send progress updates for clustering
        },
        () => {
          dispatch(setActiveClusterTaskId(undefined));
        },
        (title, description, variant) => {
          dispatch(
            setToastNotification({
              title,
              description,
              variant,
            })
          );
        }
      );

      // Store the cancel function for potential cleanup
      cancelFunctionsMap[jobId] = onCancel;
    } catch (error) {
      // Cleanup on error
      dispatch(setActiveClusterTaskId(undefined));
      dispatch(
        setToastNotification({
          title: 'Error requesting clusters',
          description: 'Failed to cluster dimension',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const clearAttributeQuery = createAsyncThunk(
  'experimentViewer/clearAttributeQuery',
  async (_, { dispatch, getState }) => {
    dispatch(setAttributeQueryDimId(undefined));
    dispatch(cancelCurrentAttributeRequest());
    dispatch(clearAttributeMap());
  }
);

export const cancelCurrentAttributeRequest = createAsyncThunk(
  'experimentViewer/cancelCurrentAttributeRequest',
  async (_, { getState, dispatch }) => {
    const state = getState() as { attributeFinder: AttributeFinderState };
    const { activeAttributeTaskId } = state.attributeFinder;

    // Also cancel any active cluster task when cancelling attribute requests
    await dispatch(cancelCurrentClusterRequest());

    if (activeAttributeTaskId) {
      // If there's an active cancel function, call it
      if (cancelFunctionsMap[activeAttributeTaskId]) {
        try {
          cancelFunctionsMap[activeAttributeTaskId]();
          delete cancelFunctionsMap[activeAttributeTaskId];
        } catch (error) {
          dispatch(
            setToastNotification({
              title: 'Error cancelling request',
              description: 'Failed with unknown error',
              variant: 'destructive',
            })
          );
          throw error;
        }
      } else {
        dispatch(
          setToastNotification({
            title: 'Error cancelling request',
            description: 'No active cancel function found for task',
            variant: 'destructive',
          })
        );
      }

      // Reset the state
      dispatch(setLoadingAttributesForId(undefined));
      dispatch(setActiveAttributeTaskId(undefined));
      dispatch(setLoadingProgress(undefined));
    }
  }
);

export const updateBaseFilter = createAsyncThunk(
  'experimentViewer/updateBaseFilter',
  async (filter: ComplexFilter | undefined, { dispatch, getState }) => {
    const state = getState() as { frame: { frameGridId?: string } };
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
      await apiRestClient.post('/base_filter', {
        fg_id: frameGridId,
        filter: filter ?? null,
      });

      // Also clear attribute query and regex snippets
      dispatch(clearAttributeQuery());
      dispatch(clearRegexSnippets());
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error updating base filter',
          description: 'Failed to update base filter',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const addBaseFilter = createAsyncThunk(
  'experimentViewer/addBaseFilter',
  async (filter: FrameFilter, { dispatch, getState }) => {
    const state = getState() as RootState;

    // Clone the current filter
    const newBaseFilter: ComplexFilter = state.frame.baseFilter
      ? {
          ...state.frame.baseFilter,
          filters: [...state.frame.baseFilter.filters],
        }
      : { filters: [], type: 'complex', op: 'and', id: uuid4(), name: null };
    newBaseFilter.filters.push(filter);

    dispatch(updateBaseFilter(newBaseFilter));
  }
);

export const removeBaseFilter = createAsyncThunk(
  'experimentViewer/removeBaseFilter',
  async (filterId: string, { dispatch, getState }) => {
    const state = getState() as RootState;

    if (!state.frame.baseFilter) {
      return;
    }

    // Clone the current filter
    let newBaseFilter: ComplexFilter | undefined = {
      ...state.frame.baseFilter,
      filters: [...state.frame.baseFilter.filters],
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
      newBaseFilter = undefined;
    }

    dispatch(updateBaseFilter(newBaseFilter));
  }
);

export const clearBaseFilters = createAsyncThunk(
  'experimentViewer/clearBaseFilters',
  async (_, { dispatch }) => {
    dispatch(updateBaseFilter(undefined));
    dispatch(clearAttributeQuery());
  }
);

export const cancelCurrentClusterRequest = createAsyncThunk(
  'experimentViewer/cancelCurrentClusterRequest',
  async (_, { getState, dispatch }) => {
    const state = getState() as { attributeFinder: AttributeFinderState };
    const { activeClusterTaskId } = state.attributeFinder;

    if (activeClusterTaskId) {
      // If there's an active cancel function, call it
      if (cancelFunctionsMap[activeClusterTaskId]) {
        try {
          cancelFunctionsMap[activeClusterTaskId]();
          delete cancelFunctionsMap[activeClusterTaskId];
        } catch (error) {
          dispatch(
            setToastNotification({
              title: 'Error cancelling cluster request',
              description: 'Failed to cancel the clustering task',
              variant: 'destructive',
            })
          );
          throw error;
        }
      } else {
        dispatch(
          setToastNotification({
            title: 'Error cancelling cluster request',
            description: 'No active cancel function found for task',
            variant: 'destructive',
          })
        );
      }

      // Reset the state
      dispatch(setActiveClusterTaskId(undefined));
    }
  }
);

export const submitAttributeFeedback = createAsyncThunk(
  'experimentViewer/submitAttributeFeedback',
  async (
    {
      originalQuery,
      feedback,
      missingQueries,
    }: {
      originalQuery: string;
      feedback: AttributeFeedback[];
      missingQueries: string;
    },
    { dispatch }
  ) => {
    try {
      const response = await apiRestClient.post('/submit_attribute_feedback', {
        original_query: originalQuery,
        attribute_feedback: feedback,
        missing_queries: missingQueries,
      });
      return response.data.rewritten_query;
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error submitting attribute feedback',
          description: 'Failed to submit attribute feedback',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const attributeFinderSlice = createSlice({
  name: 'attributeFinder',
  initialState,
  reducers: {
    setActiveClusterTaskId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.activeClusterTaskId = action.payload;
    },
    handleAttributesUpdate: (
      state,
      action: PayloadAction<StreamedAttribute>
    ) => {
      const { data_dict, num_agent_runs_done, num_agent_runs_total } =
        action.payload;

      // Update the progress counters
      state.loadingProgress = [num_agent_runs_done, num_agent_runs_total];

      // Update the attribute map
      if (!state.attributeMap) {
        state.attributeMap = {};
      }
      for (const agent_run_id in data_dict) {
        for (const attribute in data_dict[agent_run_id]) {
          if (!state.attributeMap[agent_run_id]) {
            state.attributeMap[agent_run_id] = {};
          }

          // Replace the old values at (agent_run_id, attribute)
          state.attributeMap[agent_run_id][attribute] =
            data_dict[agent_run_id][attribute];
        }
      }
    },
    setLoadingAttributesForId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.loadingAttributesForId = action.payload;
    },
    // New actions for attribute requests
    setActiveAttributeTaskId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.activeAttributeTaskId = action.payload;
    },
    clearAttributeMap: (state) => {
      state.attributeMap = undefined;
    },
    voteOnAttribute: (
      state,
      action: PayloadAction<{
        agent_run_id: string;
        attribute: string;
        vote: 'up' | 'down';
      }>
    ) => {
      const { agent_run_id, attribute, vote } = action.payload;
      if (!state.voteState) {
        state.voteState = {};
      }

      // Initialize nested objects if they don't exist
      state.voteState[agent_run_id] = state.voteState[agent_run_id] || {};

      // Toggle behavior: remove vote if it's the same as current vote
      if (state.voteState[agent_run_id][attribute] === vote) {
        delete state.voteState[agent_run_id][attribute];
        // Clean up empty objects
        if (Object.keys(state.voteState[agent_run_id]).length === 0) {
          delete state.voteState[agent_run_id];
        }
      } else {
        // Set the new vote
        state.voteState[agent_run_id][attribute] = vote;
      }
    },
    clearVoteState: (state) => {
      state.voteState = undefined;
    },
    setAttributeQueryTextboxValue: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.attributeQueryTextboxValue = action.payload;
    },
    setAttributeQueryDimId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.attributeQueryDimId = action.payload;
    },
    setLoadingProgress: (
      state,
      action: PayloadAction<[number, number] | undefined>
    ) => {
      state.loadingProgress = action.payload;
    },
    setAttributeSearches: (
      state,
      action: PayloadAction<
        Array<{
          dim_id: string;
          attribute: string;
          num_judgments_computed: number;
          num_total: number;
        }>
      >
    ) => {
      state.attributeSearches = action.payload;
    },
    resetAttributeFinderSlice: () => initialState,
  },
});

export const {
  setActiveClusterTaskId,
  handleAttributesUpdate,
  setLoadingAttributesForId,
  setActiveAttributeTaskId,
  clearAttributeMap,
  voteOnAttribute,
  clearVoteState,
  setAttributeQueryTextboxValue,
  setAttributeQueryDimId,
  setLoadingProgress,
  setAttributeSearches,
  resetAttributeFinderSlice,
} = attributeFinderSlice.actions;

export default attributeFinderSlice.reducer;
