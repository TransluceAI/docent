import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import {
  JudgeFilter,
  Operator,
  ViewMode,
} from '@/providers/use-result-filters';
import { Label } from '@/app/api/labelApi';

function compareValues(
  itemValue: string | number,
  filterValue: string | number,
  op: Operator
): boolean {
  const itemType = typeof itemValue;
  const filterType = typeof filterValue;

  const typeKey = `${itemType}-${filterType}`;
  switch (typeKey) {
    case 'number-number':
      if (op === '==') return itemValue === filterValue;
      if (op === '!=') return itemValue !== filterValue;
      if (op === '<') return itemValue < filterValue;
      if (op === '<=') return itemValue <= filterValue;
      if (op === '>') return itemValue > filterValue;
      if (op === '>=') return itemValue >= filterValue;
      break;
    case 'string-string':
      if (op === '==') return itemValue === filterValue;
      if (op === '!=') return itemValue !== filterValue;
      if (op === 'contains')
        return (itemValue as string)
          .toLowerCase()
          .includes((filterValue as string).toLowerCase());
      break;
    default:
      return false;
  }
  return false;
}

export function applyGeneralFilters(
  result: JudgeResultWithCitations,
  filters: JudgeFilter[]
): boolean {
  return filters.every((filter) => {
    let value = result.output[filter.path];
    if (value?.text) value = value.text;
    return compareValues(value, filter.value, filter.op);
  });
}

function calculateHumanMissFraction(agentRun: AgentRunJudgeResults): number {
  const { results, reflection } = agentRun;
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
  const labels = agentRun.results.map((result) => result.output?.label);
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
  const nonModalFraction = 1 - labelCounts[mode] / agentRun.results.length;

  return nonModalFraction;
}

function calculateJudgeLabelDisagreementScore(
  agentRun: AgentRunJudgeResults,
  labels: Label[]
): number {
  const { results, agent_run_id } = agentRun;
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
  generalFilters: JudgeFilter[],
  missingLabelsSnapshot?: Set<string> | null
): AgentRunJudgeResults[] {
  const labeledAgentRunIds = new Set(labels.map((label) => label.agent_run_id));

  // Filter agent runs where at least one result passes the general filters
  let filteredAgentRuns = agentRunResults
    .map((agentRun) => ({
      ...agentRun,
      results: agentRun.results.filter((result) =>
        applyGeneralFilters(result, generalFilters)
      ),
    }))
    .filter((agentRun) => agentRun.results.length > 0);

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
