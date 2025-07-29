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

export interface RubricCentroid {
  id: string;
  collection_id: string;
  rubric_id: string;
  centroid: string;
}

export interface RubricState {
  activeRubricId: string | null;
  editingRubricId: string | null;
  rubricsMap: Record<string, Rubric>; // rubric_id -> Rubric
  activeRubricJobId: string | null;
  judgeResultsMap: Record<string, JudgeResultWithCitations>; // judge_result_id -> JudgeResult
  isPollingResults: boolean;
  totalAgentRuns: number | null;
  // Clustering state
  centroidsMap: Record<string, RubricCentroid>; // centroid_id -> centroid
  centroidAssignments: Record<string, string[]>; // centroid_id -> judge_result_ids
  isPollingAssignments: boolean;
  activeCentroidAssignmentJobId: string | null;
}

const initialState: RubricState = {
  activeRubricId: null,
  editingRubricId: null,
  rubricsMap: {},
  judgeResultsMap: {},
  isPollingResults: false,
  totalAgentRuns: null,
  activeRubricJobId: null,
  // Clustering state
  centroidsMap: {},
  centroidAssignments: {},
  isPollingAssignments: false,
  activeCentroidAssignmentJobId: null,
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

const convertCentroidsArrayToMap = (
  centroids: RubricCentroid[]
): Record<string, RubricCentroid> => {
  return centroids.reduce(
    (acc, centroid) => {
      acc[centroid.id] = centroid;
      return acc;
    },
    {} as Record<string, RubricCentroid>
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
      const judgeResultsList: JudgeResultWithCitations[] = action.payload;
      state.judgeResultsMap = judgeResultsList.reduce(
        (acc, result) => {
          acc[result.id] = result;
          return acc;
        },
        {} as Record<string, JudgeResultWithCitations>
      );
    },
    clearJudgeResults(state) {
      state.judgeResultsMap = {};
      state.totalAgentRuns = null;
    },
    setIsPollingResults(state, action) {
      state.isPollingResults = action.payload;
    },
    setTotalAgentRuns(state, action) {
      state.totalAgentRuns = action.payload;
    },
    setActiveRubricJobId(state, action) {
      state.activeRubricJobId = action.payload;
    },
    // Clustering actions
    setCentroids(state, action) {
      state.centroidsMap = convertCentroidsArrayToMap(action.payload.centroids);
    },
    clearCentroids(state) {
      state.centroidsMap = {};
      state.centroidAssignments = {};
    },
    setCentroidAssignments(state, action) {
      state.centroidAssignments = action.payload;
    },
    setIsPollingAssignments(state, action) {
      state.isPollingAssignments = action.payload;
    },
    setActiveCentroidAssignmentJob(state, action) {
      state.activeCentroidAssignmentJobId = action.payload;
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
          state.activeRubricJobId = action.payload.job_id;
        }
      )
      // Handle clustering endpoints
      .addMatcher(
        rubricApi.endpoints.proposeCentroids.matchFulfilled,
        (state, action) => {
          state.centroidsMap = convertCentroidsArrayToMap(
            action.payload.centroids
          );
        }
      )
      .addMatcher(
        rubricApi.endpoints.getCentroids.matchFulfilled,
        (state, action) => {
          state.centroidsMap = convertCentroidsArrayToMap(
            action.payload.centroids
          );
        }
      )
      .addMatcher(
        rubricApi.endpoints.clearCentroids.matchFulfilled,
        (state) => {
          state.centroidsMap = {};
          state.centroidAssignments = {};
        }
      )
      .addMatcher(
        rubricApi.endpoints.startCentroidAssignment.matchFulfilled,
        (state, action) => {
          state.activeCentroidAssignmentJobId = action.payload.job_id;
        }
      )
      .addMatcher(
        rubricApi.endpoints.getCentroidAssignments.matchFulfilled,
        (state, action) => {
          state.centroidAssignments = action.payload.assignments;
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
  setActiveRubricJobId,
  setCentroids,
  clearCentroids,
  setCentroidAssignments,
  setIsPollingAssignments,
  setActiveCentroidAssignmentJob,
} = rubricSlice.actions;

export default rubricSlice.reducer;
