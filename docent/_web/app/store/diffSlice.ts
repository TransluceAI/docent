import {
  createAsyncThunk,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';
import {
  EvidenceWithCitation,
  StreamedDiffs,
} from '../types/experimentViewerTypes';
import { apiRestClient } from '../services/apiService';
import sseService from '../services/sseService';
import { cancelFunctionsMap } from './searchSlice';
import { setToastNotification } from './toastSlice';
import { RootState } from './store';

export interface DiffState {
  activeDiffTaskId: string | undefined;
  diffLoadingProgress: [number, number] | undefined;
  diffMap: Record<
    string, // key for the datapoint pair, e.g. `${data_id_1}___${data_id_2}`
    {
      claim: string[];
      evidence: EvidenceWithCitation[];
    }
  >;
}

const initialState: DiffState = {
  activeDiffTaskId: undefined,
  diffLoadingProgress: undefined,
  diffMap: {},
};

export const diffSlice = createSlice({
  name: 'diff',
  initialState,
  reducers: {
    setActiveDiffTaskId: (state, action: PayloadAction<string | undefined>) => {
      state.activeDiffTaskId = action.payload;
    },
    setDiffLoadingProgress: (
      state,
      action: PayloadAction<[number, number] | undefined>
    ) => {
      state.diffLoadingProgress = action.payload;
    },
    handleDiffsUpdate: (state, action: PayloadAction<StreamedDiffs>) => {
      const {
        data_id_1,
        data_id_2,
        claim,
        evidence,
        num_pairs_done,
        num_pairs_total,
      } = action.payload;

      // Update the progress counters
      state.diffLoadingProgress = [num_pairs_done, num_pairs_total];

      if (
        data_id_1 === null ||
        data_id_2 === null ||
        claim === null ||
        evidence === null
      ) {
        return;
      }

      // Create a key for the pair of datapoints
      const pairKey = `${data_id_1}___${data_id_2}`;

      // Update the diff map with the new data
      state.diffMap[pairKey] = {
        claim,
        evidence,
      };
    },
  },
});

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
      dispatch(setDiffLoadingProgress([0, 0]));

      // Get the frame grid ID from the state
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

      // Start the compute diffs job
      const response = await apiRestClient.post(
        `/${frameGridId}/start_compute_diffs`,
        {
          fg_id: frameGridId,
          experiment_id_1: experimentId1,
          experiment_id_2: experimentId2,
        }
      );

      const jobId = response.data;

      // Set the job ID as the active diff task ID
      dispatch(setActiveDiffTaskId(jobId));

      // Set up event source to listen for streaming updates using sseService
      const { onCancel } = sseService.createEventSource(
        `/rest/${frameGridId}/listen_compute_diffs?job_id=${jobId}`,
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

export const requestDiffClusters = createAsyncThunk(
  'experimentViewer/requestDiffClusters',
  async (
    {
      experimentId1,
      experimentId2,
    }: { experimentId1: string; experimentId2: string },
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
      // await dispatch(cancelCurrentClusterRequest());

      // Start the cluster dimension job
      const response = await apiRestClient.post(
        `/${frameGridId}/compute_diff_clusters`,
        {
          experiment_id_1: experimentId1,
          experiment_id_2: experimentId2,
        }
      );

      const clusters = response.data;
      console.log(clusters);
      // dispatch(setActiveClusterTaskId(jobId));
    } catch (error) {
      // Cleanup on error
      // dispatch(setActiveClusterTaskId(undefined));
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

export const cancelCurrentDiffRequest = createAsyncThunk(
  'experimentViewer/cancelCurrentDiffRequest',
  async (_, { getState, dispatch }) => {
    const state = getState() as RootState;
    const { activeDiffTaskId } = state.diff;

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

export const {
  setActiveDiffTaskId,
  handleDiffsUpdate,
  setDiffLoadingProgress,
} = diffSlice.actions;

export const diffReducer = diffSlice.reducer;
