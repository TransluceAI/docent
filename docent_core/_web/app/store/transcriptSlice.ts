/**
 * Note(mengk): the patterns in this file are highly deprecated!
 * This is not very "React-ive" - having global state like this and using async thunks is highly discouraged.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { Comment } from '../api/labelApi';
import { AgentRun, SolutionSummary } from '../types/transcriptTypes';
import { CitationTarget, InlineCitation } from '../types/citationTypes';
import { TextSelectionItem } from '../../providers/use-text-selection';

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
  hoveredCommentId: string | null;
  selectedCommentId: string | null;
  // Agent run sidebar state
  agentRunSidebarTab?: string;
  // Sidebar visibility states for different routes
  agentRunLeftSidebarOpen: boolean;
  agentRunRightSidebarOpen: boolean;
  judgeLeftSidebarOpen: boolean;
  judgeRightSidebarOpen: boolean;

  // Text selections
  textSelections: TextSelectionItem[];
  // Draft comment (multi-citation creation flow)
  draftComment: Comment | null;
  commentSidebarCollapsed: boolean;
}

const initialState: TranscriptState = {
  agentRunLeftSidebarOpen: false,
  agentRunRightSidebarOpen: true,
  judgeLeftSidebarOpen: true,
  judgeRightSidebarOpen: true,
  allCitations: {},

  hoveredCommentId: null,
  selectedCommentId: null,
  textSelections: [],
  draftComment: null,
  commentSidebarCollapsed: true,
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

    // Mainly used for controlling the tab when switching between pages. E.g. if i want to ensure that the tab is on
    // "chat" when I jump to a rubric page
    setAgentRunSidebarTab: (state, action: PayloadAction<string>) => {
      state.agentRunSidebarTab = action.payload;
    },

    // Various sidebar states
    // Sidebar visibility states for different routes
    setAgentRunLeftSidebarOpen: (state, action: PayloadAction<boolean>) => {
      state.agentRunLeftSidebarOpen = action.payload;
    },
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

    // Comment states
    setHoveredCommentId: (state, action: PayloadAction<string | null>) => {
      state.hoveredCommentId = action.payload;
    },
    setSelectedCommentId: (state, action: PayloadAction<string | null>) => {
      state.selectedCommentId = action.payload;
    },

    // Text selections
    setTextSelections: (state, action: PayloadAction<TextSelectionItem[]>) => {
      state.textSelections = action.payload;
    },
    addCitationToDraft: (state, action: PayloadAction<CitationTarget>) => {
      state.draftComment = {
        id: 'draft',
        citations: [
          {
            start_idx: 0,
            end_idx: 0,
            target: action.payload,
          },
        ],
        content: '',
        user_email: '',
        collection_id: '',
        agent_run_id: '',
        created_at: '',
      };
    },
    updateDraftContent: (state, action: PayloadAction<string>) => {
      if (state.draftComment) {
        state.draftComment.content = action.payload;
      }
    },
    clearDraftComment: (state) => {
      state.draftComment = null;
    },

    setCommentSidebarCollapsed: (state, action: PayloadAction<boolean>) => {
      state.commentSidebarCollapsed = action.payload;
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
  setAgentRunLeftSidebarOpen,
  toggleAgentRunLeftSidebar,
  toggleJudgeLeftSidebar,
  toggleAgentRunRightSidebar,
  toggleJudgeRightSidebar,

  // Comment states
  setHoveredCommentId,
  setSelectedCommentId,

  // Text selections
  setTextSelections,
  addCitationToDraft,
  updateDraftContent,
  clearDraftComment,
  setCommentSidebarCollapsed,
} = transcriptSlice.actions;

export const selectRunCitationsById = (
  state: RootState,
  runId?: string
): InlineCitation[] => {
  if (!runId) return [];
  return state.transcript.allCitations[runId] || [];
};

export const selectTextSelections = (state: RootState) =>
  state.transcript.textSelections;

export default transcriptSlice.reducer;
