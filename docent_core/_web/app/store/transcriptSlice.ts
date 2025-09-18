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

// Map to store cancel functions for active SSE connections
const cancelFunctionsMap: Record<string, () => void> = {};

// Utility functions for TA session localStorage keys
export const getTaSessionStorageKey = (agentRunId: string) =>
  `ta-session-${agentRunId}`;

export interface TranscriptState {
  // Cur
  curAgentRun?: AgentRun;
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
  // All citations
  allCitations: Record<string, Citation[]>;
  // Citation highlighting
  highlightedCitationId: string | null;
  // Agent run sidebar state
  agentRunSidebarTab?: string;
  // Sidebar visibility states for different routes
  agentRunLeftSidebarOpen: boolean;
  judgeLeftSidebarOpen: boolean;
  rightSidebarOpen: boolean;
}

const initialState: TranscriptState = {
  agentRunLeftSidebarOpen: false,
  judgeLeftSidebarOpen: true,
  rightSidebarOpen: true,
  allCitations: {},
  highlightedCitationId: null,
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
      const { onCancel } = sseService.createEventSource(
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
      const { onCancel } = sseService.createEventSource(
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

export const transcriptSlice = createSlice({
  name: 'transcript',
  initialState,
  reducers: {
    setCurAgentRun: (state, action: PayloadAction<AgentRun | undefined>) => {
      state.curAgentRun = action.payload;
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
    setRunCitations: (
      state,
      action: PayloadAction<Record<string, Citation[]>>
    ) => {
      for (const [key, value] of Object.entries(action.payload)) {
        state.allCitations[key] = value;
      }
    },
    setHighlightedCitation: (state, action: PayloadAction<string | null>) => {
      state.highlightedCitationId = action.payload;
    },
    clearHighlightedCitation: (state) => {
      state.highlightedCitationId = null;
    },
    setAgentRunSidebarTab: (state, action: PayloadAction<string>) => {
      state.agentRunSidebarTab = action.payload;
    },
    setAgentRunLeftSidebarOpen: (state, action: PayloadAction<boolean>) => {
      state.agentRunLeftSidebarOpen = action.payload;
    },
    toggleAgentRunLeftSidebar: (state) => {
      state.agentRunLeftSidebarOpen = !(state.agentRunLeftSidebarOpen ?? false);
    },
    setJudgeLeftSidebarOpen: (state, action: PayloadAction<boolean>) => {
      state.judgeLeftSidebarOpen = action.payload;
    },
    toggleJudgeLeftSidebar: (state) => {
      state.judgeLeftSidebarOpen = !(state.judgeLeftSidebarOpen ?? false);
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
  setActionsSummary,
  setLoadingActionsSummaryForTranscriptId,
  setActionsSummaryTaskId,
  onFinishLoadingActionsSummary,
  setSolutionSummary,
  setLoadingSolutionSummaryForTranscriptId,
  setSolutionSummaryTaskId,
  onFinishLoadingSolutionSummary,
  setDashboardAgentRunView,
  clearDashboardAgentRunView,
  resetTranscriptSlice,
  setRunCitations,
  setHighlightedCitation,
  clearHighlightedCitation,
  setAgentRunSidebarTab,
  setAgentRunLeftSidebarOpen,
  toggleAgentRunLeftSidebar,
  setJudgeLeftSidebarOpen,
  toggleJudgeLeftSidebar,
  setRightSidebarOpen,
  toggleRightSidebar,
} = transcriptSlice.actions;

export const selectRunCitationsById = (state: RootState, runId?: string) => {
  if (!runId) return [] as Citation[];
  return state.transcript.allCitations[runId] || [];
};

export default transcriptSlice.reducer;
