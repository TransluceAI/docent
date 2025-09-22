import { TextWithCitations } from './CitationRenderer';
import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { MetadataBlock } from '@/components/metadata/MetadataBlock';

export default function JudgeResultDetail({
  judgeResult,
}: {
  judgeResult: JudgeResultWithCitations;
}) {
  const { explanation, ...rest } = judgeResult.output;
  const explanationText =
    explanation instanceof Object ? explanation.text : explanation;

  return (
    <div>
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
