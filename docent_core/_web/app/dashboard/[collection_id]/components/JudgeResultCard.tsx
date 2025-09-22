import {
  JudgeRunLabel,
  JudgeResultWithCitations,
} from '@/app/store/rubricSlice';
import { cn } from '@/lib/utils';
import { TextWithCitations } from '@/components/CitationRenderer';
import posthog from 'posthog-js';
import { Tag, X } from 'lucide-react';
import { useParams, usePathname, useRouter } from 'next/navigation';
import {
  useDeleteJudgeRunLabelMutation,
  useUpdateJudgeRunLabelMutation,
} from '@/app/api/rubricApi';
import { Citation } from '@/app/types/experimentViewerTypes';
import {
  useCitationNavigation,
  CitationNavigationContext,
} from '@/app/dashboard/[collection_id]/rubric/[rubric_id]/NavigateToCitationContext';
import React from 'react';
import { useRefinementTab } from '@/providers/use-refinement-tab';

interface JudgeResultCardProps {
  judgeResult: JudgeResultWithCitations;
  judgeRunLabel?: JudgeRunLabel;
  navToTranscriptOnClick?: boolean;
  active?: boolean;
}

export const JudgeResultCard = ({
  judgeResult,
  judgeRunLabel,
  navToTranscriptOnClick = true,
  active = false,
}: JudgeResultCardProps) => {
  const router = useRouter();
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();
  const agentRunId = judgeResult.agent_run_id;

  const pathname = usePathname();
  const citationNav = useCitationNavigation();

  const { setActiveTab } = useRefinementTab();
  const [updateJudgeRunLabel] = useUpdateJudgeRunLabelMutation();
  const [deleteJudgeRunLabel] = useDeleteJudgeRunLabelMutation();

  const clearLabelField = (key: string) => {
    // Clear the label if there is only one remaining field
    if (Object.keys(judgeRunLabel?.label || {}).length <= 1) {
      deleteJudgeRunLabel({
        collectionId: collectionId,
        rubricId: judgeResult.rubric_id,
        agentRunId: judgeResult.agent_run_id,
      });
    } else {
      const newLabel = { ...judgeRunLabel?.label };
      delete newLabel[key];

      updateJudgeRunLabel({
        collectionId: collectionId,
        rubricId: judgeResult.rubric_id,
        agentRunId: judgeResult.agent_run_id,
        label: newLabel,
      });
    }
  };

  const navigateToCitation = React.useCallback(
    ({ citation }: { citation: Citation }) => {
      const url = `/dashboard/${collectionId}/rubric/${judgeResult.rubric_id}/result/${judgeResult.id}`;
      const isOnTargetPage = pathname === url;

      if (!isOnTargetPage) {
        citationNav?.prepareForNavigation?.();
        router.push(url, { scroll: false } as any);
      }

      citationNav?.navigateToCitation?.({
        citation,
        source: 'judge_result',
      });
    },
    [
      citationNav,
      collectionId,
      judgeResult.id,
      judgeResult.rubric_id,
      pathname,
      router,
    ]
  );

  const value = React.useMemo(
    () => ({
      registerHandler: citationNav?.registerHandler ?? (() => {}),
      navigateToCitation,
      prepareForNavigation: citationNav?.prepareForNavigation ?? (() => {}),
    }),
    [citationNav, navigateToCitation]
  );

  if (Object.keys(judgeResult.output).length === 0) {
    return <span className="text-muted-foreground italic">Empty</span>;
  }

  return (
    <CitationNavigationContext.Provider value={value}>
      <div className="flex gap-2 group cursor-pointer">
        <div
          className={cn(
            'self-stretch w-[2.5px] rounded-full flex-shrink-0 my-0.5',
            'bg-border group-hover:bg-indigo-border transition-colors duration-200'
          )}
        />
        <div
          className="flex-1 text-xs space-y-2"
          onClick={(e) => {
            if (!navToTranscriptOnClick) return;
            e.stopPropagation();

            // Get the first entry with citations
            const entryWithCitations = Object.entries(judgeResult.output).find(
              ([key, value]) => value.citations
            );
            const firstCitation =
              entryWithCitations?.[1]?.citations?.[0] || null;

            // Navigate to the first citation
            if (firstCitation) {
              posthog.capture('rubric_result_clicked', {
                query: judgeResult.rubric_id,
                agent_run_id: agentRunId,
              });

              navigateToCitation({ citation: firstCitation });
            } else {
              router.push(
                `/dashboard/${collectionId}/rubric/${judgeResult.rubric_id}/result/${judgeResult.id}`
              );
            }

            setActiveTab('analyze');
          }}
        >
          <div className="space-y-1.5">
            {Object.entries(judgeResult.output).map(([key, value]) => (
              <FieldWithLabel
                key={key}
                fieldName={key}
                judgeResultValue={value}
                labeledValue={judgeRunLabel?.label?.[key]}
                clearLabelField={clearLabelField}
              />
            ))}
          </div>
        </div>
      </div>
    </CitationNavigationContext.Provider>
  );
};

interface FieldWithLabelProps {
  fieldName: string;
  judgeResultValue: any;
  labeledValue?: any;
  clearLabelField?: (key: string) => void;
}

const FieldWithLabel = ({
  fieldName,
  judgeResultValue,
  labeledValue,
  clearLabelField,
}: FieldWithLabelProps) => {
  const labelIsDifferent = labeledValue && labeledValue !== judgeResultValue;

  const judgeResultHasCitation = judgeResultValue.citations !== undefined;
  // Check if its an object (citation object) and not null (empty object)
  const labeledValueHasCitation =
    typeof labeledValue === 'object' && labeledValue !== null;
  const resolvedJudgeResultValue = judgeResultHasCitation
    ? judgeResultValue.text
    : String(judgeResultValue);

  const resolvedLabeledValue =
    labeledValue && labeledValueHasCitation
      ? labeledValue.text
      : String(labeledValue);

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex-1 items-start">
        <span className="font-semibold shrink-0">{fieldName}: </span>
        {judgeResultHasCitation ? (
          <TextWithCitations
            text={resolvedJudgeResultValue}
            citations={judgeResultValue.citations || []}
          />
        ) : (
          <span className={cn(labelIsDifferent && 'line-through opacity-50')}>
            {resolvedJudgeResultValue || (
              <span className="text-muted-foreground italic">Empty</span>
            )}
          </span>
        )}
      </div>

      {labeledValue !== undefined && (
        <Label
          fieldName={fieldName}
          labeledValue={resolvedLabeledValue}
          clearLabelField={clearLabelField}
        />
      )}
    </div>
  );
};

interface LabelProps {
  fieldName: string;
  labeledValue?: any;
  clearLabelField?: (key: string) => void;
}

const Label = ({ fieldName, labeledValue, clearLabelField }: LabelProps) => {
  return (
    <div className="flex w-fit px-1.5 py-0.5 cursor-default border relative bg-indigo-bg border-indigo-border rounded group/label">
      <div className="flex items-start gap-1">
        <Tag className="size-3 mt-0.5 flex-shrink-0 group-hover/label:hidden text-indigo-text" />
        <X
          className="size-3 mt-0.5 flex-shrink-0 group-hover/label:inline-flex hidden text-indigo-text cursor-pointer"
          onClick={() => clearLabelField?.(fieldName)}
        />
        <span className="text-primary text-xs">{labeledValue}</span>
      </div>
    </div>
  );
};
