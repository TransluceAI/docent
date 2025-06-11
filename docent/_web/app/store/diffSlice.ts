import {
  createAsyncThunk,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';
import { Citation, StreamedDiffs } from '../types/experimentViewerTypes';
import { apiRestClient } from '../services/apiService';
import sseService from '../services/sseService';
import { cancelFunctionsMap } from './searchSlice';
import { setToastNotification } from './toastSlice';
import { RootState } from './store';

export interface Claim {
  id: string;
  idx: number;
  claim_summary: string;
  agent_1_action: string;
  agent_2_action: string;
  evidence: string;
  evidence_with_citations: {
    evidence: string;
    citations: Citation[];
  };
  shared_context: string;
}

export interface TranscriptDiff {
  agent_run_1_id: string;
  agent_run_2_id: string;
  diffs_report_id: string;
  id: string;
  title: string;
  claims: Claim[];
}

export interface DiffTheme {
  diffs_report_id: string;
  name: string;
  description: string;
  claim_ids: string[];
}

export interface DiffsReport {
  id: string;
  name: string;
  experiment_id_1: string;
  experiment_id_2: string;
  clusters?: DiffTheme[];
}

export interface DiffState {
  diffsReport: DiffsReport | undefined;
  activeDiffTaskId: string | undefined;
  diffLoadingProgress: [number, number] | undefined;
  transcriptDiffsByKey: Record<string, TranscriptDiff>;
  filteredClaimIds: string[] | undefined;
  selectedCluster: DiffTheme | undefined;
}

const initialState: DiffState = {
  diffsReport: undefined,
  activeDiffTaskId: undefined,
  diffLoadingProgress: undefined,
  transcriptDiffsByKey: {},
  filteredClaimIds: undefined,
  selectedCluster: undefined,
};

export const diffSlice = createSlice({
  name: 'diff',
  initialState,
  reducers: {
    setDiffsReport: (state, action: PayloadAction<DiffsReport>) => {
      state.diffsReport = action.payload;
    },
    setDiffsReportClusters: (state, action: PayloadAction<DiffTheme[]>) => {
      state.diffsReport!.clusters = action.payload;
    },
    setActiveDiffTaskId: (state, action: PayloadAction<string | undefined>) => {
      state.activeDiffTaskId = action.payload;
    },
    setDiffLoadingProgress: (
      state,
      action: PayloadAction<[number, number] | undefined>
    ) => {
      state.diffLoadingProgress = action.payload;
    },
    setDiffs: (
      state,
      action: PayloadAction<Record<string, TranscriptDiff>>
    ) => {
      Object.assign(state.transcriptDiffsByKey, action.payload);
    },
    handleDiffsUpdate: (state, action: PayloadAction<StreamedDiffs>) => {
      console.log('suppers', action.payload);
      const {
        num_pairs_done,
        num_pairs_total,
        transcript_diff: diff,
      } = action.payload;

      // Update the progress counters
      state.diffLoadingProgress = [num_pairs_done, num_pairs_total];

      if (!diff) {
        return;
      }

      // Create a key for the pair of datapoints
      const pairKey = `${diff.agent_run_1_id}___${diff.agent_run_2_id}`;
      state.transcriptDiffsByKey[pairKey] = diff;
    },
    focusCluster: (state, action: PayloadAction<DiffTheme | null>) => {
      const theme = action.payload;
      if (theme) {
        state.filteredClaimIds = theme.claim_ids;
        state.selectedCluster = theme;
      } else {
        state.filteredClaimIds = undefined;
        state.selectedCluster = undefined;
      }
    },
  },
});

export const requestDiffsReport = createAsyncThunk(
  'diff/requestDiffReport',
  async (
    { diffsReportId }: { diffsReportId: string },
    { dispatch, getState }
  ) => {
    const state = getState() as RootState;
    const frameGridId = state.frame.frameGridId;
    if (!frameGridId) {
      throw new Error('No frame grid ID available');
    }
    const response = await apiRestClient.get(
      `/${frameGridId}/diffs_reports/${diffsReportId}`
    );
    const { id, name, experiment_id_1, experiment_id_2, diffs } = response.data;
    const diffReport = {
      id,
      name,
      experiment_id_1,
      experiment_id_2,
    };

    const diffsByKey = diffs.reduce((acc: Record<string, TranscriptDiff>, diff: TranscriptDiff) => {
      const pairKey = `${diff.agent_run_1_id}___${diff.agent_run_2_id}`;
      acc[pairKey] = diff;
      return acc;
    }, {});

    dispatch(setDiffs(diffsByKey));
    dispatch(setDiffsReport(diffReport));
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

      const { job_id, diffs_report_id } = response.data;

      // Set the job ID as the active diff task ID
      dispatch(setActiveDiffTaskId(job_id));

      // Set up event source to listen for streaming updates using sseService
      const { onCancel } = sseService.createEventSource(
        `/rest/${frameGridId}/listen_compute_diffs?job_id=${job_id}`,
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
      cancelFunctionsMap[job_id] = onCancel;
      return diffs_report_id as string;
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
    { diffsReportId }: { diffsReportId: string },
    { dispatch, getState }
  ) => {
    const state = getState() as RootState;
    const diffsReport = state.diff.diffsReport;
    if (!diffsReport) {
      throw new Error('No diffs report available');
    }
    const { experiment_id_1, experiment_id_2 } = diffsReport;
    // Get the frame grid ID from the state
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
          diffs_report_id: diffsReportId,
        }
      );

      const clusters = response.data;
      dispatch(setDiffsReportClusters(clusters));
      console.log(clusters);
    } catch (error) {
      // Cleanup on error
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

export const requestTranscriptDiff = createAsyncThunk(
  'diff/requestTranscriptDiff',
  async (
    { agentRun1Id, agentRun2Id }: { agentRun1Id: string; agentRun2Id: string },
    { dispatch, getState }
  ) => {
    const state = getState() as RootState;
    const frameGridId = state.frame.frameGridId;
    if (!frameGridId) {
      throw new Error('No frame grid ID available');
    }
    const response = await apiRestClient.get(
      `/${frameGridId}/transcript_diff?agent_run_1_id=${agentRun1Id}&agent_run_2_id=${agentRun2Id}`
    );
    const diff = response.data;
    if (diff) {
      const pairKey = `${agentRun1Id}___${agentRun2Id}`;
      dispatch(setDiffs({ [pairKey]: diff }));
    }
  }
);

export const {
  setDiffsReport,
  setActiveDiffTaskId,
  handleDiffsUpdate,
  setDiffLoadingProgress,
  setDiffs,
  setDiffsReportClusters,
  focusCluster,
} = diffSlice.actions;

export const diffReducer = diffSlice.reducer;
