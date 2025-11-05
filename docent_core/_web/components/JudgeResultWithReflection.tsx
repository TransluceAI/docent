'use client';

import { useMemo } from 'react';
import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import Reflection from './JudgeResultReflection';
import JudgeResultDetail from './JudgeResultDetail';
import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { MetadataBlock } from './metadata/MetadataBlock';
import { Badge } from './ui/badge';
import { TextWithCitations } from './CitationRenderer';

function RolloutDetail({
  rollout,
  rolloutIndex,
}: {
  rollout: Record<string, any>;
  rolloutIndex: number;
}) {
  const { explanation, ...rest } = rollout;
  const explanationText =
    explanation instanceof Object ? explanation.text : explanation;

  return (
    <div>
      <div className="w-full mx-auto max-w-4xl mb-2">
        <Badge variant="secondary" className="text-xs">
          Rollout {rolloutIndex + 1}
        </Badge>
      </div>
      {explanation && (
        <div className="w-full mx-auto max-w-4xl">
          <div className="bg-indigo-bg border border-indigo-border rounded-md p-2 mt-2 text-xs text-primary leading-snug">
            <TextWithCitations
              text={explanationText}
              citations={explanation.citations || []}
            />
          </div>
          <div className="mt-2">
            <MetadataBlock metadata={rest} />
          </div>
        </div>
      )}
    </div>
  );
}
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
  const selectedResult: JudgeResultWithCitations | undefined = useMemo(() => {
    return agentRunResults.results.find((r) => r.id === selectedResultId);
  }, [agentRunResults.results, selectedResultId]);

  const rolloutIndexFromUrl = useMemo(() => {
    const index = agentRunResults.results.findIndex(
      (r) => r.id === selectedResultId
    );
    return index >= 0 ? index : 0;
  }, [agentRunResults.results, selectedResultId]);

  const isMultiRollout = agentRunResults.results.length > 1;

  const showRolloutDetail =
    rolloutIndexFromUrl !== null &&
    isMultiRollout &&
    agentRunResults.results[rolloutIndexFromUrl];

  return (
    <>
      <Reflection
        agentRunResults={agentRunResults}
        selectedResultId={selectedResultId}
        rubricId={rubricId}
        collectionId={collectionId}
        selectedRolloutIndex={rolloutIndexFromUrl}
      />
      {showRolloutDetail ? (
        <RolloutDetail
          rollout={agentRunResults.results[rolloutIndexFromUrl].output}
          rolloutIndex={rolloutIndexFromUrl}
        />
      ) : (
        <JudgeResultDetail
          judgeResult={selectedResult ?? agentRunResults.results[0]}
        />
      )}
    </>
  );
}
