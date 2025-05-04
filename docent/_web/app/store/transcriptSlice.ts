import { createSlice, PayloadAction, createAsyncThunk } from '@reduxjs/toolkit';
import socketService from '../services/socketService';
import sseService from '../services/sseService';
import {
  ActionsSummary,
  ChatMessage,
  Datapoint,
  SolutionSummary,
  TaMessage,
} from '../types/transcriptTypes';
import { RootState } from './store';
import {
  getTranscriptMetadata,
  getTranscriptMetadataFields,
} from './frameSlice';
import { apiRestClient } from '../services/apiService';
import { setToastNotification } from './toastSlice';

// Map to store cancel functions for active SSE connections
const cancelFunctionsMap: Record<string, () => void> = {};

export interface TranscriptState {
  curDatapoint?: Datapoint;
  // Actions summary
  actionsSummary?: ActionsSummary;
  loadingActionsSummaryForTranscriptId?: string;
  actionsSummaryTaskId?: string;
  // Solution summary
  solutionSummary?: SolutionSummary;
  loadingSolutionSummaryForTranscriptId?: string;
  solutionSummaryTaskId?: string;
  // Chat assistant
  taDatapointId?: string;
  taSessionId?: string;
  taMessages?: TaMessage[];
  taMessageTaskId?: string;
  loadingTaResponse?: boolean;
}

const initialState: TranscriptState = {};

export const getActionsSummary = createAsyncThunk(
  'transcript/getActionsSummary',
  async (datapointId: string, { dispatch, getState }) => {
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
    dispatch(setLoadingActionsSummaryForTranscriptId(datapointId));

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
        `/rest/actions_summary?fg_id=${frameGridId}&datapoint_id=${datapointId}`,
        (data) => {
          // Update actions summary with streamed data
          dispatch(
            setActionsSummary({
              datapoint_id: data.datapoint_id,
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
  async (datapointId: string, { dispatch, getState }) => {
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
    dispatch(setLoadingSolutionSummaryForTranscriptId(datapointId));

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
        `/rest/solution_summary?fg_id=${frameGridId}&datapoint_id=${datapointId}`,
        (data) => {
          // Update solution summary with streamed data
          dispatch(
            setSolutionSummary({
              datapoint_id: data.datapoint_id,
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

export const clearCurDatapoint = createAsyncThunk(
  'transcript/clearCurDatapoint',
  async (_, { dispatch }) => {
    dispatch(setCurDatapoint(undefined));
  }
);

export const getCurDatapoint = createAsyncThunk(
  'transcript/getDatapoint',
  async (datapointId: string, { dispatch, getState }) => {
    const state = getState() as RootState;
    const frameGridId = state.frame.frameGridId;

    // Clear current datapoint
    const curDatapoint = state.transcript.curDatapoint;
    if (curDatapoint !== undefined) {
      dispatch(clearCurDatapoint());
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
        `/datapoint?fg_id=${frameGridId}&datapoint_id=${datapointId}`
      );
      dispatch(setCurDatapoint(response.data));
    } catch (error) {
      dispatch(
        setToastNotification({
          title: 'Error getting datapoint',
          description: 'Failed to retrieve datapoint information',
          variant: 'destructive',
        })
      );
      throw error;
    }
  }
);

export const handleDatapointsUpdated = createAsyncThunk(
  'transcript/handleDatapointsUpdated',
  async (_, { dispatch, getState }) => {
    const state = getState() as RootState;

    // Refresh current datapoint
    const curDatapoint = state.transcript.curDatapoint;
    if (curDatapoint !== undefined) {
      dispatch(getCurDatapoint(curDatapoint.id));
    }

    // Refresh transcript metadata
    const transcriptMetadata = state.frame.transcriptMetadata;
    if (transcriptMetadata !== undefined) {
      dispatch(getTranscriptMetadata(Object.keys(transcriptMetadata)));
    }

    // Refresh transcript metadata fields
    dispatch(getTranscriptMetadataFields());

    // Show a toast
    dispatch(
      setToastNotification({
        title: 'Datapoints updated',
        description: 'Datapoints have been updated',
        variant: 'default',
      })
    );

    // TODO(mengk): Deal with the trees/graphs
  }
);

export const createTaSession = createAsyncThunk(
  'transcript/createTaSession',
  async (datapointId: string, { dispatch, getState }) => {
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
      const response = await apiRestClient.post('/ta_session', {
        fg_id: frameGridId,
        base_filter: {
          type: 'datapoint_id',
          value: datapointId,
        },
      });

      // Set the session ID and datapoint ID
      dispatch(setTaSessionId(response.data.session_id));
      dispatch(setTaDatapointId(datapointId));

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
        `/rest/ta_message?session_id=${taSessionId}&message=${encodeURIComponent(message)}`,
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
    dispatch(setTaDatapointId(undefined));
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
    setCurDatapoint: (state, action: PayloadAction<Datapoint | undefined>) => {
      state.curDatapoint = action.payload;
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
    setTaDatapointId: (state, action: PayloadAction<string | undefined>) => {
      state.taDatapointId = action.payload;
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
  setCurDatapoint,
  setActionsSummary,
  setLoadingActionsSummaryForTranscriptId,
  setActionsSummaryTaskId,
  onFinishLoadingActionsSummary,
  setSolutionSummary,
  setLoadingSolutionSummaryForTranscriptId,
  setSolutionSummaryTaskId,
  onFinishLoadingSolutionSummary,
  setTaDatapointId,
  setTaSessionId,
  setTaMessages,
  setLoadingTaResponse,
  setTaMessageTaskId,
  resetTranscriptSlice,
} = transcriptSlice.actions;

export default transcriptSlice.reducer;
