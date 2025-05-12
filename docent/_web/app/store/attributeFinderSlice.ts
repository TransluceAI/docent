import { createSlice, PayloadAction, createAsyncThunk } from '@reduxjs/toolkit';
import {
  AttributeFeedback,
  AttributeWithCitation,
  RegexSnippet,
  StreamedAttribute,
  EvidenceWithCitation,
  StreamedDiffs,
} from '../types/experimentViewerTypes';
import socketService from '../services/socketService';
import sseService from '../services/sseService';
import {
  ComplexFrameFilter,
  FrameDimension,
  FrameFilter,
} from '../types/frameTypes';
import {
  clearRegexSnippets,
  ExperimentViewerState,
} from './experimentViewerSlice';
import { RootState } from './store';
import { addAttributeDimension, deleteDimension } from './frameSlice';
import { apiRestClient } from '../services/apiService';
import { setToastNotification } from './toastSlice';
import { v4 as uuid4 } from 'uuid';

// Map to store cancel functions for active SSE connections
const cancelFunctionsMap: Record<string, () => void> = {};

export interface AttributeFinderState {
  attributeQueryTextboxValue?: string;
  searchHistory?: string[];
  attributeMap?: Record<string, Record<string, AttributeWithCitation[]>>;
  // Current attribute query
  curAttributeQuery?: string;
  attributeQueryDimId?: string;
  // Clustering
  activeClusterTaskId?: string;
  // Parts of the lifecycle of a query
  loadingProgress?: [number, number]; // [num_done, num_total]
  loadingAttributesForId?: string;
  activeAttributeTaskId?: string;
  // Feedback
  voteState?: Record<string, Record<string, 'up' | 'down'>>; // datapoint_id -> attribute -> vote
  // Attribute searches with completion status
  attributeSearches?: Array<{
    dim_id: string;
    attribute: string;
    num_judgments_computed: number;
    num_total: number;
  }>;
  // Diffs
  activeDiffTaskId?: string;
  diffMap?: Record<
    string,
    {
      claim: string[];
      evidence: EvidenceWithCitation[];
      reverse_evidence: EvidenceWithCitation[];
    }
  >;
}

const initialState: AttributeFinderState = {};

export const requestRegexSnippetsIfExist = createAsyncThunk(
  'experimentViewer/requestRegexSnippetsIfExist',
  async (
    { filterId, datapointIds }: { filterId: string; datapointIds: string[] },
    { dispatch, getState }
  ) => {
    try {
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

      const response = await apiRestClient.post('/get_regex_snippets', {
        fg_id: frameGridId,
        filter_id: filterId,
        datapoint_ids: datapointIds,
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
  async (attribute: string, { dispatch, getState }) => {
    try {
      // Cancel any existing attribute task
      dispatch(cancelCurrentAttributeRequest());

      // Set the UI loading state
      dispatch(setCurAttributeQuery(attribute));
      dispatch(setLoadingAttributesForId(attribute));
      dispatch(setLoadingProgress([0, 0]));

      // Add a dimension corresponding to the attribute and store the ID
      const dimId = await dispatch(addAttributeDimension(attribute)).unwrap();
      dispatch(setAttributeQueryDimId(dimId));

      // 5. Send the request via REST API
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
          title: 'Error requesting attributes',
          description: 'Failed to compute attributes for the query',
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

    // Cancel any previous cluster requests
    dispatch(cancelCurrentClusterRequest());

    try {
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
    dispatch(setCurAttributeQuery(undefined));
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
    dispatch(cancelCurrentClusterRequest());

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
              description: 'Failed to cancel the attribute request',
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
    }
  }
);

export const updateBaseFilter = createAsyncThunk(
  'experimentViewer/updateBaseFilter',
  async (filter: ComplexFrameFilter | undefined, { dispatch, getState }) => {
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
    let newBaseFilter: ComplexFrameFilter = state.frame.baseFilter
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
    let newBaseFilter: ComplexFrameFilter | undefined = {
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

export const requestDiffs = createAsyncThunk(
  'experimentViewer/requestDiffs',
  async (
    {
      experimentId1,
      experimentId2,
    }: { experimentId1: string; experimentId2: string },
    { dispatch, getState }
  ) => {
    try {
      // Cancel any existing diff task
      dispatch(cancelCurrentDiffRequest());

      // Set the UI loading state
      dispatch(setLoadingProgress([0, 0]));

      // Get the frame grid ID from the state
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

      // Start the compute diffs job
      const response = await apiRestClient.post('/start_compute_diffs', {
        fg_id: frameGridId,
        experiment_id_1: experimentId1,
        experiment_id_2: experimentId2,
      });

      const jobId = response.data;

      // Set the job ID as the active diff task ID
      dispatch(setActiveDiffTaskId(jobId));

      // Set up event source to listen for streaming updates using sseService
      const { eventSource, onCancel } = sseService.createEventSource(
        `/rest/listen_compute_diffs?job_id=${jobId}`,
        (data: StreamedDiffs) => {
          dispatch(handleDiffsUpdate(data));
        },
        () => {
          dispatch(setActiveDiffTaskId(undefined));
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
      dispatch(setActiveDiffTaskId(undefined));
      dispatch(
        setToastNotification({
          title: 'Error requesting diffs',
          description: 'Failed to compute diffs between experiments',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const cancelCurrentDiffRequest = createAsyncThunk(
  'experimentViewer/cancelCurrentDiffRequest',
  async (_, { getState, dispatch }) => {
    const state = getState() as { attributeFinder: AttributeFinderState };
    const { activeDiffTaskId } = state.attributeFinder;

    if (activeDiffTaskId) {
      // If there's an active cancel function, call it
      if (cancelFunctionsMap[activeDiffTaskId]) {
        try {
          cancelFunctionsMap[activeDiffTaskId]();
          delete cancelFunctionsMap[activeDiffTaskId];
        } catch (error) {
          dispatch(
            setToastNotification({
              title: 'Error cancelling request',
              description: 'Failed to cancel the diff request',
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
      dispatch(setActiveDiffTaskId(undefined));
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
    setCurAttributeQuery: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.curAttributeQuery = action.payload;
    },
    handleAttributesUpdate: (
      state,
      action: PayloadAction<StreamedAttribute>
    ) => {
      const {
        datapoint_id,
        attribute,
        attributes,
        num_datapoints_done,
        num_datapoints_total,
      } = action.payload;

      // Update the progress counters
      state.loadingProgress = [num_datapoints_done, num_datapoints_total];

      if (datapoint_id === null || attribute === null || attributes === null) {
        return;
      }
      if (!state.attributeMap) {
        state.attributeMap = {};
      }

      // Update dict with new attribute
      // We assume that each update contains *all* attributes for that (datapoint_id, attribute) pair
      const attrIds = state.attributeMap[datapoint_id] || {};
      attrIds[attribute] = attributes;
      state.attributeMap[datapoint_id] = attrIds;
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
        datapoint_id: string;
        attribute: string;
        vote: 'up' | 'down';
      }>
    ) => {
      const { datapoint_id, attribute, vote } = action.payload;
      if (!state.voteState) {
        state.voteState = {};
      }

      // Initialize nested objects if they don't exist
      state.voteState[datapoint_id] = state.voteState[datapoint_id] || {};

      // Toggle behavior: remove vote if it's the same as current vote
      if (state.voteState[datapoint_id][attribute] === vote) {
        delete state.voteState[datapoint_id][attribute];
        // Clean up empty objects
        if (Object.keys(state.voteState[datapoint_id]).length === 0) {
          delete state.voteState[datapoint_id];
        }
      } else {
        // Set the new vote
        state.voteState[datapoint_id][attribute] = vote;
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
    setActiveDiffTaskId: (state, action: PayloadAction<string | undefined>) => {
      state.activeDiffTaskId = action.payload;
    },
    handleDiffsUpdate: (state, action: PayloadAction<StreamedDiffs>) => {
      const {
        data_id_1,
        data_id_2,
        claim,
        evidence,
        reverse_evidence,
        num_pairs_done,
        num_pairs_total,
      } = action.payload;

      // Update the progress counters
      state.loadingProgress = [num_pairs_done, num_pairs_total];

      if (
        data_id_1 === null ||
        data_id_2 === null ||
        claim === null ||
        evidence === null ||
        reverse_evidence === null
      ) {
        return;
      }

      if (!state.diffMap) {
        state.diffMap = {};
      }

      // Create a key for the pair of datapoints
      const pairKey = `${data_id_1}|||${data_id_2}`;

      // Update the diff map with the new data
      state.diffMap[pairKey] = {
        claim,
        evidence,
        reverse_evidence,
      };
    },
    clearDiffMap: (state) => {
      state.diffMap = undefined;
    },
    resetAttributeFinderSlice: () => initialState,
  },
});

export const {
  setActiveClusterTaskId,
  setCurAttributeQuery,
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
  setActiveDiffTaskId,
  handleDiffsUpdate,
  clearDiffMap,
  resetAttributeFinderSlice,
} = attributeFinderSlice.actions;

export default attributeFinderSlice.reducer;
