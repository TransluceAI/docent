import { createSlice } from '@reduxjs/toolkit';
import { rubricApi } from '../api/rubricApi';
import { Citation } from '../types/experimentViewerTypes';

export interface Rubric {
  id: string;
  high_level_description: string;
  inclusion_rules: string[];
  exclusion_rules: string[];
}

export interface JudgeResult {
  id: string;
  agent_run_id: string;
  rubric_id: string;
  value: string | null;
}

export interface JudgeResultWithCitations extends JudgeResult {
  citations: Citation[] | null;
}

export interface RubricState {
  activeRubricId: string | null;
  editingRubricId: string | null;
  rubricsMap: Record<string, Rubric>; // rubric_id -> Rubric
  activeJobId: string | null;
  judgeResultsMap: Record<string, JudgeResultWithCitations[]> | null; // agent_run_id -> JudgeResult[]
  isPollingResults: boolean;
  totalAgentRuns: number | null;
}

const initialState: RubricState = {
  activeRubricId: null,
  editingRubricId: null,
  rubricsMap: {},
  judgeResultsMap: null,
  isPollingResults: false,
  totalAgentRuns: null,
  activeJobId: null,
};

// Helper function to convert rubrics array to map
const convertRubricsArrayToMap = (
  rubrics: Rubric[]
): Record<string, Rubric> => {
  return rubrics.reduce(
    (acc, rubric) => {
      acc[rubric.id] = rubric;
      return acc;
    },
    {} as Record<string, Rubric>
  );
};

export const rubricSlice = createSlice({
  name: 'rubric',
  initialState,
  reducers: {
    setActiveRubricId(state, action) {
      state.activeRubricId = action.payload;
    },
    setEditingRubricId(state, action) {
      state.editingRubricId = action.payload;
    },
    setRubricsMap(state, action) {
      state.rubricsMap = action.payload;
    },
    setRubric(state, action) {
      state.rubricsMap[action.payload.id] = action.payload;
    },
    setJudgeResults(state, action) {
      // Convert into a map
      const judgeResultsList: JudgeResultWithCitations[] = action.payload;
      state.judgeResultsMap = judgeResultsList.reduce<
        Record<string, JudgeResultWithCitations[]>
      >((acc, result) => {
        (acc[result.agent_run_id] ??= []).push(result);
        return acc;
      }, {});
    },
    clearJudgeResults(state) {
      state.judgeResultsMap = null;
      state.totalAgentRuns = null;
    },
    setIsPollingResults(state, action) {
      state.isPollingResults = action.payload;
    },
    setTotalAgentRuns(state, action) {
      state.totalAgentRuns = action.payload;
    },
    setActiveJobId(state, action) {
      state.activeJobId = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      // Handle getRubrics fulfilled
      .addMatcher(
        rubricApi.endpoints.getRubrics.matchFulfilled,
        (state, action) => {
          state.rubricsMap = convertRubricsArrayToMap(action.payload);
        }
      )
      // Handle createRubric fulfilled
      .addMatcher(
        rubricApi.endpoints.createRubric.matchFulfilled,
        (state, action) => {
          state.rubricsMap = convertRubricsArrayToMap(action.payload);
        }
      )
      // Handle updateRubric fulfilled
      .addMatcher(
        rubricApi.endpoints.updateRubric.matchFulfilled,
        (state, action) => {
          state.rubricsMap = convertRubricsArrayToMap(action.payload);
        }
      )
      // Handle deleteRubric fulfilled
      .addMatcher(
        rubricApi.endpoints.deleteRubric.matchFulfilled,
        (state, action) => {
          state.rubricsMap = convertRubricsArrayToMap(action.payload);
          // Clear active/editing state if the deleted rubric was active or being edited
          if (
            state.activeRubricId &&
            !action.payload.some((r) => r.id === state.activeRubricId)
          ) {
            state.activeRubricId = null;
          }
          if (
            state.editingRubricId &&
            !action.payload.some((r) => r.id === state.editingRubricId)
          ) {
            state.editingRubricId = null;
          }
        }
      )
      // Handle startEvaluation fulfilled
      .addMatcher(
        rubricApi.endpoints.startEvaluation.matchFulfilled,
        (state, action) => {
          state.activeJobId = action.payload.job_id;
        }
      );
  },
});

export const {
  setActiveRubricId,
  setEditingRubricId,
  setRubricsMap,
  setRubric,
  setJudgeResults,
  clearJudgeResults,
  setIsPollingResults,
  setTotalAgentRuns,
  setActiveJobId,
} = rubricSlice.actions;

export default rubricSlice.reducer;
