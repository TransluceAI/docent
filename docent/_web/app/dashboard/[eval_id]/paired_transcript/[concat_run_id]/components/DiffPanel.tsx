'use client';

import React, { useMemo } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Card } from '@/components/ui/card';
import { useAppSelector } from '@/app/store/hooks';
import { Citation } from '@/app/types/experimentViewerTypes';

interface DiffPanelProps {
  agentRunIds: [string, string];
  scrollToBlock: (blockIndex: number, transcriptIdx?: number) => void;
}

const DiffPanel: React.FC<DiffPanelProps> = ({
  agentRunIds,
  scrollToBlock,
}) => {
  const diffMap = useAppSelector((state) => state.diff.diffMap);

  // Get all diffs for this specific pair of agent runs
  const relevantDiffs = useMemo(() => {
    if (!diffMap) return [];

    const [id1, id2] = agentRunIds;
    const pairKey = `${id1}___${id2}`;
    const reversePairKey = `${id2}___${id1}`;

    // Look for diff data for this pair (could be in either direction)
    const diffData = diffMap[pairKey] || diffMap[reversePairKey];

    if (!diffData) return [];

    // Create pairs of claims and evidence
    return diffData.claim.map((claim, idx) => ({
      claim,
      evidence: diffData.evidence[idx] || null,
      pairKey: diffMap[pairKey] ? pairKey : reversePairKey,
    }));
  }, [diffMap, agentRunIds]);

  // Helper function to render text with citations highlighted
  const renderTextWithCitations = (text: string, citations: Citation[]) => {
    if (!citations.length) {
      return text;
    }

    // Sort citations by start index to process them in order
    const sortedCitations = [...citations].sort(
      (a, b) => a.start_idx - b.start_idx
    );

    const parts: JSX.Element[] = [];
    let lastIndex = 0;

    sortedCitations.forEach((citation, i) => {
      // Add text before the citation
      if (citation.start_idx > lastIndex) {
        parts.push(
          <span key={`text-${i}`}>
            {text.slice(lastIndex, citation.start_idx)}
          </span>
        );
      }

      // Add the cited text as a clickable element
      const citedText = text.slice(citation.start_idx, citation.end_idx);
      parts.push(
        <button
          key={`citation-${i}`}
          className="px-1 bg-purple-200 text-purple-800 hover:bg-purple-400 rounded hover:text-white transition-colors font-medium text-xs"
          onClick={(e) => {
            e.stopPropagation();
            scrollToBlock(
              citation.block_idx,
              citation.transcript_idx == null
                ? undefined
                : citation.transcript_idx
            );
          }}
        >
          {citedText}
        </button>
      );

      lastIndex = citation.end_idx;
    });

    // Add any remaining text
    if (lastIndex < text.length) {
      parts.push(<span key={`text-end`}>{text.slice(lastIndex)}</span>);
    }

    return <>{parts}</>;
  };

  return (
    <Card className="h-full flex-1 p-3 flex flex-col space-y-2 min-h-0 min-w-0">
      <div className="flex items-center space-x-2">
        <div className="h-2 w-2 rounded-full bg-purple-500"></div>
        <span className="text-sm font-semibold text-purple-700">
          Diff Results
        </span>
      </div>

      {relevantDiffs.length === 0 ? (
        <div className="flex items-center justify-center h-full text-gray-500 text-sm">
          No diffs found for this pair
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="space-y-3">
            {relevantDiffs.map((diff, idx) => (
              <div
                key={idx}
                className="group bg-purple-50 rounded-md p-3 text-xs text-purple-900 leading-relaxed hover:bg-purple-100 transition-colors border border-transparent hover:border-purple-200"
              >
                {/* Claim */}
                <div className="mb-2">
                  <span className="font-semibold text-purple-800">Claim:</span>
                  <div className="mt-1 text-purple-900">{diff.claim}</div>
                </div>

                {/* Evidence */}
                {diff.evidence && (
                  <div>
                    <span className="font-semibold text-purple-800">
                      Evidence:
                    </span>
                    <div className="mt-1 text-purple-900">
                      {renderTextWithCitations(
                        diff.evidence.evidence,
                        diff.evidence.citations || []
                      )}
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
