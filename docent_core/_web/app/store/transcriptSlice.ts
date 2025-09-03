/**
 * Note(mengk): the patterns in this file are highly deprecated!
 * This is not very "React-ive" - having global state like this and using async thunks is highly discouraged.
 */

import {
  createSlice,
  type PayloadAction,
  createAsyncThunk,
} from '@reduxjs/toolkit';

import { apiRestClient } from '../services/apiService';
import sseService from '../services/sseService';
import { v4 as uuidv4 } from 'uuid';
import {
  ActionsSummary,
  AgentRun,
  SolutionSummary,
} from '../types/transcriptTypes';
import { Citation } from '../types/experimentViewerTypes';

import { RootState } from './store';
import { setToastNotification } from './toastSlice';
import { createAppSelector } from './hooks';

// Map to store cancel functions for active SSE connections
const cancelFunctionsMap: Record<string, () => void> = {};

// Utility functions for TA session localStorage keys
export const getTaSessionStorageKey = (agentRunId: string) =>
  `ta-session-${agentRunId}`;

export interface TranscriptState {
  // Cur
  curAgentRun?: AgentRun;
  altAgentRun?: AgentRun;
  // Dashboard agent run view
  dashboardHasRunPreview?: boolean;
  dashboardScrollToBlockIdx?: number;
  dashboardScrollToTranscriptIdx?: number;
  // Actions summary
  actionsSummary?: ActionsSummary;
  loadingActionsSummaryForTranscriptId?: string;
  actionsSummaryTaskId?: string;
  // Solution summary
  solutionSummary?: SolutionSummary;
  loadingSolutionSummaryForTranscriptId?: string;
  solutionSummaryTaskId?: string;
  // Chat assistant
  taAgentRunId?: string;
  taSessionId?: string;
  loadingTaResponse?: boolean;
  // All citations
  allCitations?: Citation[];
  // Citation highlighting
  highlightedCitationId?: string;
  // Agent run sidebar state
  agentRunSidebarTab?: string;
  // Sidebar visibility states for different routes
  leftSidebarOpen?: boolean;
  rightSidebarOpen?: boolean;
}

const initialState: TranscriptState = {
  leftSidebarOpen: undefined, // Hidden by default, shown when clicking agent run card
  rightSidebarOpen: true,
};

export const getActionsSummary = createAsyncThunk(
  'transcript/getActionsSummary',
  async (agentRunId: string, { dispatch, getState }) => {
    const state = getState() as RootState;
    const collectionId = state.collection.collectionId;

    // Cancel existing request
    const { actionsSummaryTaskId } = state.transcript;
    if (actionsSummaryTaskId && cancelFunctionsMap[actionsSummaryTaskId]) {
      cancelFunctionsMap[actionsSummaryTaskId]();
      delete cancelFunctionsMap[actionsSummaryTaskId];
    }

    // Set UI state
    dispatch(setActionsSummary(undefined));
    dispatch(setLoadingActionsSummaryForTranscriptId(agentRunId));

    if (!collectionId) {
      dispatch(
        setToastNotification({
          title: 'Configuration error',
          description: 'No collection ID available',
          variant: 'destructive',
        })
      );
      dispatch(onFinishLoadingActionsSummary());
      throw new Error('No collection ID available');
    }

    try {
      // Generate a task ID for cancellation
      const taskId = uuidv4();
      dispatch(setActionsSummaryTaskId(taskId));

      // Create SSE connection using the service
      const { eventSource, onCancel } = sseService.createEventSource(
        `/rest/${collectionId}/actions_summary?agent_run_id=${agentRunId}`,
        (data) => {
          // Update actions summary with streamed data
          dispatch(
            setActionsSummary({
              agent_run_id: data.agent_run_id,
              low_level: data.low_level,
              high_level: data.high_level,
              observations: data.observations,
            })
          );
        },
        () => {
          dispatch(onFinishLoadingActionsSummary());
        },
        dispatch // Pass dispatch function to handle errors
      );

      // Store the cancel function for potential cleanup
      cancelFunctionsMap[taskId] = onCancel;
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error getting actions summary',
          description: 'Failed to retrieve actions summary',
          variant: 'destructive',
        })
      );
      dispatch(onFinishLoadingActionsSummary());
      throw error;
    }
  }
);

export const getSolutionSummary = createAsyncThunk(
  'transcript/getSolutionSummary',
  async (agentRunId: string, { dispatch, getState }) => {
    const state = getState() as RootState;
    const collectionId = state.collection.collectionId;

    // Cancel existing request
    const { solutionSummaryTaskId } = state.transcript;
    if (solutionSummaryTaskId && cancelFunctionsMap[solutionSummaryTaskId]) {
      cancelFunctionsMap[solutionSummaryTaskId]();
      delete cancelFunctionsMap[solutionSummaryTaskId];
    }

    // Set UI state
    dispatch(setSolutionSummary(undefined));
    dispatch(setLoadingSolutionSummaryForTranscriptId(agentRunId));

    if (!collectionId) {
      dispatch(
        setToastNotification({
          title: 'Configuration error',
          description: 'No collection ID available',
          variant: 'destructive',
        })
      );
      dispatch(onFinishLoadingSolutionSummary());
      throw new Error('No collection ID available');
    }

    try {
      // Generate a task ID for cancellation
      const taskId = uuidv4();
      dispatch(setSolutionSummaryTaskId(taskId));

      // Create SSE connection using the service
      const { eventSource, onCancel } = sseService.createEventSource(
        `/rest/${collectionId}/solution_summary?agent_run_id=${agentRunId}`,
        (data) => {
          // Update solution summary with streamed data
          dispatch(
            setSolutionSummary({
              agent_run_id: data.agent_run_id,
              summary: data.summary,
              parts: data.parts,
            })
          );
        },
        () => {
          dispatch(onFinishLoadingSolutionSummary());
        },
        dispatch // Pass dispatch function to handle errors
      );

      // Store the cancel function for potential cleanup
      cancelFunctionsMap[taskId] = onCancel;
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error getting solution summary',
          description: 'Failed to retrieve solution summary',
          variant: 'destructive',
        })
      );
      dispatch(onFinishLoadingSolutionSummary());
      throw error;
    }
  }
);

export const clearActionsSummary = createAsyncThunk(
  'transcript/clearActionsSummary',
  async (_, { dispatch }) => {
    dispatch(setActionsSummary(undefined));
    dispatch(setLoadingActionsSummaryForTranscriptId(undefined));
  }
);

export const clearSolutionSummary = createAsyncThunk(
  'transcript/clearSolutionSummary',
  async (_, { dispatch, getState }) => {
    dispatch(setSolutionSummary(undefined));
    dispatch(setLoadingSolutionSummaryForTranscriptId(undefined));
  }
);

export const clearCurAgentRun = createAsyncThunk(
  'transcript/clearCurAgentRun',
  async (_, { dispatch }) => {
    dispatch(setCurAgentRun(undefined));
  }
);

export const clearAltAgentRun = createAsyncThunk(
  'transcript/clearAltAgentRun',
  async (_, { dispatch }) => {
    dispatch(setAltAgentRun(undefined));
  }
);

export const getCurAgentRun = createAsyncThunk(
  'transcript/getAgentRun',
  async (agentRunId: string, { dispatch, getState }) => {
    const state = getState() as RootState;
    const collectionId = state.collection.collectionId;

    // Clear current datapoint
    const curAgentRun = state.transcript.curAgentRun;
    if (curAgentRun !== undefined) {
      dispatch(clearCurAgentRun());
    }

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
        `/${collectionId}/agent_run?agent_run_id=${agentRunId}&apply_base_where_clause=false`
      );

      if (!response.data) {
        dispatch(
          setToastNotification({
            title: 'Agent run not found',
            description: 'The requested agent run could not be found',
            variant: 'destructive',
          })
        );
        return;
      }

      dispatch(setCurAgentRun(response.data));
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error getting agent run',
          description: 'Failed with unknown error',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const openAgentRunInDashboard = createAsyncThunk(
  'transcript/openAgentRunInDashboard',
  async (
    {
      agentRunId,
      blockIdx,
      transcriptIdx,
    }: {
      agentRunId: string;
      blockIdx?: number;
      transcriptIdx?: number;
    },
    { dispatch, getState }
  ) => {
    // First, load the agent run
    await dispatch(getCurAgentRun(agentRunId));

    // Then set the dashboard view state
    dispatch(
      setDashboardAgentRunView({
        dashboardHasRunPreview: true,
        blockIdx,
        transcriptIdx,
      })
    );
  }
);

export const handleAgentRunsUpdated = createAsyncThunk(
  'transcript/handleAgentRunsUpdated',
  async (_, { dispatch, getState }) => {
    const state = getState() as RootState;

    // Refresh current datapoint
    const curAgentRun = state.transcript.curAgentRun;
    if (curAgentRun !== undefined) {
      dispatch(getCurAgentRun(curAgentRun.id));
    }

    // Refresh alternative datapoint
    // const altAgentRun = state.transcript.altAgentRun;
    // if (altAgentRun !== undefined) {
    //   dispatch(getAltAgentRun(altAgentRun.id));
    // }

    // Refresh transcript metadata
    // const transcriptMetadata = state.collection.agentRunMetadata;
    // if (transcriptMetadata !== undefined) {
    //   dispatch(getAgentRunMetadata(Object.keys(transcriptMetadata)));
    // }

    // Refresh transcript metadata fields
    // dispatch(getAgentRunMetadataFields());

    // Show a toast
    dispatch(
      setToastNotification({
        title: 'AgentRuns updated',
        description: 'AgentRuns have been updated',
        variant: 'default',
      })
    );

    // TODO(mengk): Deal with the trees/graphs
  }
);

export const transcriptSlice = createSlice({
  name: 'transcript',
  initialState,
  reducers: {
    setCurAgentRun: (state, action: PayloadAction<AgentRun | undefined>) => {
      state.curAgentRun = action.payload;
    },
    setAltAgentRun: (state, action: PayloadAction<AgentRun | undefined>) => {
      state.altAgentRun = action.payload;
    },
    setActionsSummary: (
      state,
      action: PayloadAction<ActionsSummary | undefined>
    ) => {
      state.actionsSummary = action.payload;
    },
    setLoadingActionsSummaryForTranscriptId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.loadingActionsSummaryForTranscriptId = action.payload;
    },
    setActionsSummaryTaskId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.actionsSummaryTaskId = action.payload;
    },
    onFinishLoadingActionsSummary: (state) => {
      state.loadingActionsSummaryForTranscriptId = undefined;
      state.actionsSummaryTaskId = undefined;
    },
    setSolutionSummary: (
      state,
      action: PayloadAction<SolutionSummary | undefined>
    ) => {
      state.solutionSummary = action.payload;
    },
    setLoadingSolutionSummaryForTranscriptId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.loadingSolutionSummaryForTranscriptId = action.payload;
    },
    setSolutionSummaryTaskId: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.solutionSummaryTaskId = action.payload;
    },
    onFinishLoadingSolutionSummary: (state) => {
      state.loadingSolutionSummaryForTranscriptId = undefined;
      state.solutionSummaryTaskId = undefined;
    },
    setTaAgentRunId: (state, action: PayloadAction<string | undefined>) => {
      state.taAgentRunId = action.payload;
    },
    setTaSessionId: (state, action: PayloadAction<string | undefined>) => {
      state.taSessionId = action.payload;
    },
    setLoadingTaResponse: (
      state,
      action: PayloadAction<boolean | undefined>
    ) => {
      state.loadingTaResponse = action.payload;
    },
    setDashboardAgentRunView: (
      state,
      action: PayloadAction<{
        dashboardHasRunPreview: boolean;
        blockIdx?: number;
        transcriptIdx?: number;
      }>
    ) => {
      state.dashboardHasRunPreview = action.payload.dashboardHasRunPreview;
      state.dashboardScrollToBlockIdx = action.payload.blockIdx;
      state.dashboardScrollToTranscriptIdx = action.payload.transcriptIdx;
    },
    clearDashboardAgentRunView: (state) => {
      state.dashboardHasRunPreview = false;
      state.dashboardScrollToBlockIdx = undefined;
      state.dashboardScrollToTranscriptIdx = undefined;
    },
    setAllCitations: (state, action: PayloadAction<Citation[] | undefined>) => {
      state.allCitations = action.payload;
    },
    setHighlightedCitation: (
      state,
      action: PayloadAction<string | undefined>
    ) => {
      state.highlightedCitationId = action.payload;
    },
    clearHighlightedCitation: (state) => {
      state.highlightedCitationId = undefined;
    },
    setAgentRunSidebarTab: (state, action: PayloadAction<string>) => {
      state.agentRunSidebarTab = action.payload;
    },
    setLeftSidebarOpen: (state, action: PayloadAction<boolean>) => {
      state.leftSidebarOpen = action.payload;
    },
    toggleLeftSidebar: (state) => {
      state.leftSidebarOpen = !(state.leftSidebarOpen ?? false);
    },
    setRightSidebarOpen: (state, action: PayloadAction<boolean>) => {
      state.rightSidebarOpen = action.payload;
    },
    toggleRightSidebar: (state) => {
      state.rightSidebarOpen = !state.rightSidebarOpen;
    },
    resetTranscriptSlice: () => initialState,
  },
});

export const {
  setCurAgentRun,
  setAltAgentRun,
  setActionsSummary,
  setLoadingActionsSummaryForTranscriptId,
  setActionsSummaryTaskId,
  onFinishLoadingActionsSummary,
  setSolutionSummary,
  setLoadingSolutionSummaryForTranscriptId,
  setSolutionSummaryTaskId,
  onFinishLoadingSolutionSummary,
  setTaAgentRunId,
  setTaSessionId,
  setLoadingTaResponse,
  setDashboardAgentRunView,
  clearDashboardAgentRunView,
  resetTranscriptSlice,
  setAllCitations,
  setHighlightedCitation,
  clearHighlightedCitation,
  setAgentRunSidebarTab,
  setLeftSidebarOpen,
  toggleLeftSidebar,
  setRightSidebarOpen,
  toggleRightSidebar,
} = transcriptSlice.actions;

// Memoized selectors to prevent unnecessary rerenders
export const selectAllCitations = createAppSelector(
  [(state) => state.transcript.allCitations],
  (allCitations) => allCitations || []
);

export default transcriptSlice.reducer;
