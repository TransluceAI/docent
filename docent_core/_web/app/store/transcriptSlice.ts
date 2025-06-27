import {
  createSlice,
  type PayloadAction,
  createAsyncThunk,
} from '@reduxjs/toolkit';

import { apiRestClient } from '../services/apiService';
import socketService from '../services/socketService';
import sseService from '../services/sseService';
import {
  ActionsSummary,
  AgentRun,
  SolutionSummary,
  TaMessage,
} from '../types/transcriptTypes';

import { getAgentRunMetadata, getAgentRunMetadataFields } from './frameSlice';
import { RootState } from './store';
import { setToastNotification } from './toastSlice';

// Map to store cancel functions for active SSE connections
const cancelFunctionsMap: Record<string, () => void> = {};

export interface TranscriptState {
  curAgentRun?: AgentRun;
  altAgentRun?: AgentRun;
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
  taMessages?: TaMessage[];
  taMessageTaskId?: string;
  loadingTaResponse?: boolean;
}

const initialState: TranscriptState = {};

export const getActionsSummary = createAsyncThunk(
  'transcript/getActionsSummary',
  async (agentRunId: string, { dispatch, getState }) => {
    const state = getState() as RootState;
    const frameGridId = state.frame.frameGridId;

    // Cancel existing request
    const { actionsSummaryTaskId } = state.transcript;
    if (actionsSummaryTaskId && cancelFunctionsMap[actionsSummaryTaskId]) {
      cancelFunctionsMap[actionsSummaryTaskId]();
      delete cancelFunctionsMap[actionsSummaryTaskId];
    }

    // Set UI state
    dispatch(setActionsSummary(undefined));
    dispatch(setLoadingActionsSummaryForTranscriptId(agentRunId));

    if (!frameGridId) {
      dispatch(
        setToastNotification({
          title: 'Configuration error',
          description: 'No frame grid ID available',
          variant: 'destructive',
        })
      );
      dispatch(onFinishLoadingActionsSummary());
      throw new Error('No frame grid ID available');
    }

    try {
      // Generate a task ID for cancellation
      const taskId = socketService.generateTaskId();
      dispatch(setActionsSummaryTaskId(taskId));

      // Create SSE connection using the service
      const { eventSource, onCancel } = sseService.createEventSource(
        `/rest/${frameGridId}/actions_summary?agent_run_id=${agentRunId}`,
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
    const frameGridId = state.frame.frameGridId;

    // Cancel existing request
    const { solutionSummaryTaskId } = state.transcript;
    if (solutionSummaryTaskId && cancelFunctionsMap[solutionSummaryTaskId]) {
      cancelFunctionsMap[solutionSummaryTaskId]();
      delete cancelFunctionsMap[solutionSummaryTaskId];
    }

    // Set UI state
    dispatch(setSolutionSummary(undefined));
    dispatch(setLoadingSolutionSummaryForTranscriptId(agentRunId));

    if (!frameGridId) {
      dispatch(
        setToastNotification({
          title: 'Configuration error',
          description: 'No frame grid ID available',
          variant: 'destructive',
        })
      );
      dispatch(onFinishLoadingSolutionSummary());
      throw new Error('No frame grid ID available');
    }

    try {
      // Generate a task ID for cancellation
      const taskId = socketService.generateTaskId();
      dispatch(setSolutionSummaryTaskId(taskId));

      // Create SSE connection using the service
      const { eventSource, onCancel } = sseService.createEventSource(
        `/rest/${frameGridId}/solution_summary?agent_run_id=${agentRunId}`,
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
    const frameGridId = state.frame.frameGridId;

    // Clear current datapoint
    const curAgentRun = state.transcript.curAgentRun;
    if (curAgentRun !== undefined) {
      dispatch(clearCurAgentRun());
    }

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
        `/${frameGridId}/agent_run?agent_run_id=${agentRunId}`
      );
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

export const getAltAgentRun = createAsyncThunk(
  'transcript/getAltAgentRun',
  async (agentRunId: string, { dispatch, getState }) => {
    const state = getState() as RootState;
    const frameGridId = state.frame.frameGridId;

    // Clear current datapoint
    const altAgentRun = state.transcript.altAgentRun;
    if (altAgentRun !== undefined) {
      dispatch(clearAltAgentRun());
    }

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
      const response = await await apiRestClient.get(
        `/${frameGridId}/agent_run?agent_run_id=${agentRunId}`
      );
      console.log('response', response);
      dispatch(setAltAgentRun(response.data));
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
    const altAgentRun = state.transcript.altAgentRun;
    if (altAgentRun !== undefined) {
      dispatch(getAltAgentRun(altAgentRun.id));
    }

    // Refresh transcript metadata
    const transcriptMetadata = state.frame.agentRunMetadata;
    if (transcriptMetadata !== undefined) {
      dispatch(getAgentRunMetadata(Object.keys(transcriptMetadata)));
    }

    // Refresh transcript metadata fields
    dispatch(getAgentRunMetadataFields());

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

export const createTaSession = createAsyncThunk(
  'transcript/createTaSession',
  async (agentRunId: string, { dispatch, getState }) => {
    const state = getState() as RootState;
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
      // Reset existing session if any
      dispatch(resetTaSession());

      // Create a new TA session via REST API
      const response = await apiRestClient.post(`/${frameGridId}/ta_session`, {
        base_filter: {
          type: 'agent_run_id',
          value: agentRunId,
        },
      });

      // Set the session ID and datapoint ID
      dispatch(setTaSessionId(response.data.session_id));
      dispatch(setTaAgentRunId(agentRunId));

      // Initialize empty messages array
      dispatch(setTaMessages([]));
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error creating TA session',
          description: 'Failed to initialize teaching assistant session',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const sendTaMessage = createAsyncThunk(
  'transcript/sendTaMessage',
  async (message: string, { dispatch, getState }) => {
    const state = getState() as RootState;
    const { taSessionId } = state.transcript;
    const frameGridId = state.frame.frameGridId;

    if (!taSessionId) {
      dispatch(
        setToastNotification({
          title: 'Configuration error',
          description: 'No TA session ID available',
          variant: 'destructive',
        })
      );
      throw new Error('No TA session ID available');
    }

    // Cancel existing request
    const { taMessageTaskId } = state.transcript;
    if (taMessageTaskId && cancelFunctionsMap[taMessageTaskId]) {
      cancelFunctionsMap[taMessageTaskId]();
      delete cancelFunctionsMap[taMessageTaskId];
    }

    // Set loading state
    dispatch(setLoadingTaResponse(true));

    try {
      // Generate a task ID for cancellation
      const taskId = socketService.generateTaskId();
      dispatch(setTaMessageTaskId(taskId));

      // Create SSE connection
      const { eventSource, onCancel } = sseService.createEventSource(
        `/rest/${frameGridId}/ta_message?session_id=${taSessionId}&message=${encodeURIComponent(message)}`,
        (data) => {
          if (data.messages) {
            dispatch(setTaMessages(data.messages));
          }
        },
        () => {
          dispatch(setLoadingTaResponse(false));
          dispatch(setTaMessageTaskId(undefined));
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
      cancelFunctionsMap[taskId] = onCancel;
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error sending message',
          description: 'Failed to send message to teaching assistant',
          variant: 'destructive',
        })
      );
      dispatch(setLoadingTaResponse(false));
      dispatch(setTaMessageTaskId(undefined));
      throw error;
    }
  }
);

export const resetTaSession = createAsyncThunk(
  'transcript/resetTaSession',
  async (_, { dispatch, getState }) => {
    const state = getState() as RootState;

    // Cancel existing request if exists
    const { taMessageTaskId } = state.transcript;
    if (taMessageTaskId && cancelFunctionsMap[taMessageTaskId]) {
      cancelFunctionsMap[taMessageTaskId]();
      delete cancelFunctionsMap[taMessageTaskId];
    }

    // Reset TA state
    dispatch(setTaAgentRunId(undefined));
    dispatch(setTaSessionId(undefined));
    dispatch(setTaMessages(undefined));
    dispatch(setLoadingTaResponse(false));
    dispatch(setTaMessageTaskId(undefined));
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
    setTaMessages: (state, action: PayloadAction<TaMessage[] | undefined>) => {
      state.taMessages = action.payload;
    },
    setLoadingTaResponse: (
      state,
      action: PayloadAction<boolean | undefined>
    ) => {
      state.loadingTaResponse = action.payload;
    },
    setTaMessageTaskId: (state, action: PayloadAction<string | undefined>) => {
      state.taMessageTaskId = action.payload;
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
  setTaMessages,
  setLoadingTaResponse,
  setTaMessageTaskId,
  resetTranscriptSlice,
} = transcriptSlice.actions;

export default transcriptSlice.reducer;
