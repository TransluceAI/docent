/**
 * Note(mengk): the patterns in this file are highly deprecated!
 * This is not very "React-ive" - having global state like this and using async thunks is highly discouraged.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

import { AgentRun, SolutionSummary } from '../types/transcriptTypes';
import { InlineCitation } from '../types/citationTypes';

import { RootState } from './store';
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
  // Solution summary
  solutionSummary?: SolutionSummary;
  loadingSolutionSummaryForTranscriptId?: string;
  solutionSummaryTaskId?: string;
  // All citations
  allCitations: Record<string, InlineCitation[]>;
  // Agent run sidebar state
  agentRunSidebarTab?: string;
  // Sidebar visibility states for different routes
  agentRunLeftSidebarOpen: boolean;
  agentRunRightSidebarOpen: boolean;
  judgeLeftSidebarOpen: boolean;
  judgeRightSidebarOpen: boolean;
}

const initialState: TranscriptState = {
  agentRunLeftSidebarOpen: false,
  agentRunRightSidebarOpen: true,
  judgeLeftSidebarOpen: true,
  judgeRightSidebarOpen: true,
  allCitations: {},
};

export const transcriptSlice = createSlice({
  name: 'transcript',
  initialState,
  reducers: {
    setCurAgentRun: (state, action: PayloadAction<AgentRun | undefined>) => {
      state.curAgentRun = action.payload;
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
      action: PayloadAction<Record<string, InlineCitation[]>>
    ) => {
      for (const [key, value] of Object.entries(action.payload)) {
        state.allCitations[key] = value;
      }
    },
    setAgentRunSidebarTab: (state, action: PayloadAction<string>) => {
      state.agentRunSidebarTab = action.payload;
    },

    // Sidebar visibility states for different routes
    toggleAgentRunLeftSidebar: (state) => {
      state.agentRunLeftSidebarOpen = !(state.agentRunLeftSidebarOpen ?? false);
    },
    toggleAgentRunRightSidebar: (state) => {
      state.agentRunRightSidebarOpen = !(
        state.agentRunRightSidebarOpen ?? false
      );
    },
    toggleJudgeLeftSidebar: (state) => {
      state.judgeLeftSidebarOpen = !(state.judgeLeftSidebarOpen ?? false);
    },
    toggleJudgeRightSidebar: (state) => {
      state.judgeRightSidebarOpen = !state.judgeRightSidebarOpen;
    },
    resetTranscriptSlice: () => initialState,
  },
});

export const {
  setCurAgentRun,
  setSolutionSummary,
  setLoadingSolutionSummaryForTranscriptId,
  setSolutionSummaryTaskId,
  onFinishLoadingSolutionSummary,
  setDashboardAgentRunView,
  clearDashboardAgentRunView,
  resetTranscriptSlice,
  setRunCitations,
  setAgentRunSidebarTab,

  // Various sidebar states
  toggleAgentRunLeftSidebar,
  toggleJudgeLeftSidebar,
  toggleAgentRunRightSidebar,
  toggleJudgeRightSidebar,
} = transcriptSlice.actions;

export const selectRunCitationsById = (
  state: RootState,
  runId?: string
): InlineCitation[] => {
  if (!runId) return [];
  return state.transcript.allCitations[runId] || [];
};

export default transcriptSlice.reducer;
