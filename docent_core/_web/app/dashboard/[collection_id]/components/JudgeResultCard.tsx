import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { useRouter } from 'next/navigation';
import { useAppSelector } from '@/app/store/hooks';
import { useCitationHighlight } from '@/lib/citationUtils';
import { useCitationNavigation } from '../rubric/[rubric_id]/NavigateToCitationContext';
import { useMemo } from 'react';
import { cn } from '@/lib/utils';
import { TextWithCitations } from '@/components/CitationRenderer';
import posthog from 'posthog-js';
import { AgentRunMetadata } from '@/app/components/AgentRunMetadata';
import { Citation } from '@/app/types/experimentViewerTypes';

interface JudgeResultCardProps {
  clickable: boolean;
  judgeResult: JudgeResultWithCitations;
  isActive: boolean;
}

export const JudgeResultCard = ({
  clickable,
  judgeResult,
  isActive,
}: JudgeResultCardProps) => {
  const router = useRouter();
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const { highlightCitation } = useCitationHighlight();
  const citationNav = useCitationNavigation();
  const agentRunId = judgeResult.agent_run_id;

  const handleNavigateToCitation = ({
    citation,
    newTab,
  }: {
    citation: Citation | null;
    newTab?: boolean;
  }) => {
    const url = `/dashboard/${collectionId}/rubric/${judgeResult.rubric_id}/result/${judgeResult.id}`;
    if (!isActive && clickable) {
      if (citationNav?.prepareForNavigation) {
        citationNav.prepareForNavigation(); // Clear current handler for proper timing
      }
      if (newTab) {
        window.open(url, '_blank');
      } else {
        router.push(url, { scroll: false } as any);
      }
    }
    if (citation && clickable) {
      posthog.capture('citation_clicked', {
        source: 'judge_result',
        agent_run_id: agentRunId,
        transcript_idx: citation.transcript_idx,
        block_idx: citation.block_idx,
        start_pattern: citation.start_pattern,
      });
      if (citationNav?.navigateToCitation) {
        citationNav.navigateToCitation({ citation, newTab });
      }
      highlightCitation(citation);
    }
  };

  const explanation = judgeResult.output.explanation;
  const citations = explanation.citations || [];
  const explanationText =
    explanation instanceof Object ? explanation.text : explanation;
  const otherOutput = useMemo(() => {
    const copy = { ...judgeResult.output };
    delete copy.explanation;
    return copy;
  }, [judgeResult.output]);

  return (
    <div>
      <div
        className={cn(
          'group rounded-md p-1 border text-xs leading-snug mt-1 transition-colors cursor-pointer border',
          isActive
            ? 'border-indigo-border text-primary bg-indigo-bg'
            : 'bg-secondary/30 hover:bg-indigo-bg text-primary'
        )}
        onClick={(e) => {
          e.stopPropagation();
          const firstCitation = citations.length > 0 ? citations[0] : null;

          posthog.capture('rubric_result_clicked', {
            query: judgeResult.rubric_id,
            agent_run_id: agentRunId,
          });

          handleNavigateToCitation({
            citation: firstCitation,
            newTab: e.metaKey || e.ctrlKey,
          });
        }}
      >
        <div className="flex flex-col">
          <div className="flex items-start justify-between gap-2">
            <p
              className="mb-0.5 flex-1 wrap-anywhere"
              style={{ overflowWrap: 'anywhere' }}
            >
              {explanationText ? (
                <TextWithCitations
                  text={explanationText}
                  citations={explanation.citations || []}
                  onNavigate={handleNavigateToCitation}
                />
              ) : (
                <span className="text-muted-foreground">No explanation</span>
              )}
            </p>
          </div>
        </div>
      </div>
      <div>
        <AgentRunMetadata metadata={otherOutput} />
      </div>
    </div>
  );
};
