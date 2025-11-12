'use client';

import {
  useRecomputeAgentRunReflectionMutation,
  type AgentRunJudgeResults,
  type ReflectionSummary,
  type ReflectionIssue,
} from '@/app/api/rubricApi';
import { useGetLabelsInLabelSetQuery } from '@/app/api/labelApi';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { RefreshCw } from 'lucide-react';
import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { IssueBadge } from '../app/components/IssueBadge';
import { useLabelSets } from '@/providers/use-label-sets';
import { skipToken } from '@reduxjs/toolkit/query';

interface ReflectionProps {
  agentRunResults: AgentRunJudgeResults;
  selectedResultId?: string;
  collectionId: string;
  rubricId: string;
  selectedRolloutIndex: number | null;
}

interface RolloutButtonsProps {
  indices: number[];
  selectedRolloutIndex: number | null;
  agentRunResults: AgentRunJudgeResults;
  collectionId: string;
}

function RolloutButtons({
  indices,
  selectedRolloutIndex,
  agentRunResults,
  collectionId,
}: RolloutButtonsProps) {
  const router = useRouter();

  const handleRolloutClick = (rolloutIdx: number) => {
    if (selectedRolloutIndex !== rolloutIdx) {
      const result = agentRunResults.results[rolloutIdx];
      if (result) {
        router.replace(
          `/dashboard/${collectionId}/rubric/${result.rubric_id}/agent_run/${result.agent_run_id}/result/${result.id}`,
          { scroll: false }
        );
      }
    }
  };

  return (
    <div className="flex gap-1.5 items-center flex-wrap">
      {indices.map((rolloutIdx) => (
        <Badge
          key={rolloutIdx}
          variant={selectedRolloutIndex === rolloutIdx ? 'default' : 'outline'}
          className={cn(
            'cursor-pointer transition-colors',
            selectedRolloutIndex === rolloutIdx &&
              'ring-2 ring-primary hover:ring-primary/80',
            selectedRolloutIndex !== rolloutIdx
              ? 'hover:bg-muted'
              : 'hover:bg-primary/80'
          )}
          onClick={() => handleRolloutClick(rolloutIdx)}
        >
          {rolloutIdx + 1}
        </Badge>
      ))}
    </div>
  );
}

interface SummaryItemProps {
  summary: ReflectionSummary;
  selectedRolloutIndex: number | null;
  agentRunResults: AgentRunJudgeResults;
  collectionId: string;
}

function SummaryItem({
  summary,
  selectedRolloutIndex,
  agentRunResults,
  collectionId,
}: SummaryItemProps) {
  const matchingLabel = useMemo(() => {
    const labels = summary.rollout_indices
      .map((idx) => agentRunResults.results[idx]?.output?.label)
      .filter((label): label is string => label != null);

    if (
      labels.length === 0 ||
      labels.length !== summary.rollout_indices.length
    ) {
      return null;
    }

    return labels.every((label) => label === labels[0]) ? labels[0] : null;
  }, [summary.rollout_indices, agentRunResults.results]);

  return (
    <div className="space-y-1">
      <div className="flex gap-1.5 items-center flex-wrap">
        <RolloutButtons
          indices={summary.rollout_indices}
          selectedRolloutIndex={selectedRolloutIndex}
          agentRunResults={agentRunResults}
          collectionId={collectionId}
        />
        {matchingLabel && (
          <Badge
            variant="outline"
            className="text-xs text-muted-foreground border-border"
          >
            {matchingLabel}
          </Badge>
        )}
        {summary.classification && <IssueBadge type={summary.classification} />}
      </div>
      <p className="text-xs leading-relaxed text-foreground">{summary.text}</p>
    </div>
  );
}

interface IssueItemProps {
  issue: ReflectionIssue;
  selectedRolloutIndex: number | null;
  agentRunResults: AgentRunJudgeResults;
  collectionId: string;
}

function IssueItem({
  issue,
  selectedRolloutIndex,
  agentRunResults,
  collectionId,
}: IssueItemProps) {
  return (
    <div className="space-y-1">
      <div className="flex gap-1.5 items-center flex-wrap">
        <RolloutButtons
          indices={issue.rollout_indices}
          selectedRolloutIndex={selectedRolloutIndex}
          agentRunResults={agentRunResults}
          collectionId={collectionId}
        />
        <IssueBadge type={issue.type} />
        {issue.summary && (
          <p className="text-xs leading-relaxed text-foreground">
            {issue.summary}
          </p>
        )}
      </div>
    </div>
  );
}

function getMissingRolloutIndices(
  totalResults: number,
  issues: ReflectionIssue[]
): number[] {
  const coveredIndices = new Set<number>();
  issues.forEach((issue) => {
    issue.rollout_indices.forEach((idx) => coveredIndices.add(idx));
  });

  return Array.from({ length: totalResults }, (_, i) => i).filter(
    (i) => !coveredIndices.has(i)
  );
}

export default function Reflection({
  agentRunResults,
  selectedResultId,
  rubricId,
  collectionId,
}: ReflectionProps) {
  const { activeLabelSet } = useLabelSets(rubricId);
  const activeLabelSetId = activeLabelSet?.id;
  const { data: allLabels, isLoading: isLoadingLabels } =
    useGetLabelsInLabelSetQuery(
      activeLabelSetId
        ? { collectionId, labelSetId: activeLabelSetId }
        : skipToken
    );

  const [recomputeReflection, { isLoading: isRecomputing }] =
    useRecomputeAgentRunReflectionMutation();

  const agentRunLabels = useMemo(() => {
    return allLabels?.filter(
      (label) => label.agent_run_id === agentRunResults.agent_run_id
    );
  }, [allLabels, agentRunResults.agent_run_id]);

  const shouldHide = useMemo(() => {
    return (
      !isLoadingLabels &&
      agentRunResults.results.length === 1 &&
      (!agentRunLabels || agentRunLabels.length === 0)
    );
  }, [isLoadingLabels, agentRunResults.results.length, agentRunLabels]);

  const handleRecompute = async () => {
    await recomputeReflection({
      collectionId,
      agentRunId: agentRunResults.agent_run_id,
      rubricId: agentRunResults.rubric_id,
      version: agentRunResults.rubric_version,
      labelSetId: activeLabelSetId,
    });
  };

  const reflection = agentRunResults.reflection;
  const hasSummaries = reflection?.summaries && reflection.summaries.length > 0;
  const title = reflection?.issues ? 'Issues' : 'Judge Rollouts';

  const allIndices = agentRunResults.results.map((_, i) => i);
  const missingIndices = reflection?.issues
    ? getMissingRolloutIndices(
        agentRunResults.results.length,
        reflection.issues
      )
    : [];

  const selectedRolloutIndex = useMemo(() => {
    return agentRunResults.results.findIndex((r) => r.id === selectedResultId);
  }, [agentRunResults.results, selectedResultId]);

  if (shouldHide) {
    return null;
  }

  return (
    <div className="w-full mx-auto max-w-4xl mb-2">
      <div className="border rounded-md p-3 bg-muted/30 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            {title}
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={handleRecompute}
            disabled={isRecomputing}
          >
            <RefreshCw
              className={cn('h-3 w-3', isRecomputing && 'animate-spin')}
            />
          </Button>
        </div>

        {!reflection ? (
          <>
            <RolloutButtons
              indices={allIndices}
              selectedRolloutIndex={selectedRolloutIndex}
              agentRunResults={agentRunResults}
              collectionId={collectionId}
            />
            <div className="text-xs text-muted-foreground">
              {isRecomputing
                ? 'Analyzing judge results...'
                : 'Click the refresh button to summarize results'}
            </div>
          </>
        ) : (
          <>
            {hasSummaries &&
              reflection.summaries!.map((summary, idx) => (
                <SummaryItem
                  key={idx}
                  summary={summary}
                  selectedRolloutIndex={selectedRolloutIndex}
                  agentRunResults={agentRunResults}
                  collectionId={collectionId}
                />
              ))}

            {reflection?.issues && (
              <div className="pt-1 space-y-1">
                {reflection.issues!.map((issue, idx) => (
                  <IssueItem
                    key={idx}
                    issue={issue}
                    selectedRolloutIndex={selectedRolloutIndex}
                    agentRunResults={agentRunResults}
                    collectionId={collectionId}
                  />
                ))}

                {missingIndices.length > 0 && (
                  <div className="space-y-1">
                    <div className="flex gap-1.5 items-center flex-wrap">
                      <RolloutButtons
                        indices={missingIndices}
                        selectedRolloutIndex={selectedRolloutIndex}
                        agentRunResults={agentRunResults}
                        collectionId={collectionId}
                      />
                      <Badge
                        variant="outline"
                        className="text-xs bg-muted text-muted-foreground border-border"
                      >
                        No issues found
                      </Badge>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
