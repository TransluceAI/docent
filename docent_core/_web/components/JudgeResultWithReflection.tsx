'use client';

import { useMemo } from 'react';
import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import Reflection from './JudgeResultReflection';
import JudgeResultDetail from './JudgeResultDetail';
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
            <MetadataBlock metadata={rest} showSearchControls={false} />
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
  const rolloutIndexFromUrl = useMemo(() => {
    const index = agentRunResults.results.findIndex(
      (r) => r.id === selectedResultId
    );
    return index >= 0 ? index : null;
  }, [agentRunResults.results, selectedResultId]);

  let detailComponent: React.ReactNode = null;
  if (agentRunResults.results.length === 1) {
    detailComponent = (
      <JudgeResultDetail judgeResult={agentRunResults.results[0]} />
    );
  } else if (
    rolloutIndexFromUrl !== null &&
    agentRunResults.results[rolloutIndexFromUrl]
  ) {
    detailComponent = (
      <RolloutDetail
        rollout={agentRunResults.results[rolloutIndexFromUrl].output}
        rolloutIndex={rolloutIndexFromUrl}
      />
    );
  }

  return (
    <>
      <Reflection
        agentRunResults={agentRunResults}
        selectedResultId={selectedResultId}
        rubricId={rubricId}
        collectionId={collectionId}
        selectedRolloutIndex={rolloutIndexFromUrl}
      />
      {detailComponent}
    </>
  );
}
