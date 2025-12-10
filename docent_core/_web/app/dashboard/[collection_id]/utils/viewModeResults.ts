import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import { Label } from '@/app/api/labelApi';

export type ViewMode =
  | 'all'
  | 'labeled_disagreement'
  | 'missing_labels'
  | 'incomplete_labels';

const getResults = (agentRun: AgentRunJudgeResults) =>
  agentRun.results.filter((result) => result.result_type === 'DIRECT_RESULT');

function calculateHumanMissFraction(agentRun: AgentRunJudgeResults): number {
  const results = getResults(agentRun);
  const { reflection } = agentRun;
  if (!reflection || results.length === 0 || !reflection.issues) {
    return 0;
  }

  const humanMissRolloutIndices = new Set<number>();

  for (const issue of reflection.issues) {
    if (issue.type === 'human_miss') {
      for (const index of issue.rollout_indices) {
        humanMissRolloutIndices.add(index);
      }
    }
  }

  const humanMissCount = humanMissRolloutIndices.size;
  return humanMissCount / results.length;
}

function calculateControversyScore(agentRun: AgentRunJudgeResults): number {
  const results = getResults(agentRun);
  const labels = results.map((result) => result.output?.label);
  if (labels.length === 0) return 0;

  const labelCounts = labels.reduce(
    (acc, label) => {
      acc[label] = (acc[label] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  const mode = Object.keys(labelCounts).reduce((a, b) =>
    labelCounts[a] > labelCounts[b] ? a : b
  );
  const nonModalFraction = 1 - labelCounts[mode] / results.length;

  return nonModalFraction;
}

function calculateJudgeLabelDisagreementScore(
  agentRun: AgentRunJudgeResults,
  labels: Label[]
): number {
  const { agent_run_id } = agentRun;
  const results = getResults(agentRun);
  const label = labels.find((l) => l.agent_run_id === agent_run_id);
  if (!label) return 0;

  const humanLabel = label.label_value.label;

  if (results.length > 0) {
    const disagreements = results.filter(
      (result) => result.output.label !== humanLabel
    ).length;
    return disagreements / results.length;
  }

  return 0;
}

export function applyViewModeResults(
  agentRunResults: AgentRunJudgeResults[],
  labels: Label[],
  viewMode: ViewMode,
  missingLabelsSnapshot?: Set<string> | null
): AgentRunJudgeResults[] {
  const labeledAgentRunIds = new Set(labels.map((label) => label.agent_run_id));

  let filteredAgentRuns = agentRunResults;

  switch (viewMode) {
    case 'all':
      return filteredAgentRuns;

    case 'labeled_disagreement':
      filteredAgentRuns = filteredAgentRuns.filter((agentRun) =>
        labeledAgentRunIds.has(agentRun.agent_run_id)
      );
      break;

    case 'missing_labels':
      filteredAgentRuns = filteredAgentRuns.filter((agentRun) => {
        // Show runs that are either:
        // 1. Currently unlabeled, OR
        // 2. In the snapshot (were unlabeled when view was entered, may now be labeled)
        // This prevents runs from vanishing while being edited
        return (
          !labeledAgentRunIds.has(agentRun.agent_run_id) ||
          (missingLabelsSnapshot &&
            missingLabelsSnapshot.has(agentRun.agent_run_id))
        );
      });
      break;

    case 'incomplete_labels':
      filteredAgentRuns = filteredAgentRuns.filter((agentRun) => {
        const humanMissFraction = calculateHumanMissFraction(agentRun);
        return humanMissFraction > 0;
      });
      break;
  }

  let scoreFunction: (agentRun: AgentRunJudgeResults) => number;

  switch (viewMode) {
    case 'labeled_disagreement':
      scoreFunction = (agentRun) =>
        calculateJudgeLabelDisagreementScore(agentRun, labels);
      break;
    case 'missing_labels':
      scoreFunction = (agentRun) => calculateControversyScore(agentRun);
      break;
    case 'incomplete_labels':
      scoreFunction = (agentRun) => calculateHumanMissFraction(agentRun);
      break;
    default:
      return filteredAgentRuns;
  }

  const agentRunsWithScores = filteredAgentRuns.map((agentRun) => ({
    agentRun,
    score: scoreFunction(agentRun),
  }));

  agentRunsWithScores.sort((a, b) => b.score - a.score);

  return agentRunsWithScores.map((item) => item.agentRun);
}
