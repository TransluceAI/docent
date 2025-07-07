'use client';

import React, { useEffect } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Card } from '@/components/ui/card';
import { CitationRenderer } from '@/components/CitationRenderer';
import { useAppSelector, useAppDispatch } from '@/app/store/hooks';
import { cn } from '@/lib/utils';
import { requestTranscriptDiff } from '@/app/store/diffSliceOld';
import {
  interpolateAgentBadges,
  agentBadge,
} from '@/app/components/TranscriptDiffSummary';
import { useSearchParams } from 'next/navigation';

interface DiffPanelProps {
  agentRunIds: [string, string];
  scrollToBlock: (blockIndex: number, transcriptIdx?: number) => void;
}

const DiffPanel: React.FC<DiffPanelProps> = ({
  agentRunIds,
  scrollToBlock,
}) => {
  const dispatch = useAppDispatch();
  const searchParams = useSearchParams();
  const claimId = searchParams.get('claim_id');
  const [id1, id2] = agentRunIds;
  const pairKey = `${id1}___${id2}`;
  const reversePairKey = `${id2}___${id1}`;
  const state = useAppSelector((state) => state.diff);
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const allDiffs = state.transcriptDiffsByKey;
  console.log(allDiffs);
  const transcriptDiff = useAppSelector(
    (state) => state.diff.transcriptDiffsByKey[pairKey || reversePairKey]
  );

  // Load transcript diff on mount
  useEffect(() => {
    if (!transcriptDiff) {
      dispatch(requestTranscriptDiff({ agentRun1Id: id1, agentRun2Id: id2 }));
    }
  }, [dispatch, id1, id2, transcriptDiff, collectionId]);

  // Scroll to and highlight claim when data is loaded
  useEffect(() => {
    if (!claimId || !transcriptDiff) return;

    const claimElement = document.getElementById(`claim-${claimId}`);
    if (claimElement) {
      claimElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Add a highlight effect
      claimElement.classList.add('bg-purple-200/50', 'dark:bg-purple-800/50');
      setTimeout(() => {
        claimElement.classList.remove(
          'bg-purple-200/50',
          'dark:bg-purple-800/50'
        );
      }, 2000);
    }
  }, [claimId, transcriptDiff]);

  const claims = transcriptDiff
    ? transcriptDiff.claims.map((claim) => {
        return {
          claim: claim.claim_summary,
          shared_context: claim.shared_context,
          action1: claim.agent_1_action,
          action2: claim.agent_2_action,
          evidence: claim.evidence_with_citations,
          pairKey: pairKey,
          id: claim.id,
        };
      })
    : [];

  // Get all diffs for this specific pair of agent runs
  // const relevantDiffs = useMemo(() => {
  //   if (!diffMap) return [];
  //
  //   const [id1, id2] = agentRunIds;
  //   const pairKey = `${id1}___${id2}`;
  //   const reversePairKey = `${id2}___${id1}`;
  //
  //   // Look for diff data for this pair (could be in either direction)
  //   const diffData = diffMap[pairKey] || diffMap[reversePairKey];
  //
  //   if (!diffData) return [];
  //
  //   // Create pairs of claims and evidence
  //   return diffData.claim.map((claim, idx) => ({
  //     claim,
  //     evidence: diffData.evidence[idx] || null,
  //     pairKey: diffMap[pairKey] ? pairKey : reversePairKey,
  //   }));
  // }, [diffMap, agentRunIds]);

  return (
    <Card className="h-full flex-1 p-3 flex flex-col space-y-2 min-h-0 min-w-0">
      <div className="flex items-center space-x-2">
        <span className="text-sm font-semibold text-foreground">
          <div className="flex flex-col">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Transcript Differences for Task
            </span>
            <span className="text-lg font-semibold text-foreground">
              {transcriptDiff?.title}
            </span>
          </div>
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        We found {claims.length} differences in behavior by examining the
        transcripts of the two agents.
      </p>
      {claims.length === 0 ? (
        <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
          No diffs found for this pair
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="space-y-3">
            {claims.map((diff, idx) => (
              <div
                key={idx}
                id={`claim-${diff.id}`}
                className={cn(
                  'group bg-purple-bg rounded-md p-3 text-xs text-purple-text leading-relaxed',
                  'hover:bg-purple-bg transition-colors border border-transparent hover:border-purple-border',
                  'transition-all duration-600'
                )}
              >
                <div className="mb-2">
                  {/* <span className="font-semibold text-purple-800 dark:text-purple-200">Claim:</span> */}
                  <div className="mt-1 font-semibold text-foreground">
                    {interpolateAgentBadges(diff.claim)}
                  </div>
                </div>
                {/* Shared context */}
                {diff.shared_context && (
                  <div
                    className={cn('text-xs text-muted-foreground italic mb-2')}
                  >
                    {diff.shared_context}
                  </div>
                )}
                {/* Actions side by side */}
                <div
                  className={cn(
                    'flex flex-col sm:flex-row gap-2 sm:gap-4',
                    'divide-y sm:divide-y-0 sm:divide-x divide-border mb-2'
                  )}
                >
                  <div className="flex-1 py-2 sm:py-0 sm:pr-4">
                    <div className="text-xs font-medium mb-1">
                      {agentBadge('Agent 1')}
                    </div>
                    <div className="text-sm text-foreground whitespace-pre-line">
                      {diff.action1}
                    </div>
                  </div>
                  <div className="flex-1 py-2 sm:py-0 sm:pl-4">
                    <div className="text-xs font-medium mb-1">
                      {agentBadge('Agent 2')}
                    </div>
                    <div className="text-sm text-foreground whitespace-pre-line">
                      {diff.action2}
                    </div>
                  </div>
                </div>
                {/* Evidence */}
                {diff.evidence && (
                  <div>
                    <span className="font-semibold text-foreground">
                      Evidence:
                    </span>
                    <div className="mt-1 text-foreground">
                      <CitationRenderer
                        text={diff.evidence.evidence}
                        citations={diff.evidence.citations || []}
                        onCitationClick={(citation) => {
                          scrollToBlock(
                            citation.block_idx,
                            citation.transcript_idx == null
                              ? undefined
                              : citation.transcript_idx
                          );
                        }}
                      />
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </ScrollArea>
      )}
    </Card>
  );
};

export default DiffPanel;
