import {
  AttributeFeedback,
  StreamedSearchResult,
} from '../types/experimentViewerTypes';
import {
  createSlice,
  type PayloadAction,
  createAsyncThunk,
} from '@reduxjs/toolkit';
import { v4 as uuid4 } from 'uuid';

import { apiRestClient } from '../services/apiService';
import sseService from '../services/sseService';
import {
  SearchResultWithCitations,
  ComplexFilter,
  FrameFilter,
} from '../types/frameTypes';

import { clearRegexSnippets } from './experimentViewerSlice';
import { RootState } from './store';
import { setToastNotification } from './toastSlice';

// Map to store cancel functions for active SSE connections
export const cancelFunctionsMap: Record<string, () => void> = {};

export interface SearchState {
  searchQueryTextboxValue?: string;
  searchHistory?: string[];
  searchResultMap?: Record<string, Record<string, SearchResultWithCitations[]>>;
  // Current search query
  curSearchQuery?: string;
  // Clustering
  activeClusterTaskId?: string;
  // Parts of the lifecycle of a query
  loadingProgress?: [number, number]; // [num_done, num_total]
  loadingSearchQuery?: string;
  activeSearchTaskId?: string;
  // // Feedback
  // voteState?: Record<string, Record<string, 'up' | 'down'>>; // agent_run_id -> attribute -> vote
  // Searches with completion status
  searchesWithStats?: Array<{
    search_id: string;
    search_query: string;
    num_judgments_computed: number;
    num_total: number;
  }>;
}

const initialState: SearchState = {};

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

      const response = await apiRestClient.post(
        `/${frameGridId}/get_regex_snippets`,
        {
          filter_id: filterId,
          agent_run_ids: agentRunIds,
        }
      );

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

export const computeSearch = createAsyncThunk(
  'experimentViewer/computeSearch',
  async ({ searchQuery }: { searchQuery: string }, { dispatch, getState }) => {
    try {
      const state = getState() as RootState;

      // Cancel any existing task
      await dispatch(cancelCurrentSearch());

      // Set the UI loading state
      dispatch(setLoadingProgress([0, 0]));
      dispatch(setLoadingSearchQuery(searchQuery));
      dispatch(setSearchQuery(searchQuery));

      // Send the request via REST API
      const frameGridId = state.frame.frameGridId;
      if (!frameGridId) {
        throw new Error('No frame grid ID available');
      }

      // Start the compute search job
      console.log('Starting compute search', searchQuery);
      const response = await apiRestClient.post(
        `/${frameGridId}/start_compute_search`,
        {
          search_query: searchQuery,
        }
      );

      const jobId = response.data;

      // Set the job ID as the active task ID
      dispatch(setActiveSearchTaskId(jobId));

      // Set up event source to listen for streaming updates using sseService
      const { onCancel } = sseService.createEventSource(
        `/rest/${frameGridId}/listen_compute_search?job_id=${jobId}`,
        (data: StreamedSearchResult) => {
          dispatch(handleSearchUpdate(data));
        },
        () => {
          dispatch(setLoadingSearchQuery(undefined));
          dispatch(setActiveSearchTaskId(undefined));
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
      dispatch(setLoadingSearchQuery(undefined));
      dispatch(setActiveSearchTaskId(undefined));
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
      const response = await apiRestClient.post(
        `/${frameGridId}/start_cluster_dimension`,
        {
          dim_id: payload.dimensionId,
          feedback: payload.feedback,
        }
      );

      const jobId = response.data;
      dispatch(setActiveClusterTaskId(jobId));

      // Set up event source to listen for streaming updates using sseService
      const { onCancel } = sseService.createEventSource(
        `/rest/${frameGridId}/listen_cluster_dimension?job_id=${jobId}`,
        () => {
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

export const clearSearch = createAsyncThunk(
  'experimentViewer/clearSearch',
  async (_, { dispatch }) => {
    dispatch(setSearchQuery(undefined));
    dispatch(cancelCurrentSearch());
    dispatch(clearSearchResultMap());
  }
);

export const cancelCurrentSearch = createAsyncThunk(
  'experimentViewer/cancelCurrentSearch',
  async (_, { getState, dispatch }) => {
    const state = getState() as RootState;
    const { activeSearchTaskId } = state.search;

    // Also cancel any active cluster task when cancelling search requests
    await dispatch(cancelCurrentClusterRequest());

    if (activeSearchTaskId) {
      // If there's an active cancel function, call it
      if (cancelFunctionsMap[activeSearchTaskId]) {
        try {
          cancelFunctionsMap[activeSearchTaskId]();
          delete cancelFunctionsMap[activeSearchTaskId];
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
      dispatch(setLoadingSearchQuery(undefined));
      dispatch(setActiveSearchTaskId(undefined));
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
      await apiRestClient.post(`/${frameGridId}/base_filter`, {
        filter: filter ?? null,
      });

      // Also clear search query and regex snippets
      dispatch(clearSearch());
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
    dispatch(clearSearch());
  }
);

export const cancelCurrentClusterRequest = createAsyncThunk(
  'experimentViewer/cancelCurrentClusterRequest',
  async (_, { getState, dispatch }) => {
    const state = getState() as RootState;
    const { activeClusterTaskId } = state.search;

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

// export const submitAttributeFeedback = createAsyncThunk(
//   'experimentViewer/submitAttributeFeedback',
//   async (
//     {
//       originalQuery,
//       feedback,
//       missingQueries,
//     }: {
//       originalQuery: string;
//       feedback: AttributeFeedback[];
//       missingQueries: string;
//     },
//     { dispatch }
//   ) => {
//     try {
//       const response = await apiRestClient.post('/submit_attribute_feedback', {
//         original_query: originalQuery,
//         attribute_feedback: feedback,
//         missing_queries: missingQueries,
//       });
//       return response.data.rewritten_query;
//     } catch (error) {
//       dispatch(
//         setToastNotification({
//           title: 'Error submitting attribute feedback',
//           description: 'Failed to submit attribute feedback',
//           variant: 'destructive',
//         })
//       );
//       throw error;
//     }
//   }
// );

export const searchSlice = createSlice({
  name: 'search',
  initialState,
  reducers: {
    setActiveClusterTaskId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.activeClusterTaskId = action.payload;
    },
    handleSearchUpdate: (
      state,
      action: PayloadAction<StreamedSearchResult>
    ) => {
      const { data_dict, num_agent_runs_done, num_agent_runs_total } =
        action.payload;

      // Update the progress counters
      state.loadingProgress = [num_agent_runs_done, num_agent_runs_total];

      // Update the search map
      if (!state.searchResultMap) {
        state.searchResultMap = {};
      }
      for (const agent_run_id in data_dict) {
        for (const search_query in data_dict[agent_run_id]) {
          if (!state.searchResultMap[agent_run_id]) {
            state.searchResultMap[agent_run_id] = {};
          }

          // Replace the old values at (agent_run_id, search_query)
          state.searchResultMap[agent_run_id][search_query] =
            data_dict[agent_run_id][search_query];
        }
      }
    },
    setLoadingSearchQuery: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.loadingSearchQuery = action.payload;
    },
    setActiveSearchTaskId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.activeSearchTaskId = action.payload;
    },
    clearSearchResultMap: (state) => {
      state.searchResultMap = undefined;
    },
    // voteOnAttribute: (
    //   state,
    //   action: PayloadAction<{
    //     agent_run_id: string;
    //     attribute: string;
    //     vote: 'up' | 'down';
    //   }>
    // ) => {
    //   const { agent_run_id, attribute, vote } = action.payload;
    //   if (!state.voteState) {
    //     state.voteState = {};
    //   }

    //   // Initialize nested objects if they don't exist
    //   state.voteState[agent_run_id] = state.voteState[agent_run_id] || {};

    //   // Toggle behavior: remove vote if it's the same as current vote
    //   if (state.voteState[agent_run_id][attribute] === vote) {
    //     delete state.voteState[agent_run_id][attribute];
    //     // Clean up empty objects
    //     if (Object.keys(state.voteState[agent_run_id]).length === 0) {
    //       delete state.voteState[agent_run_id];
    //     }
    //   } else {
    //     // Set the new vote
    //     state.voteState[agent_run_id][attribute] = vote;
    //   }
    // },
    // clearVoteState: (state) => {
    //   state.voteState = undefined;
    // },
    setSearchQueryTextboxValue: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.searchQueryTextboxValue = action.payload;
    },
    setSearchQuery: (state, action: PayloadAction<string | undefined>) => {
      state.curSearchQuery = action.payload;
    },
    setLoadingProgress: (
      state,
      action: PayloadAction<[number, number] | undefined>
    ) => {
      state.loadingProgress = action.payload;
    },
    setSearchesWithStats: (
      state,
      action: PayloadAction<
        Array<{
          search_id: string;
          search_query: string;
          num_judgments_computed: number;
          num_total: number;
        }>
      >
    ) => {
      state.searchesWithStats = action.payload;
    },
    resetSearchSlice: () => initialState,
  },
});

export const {
  setActiveClusterTaskId,
  handleSearchUpdate,
  setLoadingSearchQuery,
  setActiveSearchTaskId,
  clearSearchResultMap,
  // voteOnAttribute,
  // clearVoteState,
  setSearchQueryTextboxValue,
  setSearchQuery,
  setLoadingProgress,
  setSearchesWithStats,
  resetSearchSlice,
} = searchSlice.actions;

export default searchSlice.reducer;
