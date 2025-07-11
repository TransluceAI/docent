'use client';
import { navToAgentRun } from '@/lib/nav';
import { useRouter } from 'next/navigation';
import { useAppSelector, useAppDispatch } from '@/app/store/hooks';
import { renderTextWithCitations } from '@/lib/renderCitations';
import { openAgentRunInDashboard } from '@/app/store/transcriptSlice';
import { cn } from '@/lib/utils';
import { JudgeResultWithCitations } from '@/app/store/rubricSlice';

interface JudgeResultsListProps {
  usePreview?: boolean; // Whether to use the agent run preview
}

export const JudgeResultsList = ({
  usePreview = true,
}: JudgeResultsListProps) => {
  const judgeResultsMap = useAppSelector(
    (state) => state.rubric.judgeResultsMap
  );
  if (!judgeResultsMap) return null;

  return (
    <div
      className={cn(
        'overflow-y-auto space-y-2 custom-scrollbar transition-all duration-200'
      )}
    >
      {Object.entries(judgeResultsMap).map(([agentRunId, results]) => {
        if (results.every((r) => r.value === null)) return null;
        return (
          <div
            key={agentRunId}
            className="space-y-1 border-b border-dashed pb-2 relative last:border-b-0"
          >
            {/* Search results for this agent run */}
            <div className="space-y-1">
              {results.map((judgeResult, idx) => (
                <JudgeResultCard
                  key={`${agentRunId}-${idx}`}
                  judgeResult={judgeResult}
                  usePreview={usePreview}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
};

interface JudgeResultCardProps {
  judgeResult: JudgeResultWithCitations;
  usePreview: boolean;
}

export const JudgeResultCard = ({
  judgeResult,
  usePreview,
}: JudgeResultCardProps) => {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const collectionId = useAppSelector((state) => state.collection.collectionId);

  const resultText = judgeResult.value;
  if (!resultText) {
    return null;
  }
  const agentRunId = judgeResult.agent_run_id;
  const citations = judgeResult.citations || [];

  return (
    <div
      className="group bg-indigo-bg rounded-md p-1 text-xs text-primary leading-snug mt-1 hover:border-indigo-border transition-colors cursor-pointer border border-transparent"
      onMouseDown={(e) => {
        e.stopPropagation();
        const firstCitation = citations.length > 0 ? citations[0] : null;

        if (e.metaKey || e.ctrlKey || !usePreview) {
          // Open in new tab - use original navigation
          navToAgentRun(
            router,
            window,
            agentRunId,
            firstCitation?.transcript_idx ?? undefined,
            firstCitation?.block_idx,
            collectionId,
            judgeResult.rubric_id,
            false
          );
        } else if (e.button === 0 && usePreview) {
          // Open in dashboard - use new mechanism
          dispatch(
            openAgentRunInDashboard({
              agentRunId,
              blockIdx: firstCitation?.block_idx,
              transcriptIdx: firstCitation?.transcript_idx ?? undefined,
            })
          );
        }
      }}
    >
      <div className="flex flex-col">
        <div className="flex items-start justify-between gap-2">
          <p className="mb-0.5 flex-1">
            {renderTextWithCitations(
              resultText,
              citations,
              agentRunId,
              router,
              window,
              dispatch,
              judgeResult.rubric_id,
              collectionId
            )}
          </p>
        </div>
      </div>
    </div>
  );
};
