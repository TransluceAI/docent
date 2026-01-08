'use client';

import { useMemo } from 'react';
import { AgentRunJudgeResults, useGetRubricQuery } from '@/app/api/rubricApi';
import Reflection from './JudgeResultReflection';
import { SchemaValueRenderer } from '@/app/dashboard/[collection_id]/components/SchemaValueRenderer';
import { Badge } from './ui/badge';

interface JudgeResultWithReflectionProps {
  agentRunResults: AgentRunJudgeResults;
  selectedResultId?: string;
  collectionId: string;
  rubricId: string;
}

export default function JudgeResultWithReflection({
  agentRunResults,
  selectedResultId,
  rubricId,
  collectionId,
}: JudgeResultWithReflectionProps) {
  const rolloutIndexFromUrl = useMemo(() => {
    const index = agentRunResults.results.findIndex(
      (r) => r.id === selectedResultId
    );
    return index >= 0 ? index : null;
  }, [agentRunResults.results, selectedResultId]);

  // Fetch rubric to get the output schema for rendering
  const { data: rubric } = useGetRubricQuery({
    collectionId,
    rubricId,
    version: agentRunResults.rubric_version,
  });

  // Determine which result to display
  const displayResult = useMemo(() => {
    if (agentRunResults.results.length === 1) {
      return { result: agentRunResults.results[0], rolloutIndex: null };
    }
    if (
      rolloutIndexFromUrl !== null &&
      agentRunResults.results[rolloutIndexFromUrl]
    ) {
      return {
        result: agentRunResults.results[rolloutIndexFromUrl],
        rolloutIndex: rolloutIndexFromUrl,
      };
    }
    return null;
  }, [agentRunResults.results, rolloutIndexFromUrl]);

  return (
    <>
      <Reflection
        agentRunResults={agentRunResults}
        selectedResultId={selectedResultId}
        rubricId={rubricId}
        collectionId={collectionId}
        selectedRolloutIndex={rolloutIndexFromUrl}
      />
      {displayResult && rubric?.output_schema && (
        <div className="w-full mx-auto max-w-4xl">
          {displayResult.rolloutIndex !== null && (
            <Badge variant="secondary" className="text-xs mb-2">
              Rollout {displayResult.rolloutIndex + 1}
            </Badge>
          )}
          <div className="bg-indigo-bg border border-indigo-border rounded-md p-2 mt-2">
            <SchemaValueRenderer
              schema={rubric.output_schema}
              values={displayResult.result.output}
              labelValues={{}}
              activeLabelSet={null}
              onSaveLabel={() => {}}
              onClearLabel={() => {}}
              showLabels={false}
              canEditLabels={false}
              renderLabelSetMenu={() => null}
            />
          </div>
        </div>
      )}
    </>
  );
}
