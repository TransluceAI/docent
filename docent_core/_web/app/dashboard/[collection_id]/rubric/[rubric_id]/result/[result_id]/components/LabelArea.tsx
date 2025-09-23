import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import {
  useGetRubricQuery,
  useGetJudgeRunLabelQuery,
} from '@/app/api/rubricApi';
import LabelForm from './LabelForm';
import { useRubricVersion } from '@/providers/use-rubric-version';

interface LabelAreaProps {
  rubricId: string;
  result: JudgeResultWithCitations;
  collectionId: string;
}

function LabelArea({ result, collectionId, rubricId }: LabelAreaProps) {
  // Get the remote rubric
  const { latestVersion } = useRubricVersion();
  const { data: currentViewedRubric } = useGetRubricQuery({
    collectionId: collectionId,
    rubricId: rubricId,
    version: latestVersion,
  });

  const { data: resultRubric } = useGetRubricQuery({
    collectionId: collectionId,
    rubricId: rubricId,
    version: result.rubric_version,
  });

  const { data: judgeRunLabel, isSuccess: isRunLabelSuccess } =
    useGetJudgeRunLabelQuery({
      collectionId: collectionId,
      rubricId: rubricId,
      agentRunId: result.agent_run_id,
    });

  // Initial state is the run label if it exists, otherwise the result output
  const initialState =
    judgeRunLabel && isRunLabelSuccess ? judgeRunLabel.label : result.output;

  // Make sure that the label area is displaying the latest schema form
  const isOutdated =
    JSON.stringify(resultRubric?.output_schema) !==
    JSON.stringify(currentViewedRubric?.output_schema);

  if (!currentViewedRubric?.output_schema) {
    return <span>Could not load rubric output schema.</span>;
  }

  return (
    <div className="h-full flex flex-col">
      {/* Scrollable content including header */}
      <div className="flex-1 overflow-y-auto px-0.5 min-h-0">
        <div className="space-y-1 flex flex-col pb-4">
          <div className="text-sm font-semibold">Label Editor</div>
          <div className="text-xs text-muted-foreground">
            Fields reflect the latest output schema for the rubric.
          </div>
        </div>

        {isOutdated && (
          <div className="text-xs text-muted-foreground h-[70%] flex text-center items-center p-3 justify-center">
            This label uses the v{result.rubric_version} rubric schema which is
            different from the latest v{currentViewedRubric.version} rubric
            schema. Please select a result with an updated schema.
          </div>
        )}

        {isRunLabelSuccess && !isOutdated && (
          <LabelForm
            key={result.id}
            schema={currentViewedRubric.output_schema}
            initialState={initialState}
            judgeOutput={result.output}
            collectionId={collectionId}
            rubricId={rubricId}
            judgeRunLabel={judgeRunLabel}
            agentRunId={result.agent_run_id}
          />
        )}
      </div>
    </div>
  );
}

export default LabelArea;
