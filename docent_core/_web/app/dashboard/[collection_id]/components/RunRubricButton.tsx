import { Button } from '@/components/ui/button';
import {
  useStartEvaluationMutation,
  useCancelEvaluationMutation,
} from '@/app/api/rubricApi';
import { useRubricVersion } from '@/providers/use-rubric-version';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useLabelSets } from '@/providers/use-label-sets';

interface RunRubricButtonProps {
  collectionId: string;
  rubricId: string;
  rubricJobId: string | null;
  hasUnsavedChanges: boolean;
}

const RunRubricButton = ({
  collectionId,
  rubricId,
  rubricJobId,
  hasUnsavedChanges,
}: RunRubricButtonProps) => {
  const { activeLabelSet } = useLabelSets();
  const [startEvaluation, { isLoading: isStartingEvaluation }] =
    useStartEvaluationMutation();
  const [cancelEvaluation, { isLoading: isCancellingEvaluation }] =
    useCancelEvaluationMutation();

  const { version, latestVersion } = useRubricVersion();
  const isLatestVersion = version === latestVersion;

  const handleStartRubricJob = async () => {
    if (!isLatestVersion) return;
    await startEvaluation({
      collectionId,
      rubricId,
      label_set_id: activeLabelSet?.id ?? null,
    });
  };

  const handleCancelRubricJob = async () => {
    if (!rubricJobId) return;
    await cancelEvaluation({
      collectionId,
      rubricId,
      jobId: rubricJobId,
    });
  };

  const isButtonDisabled =
    isStartingEvaluation || hasUnsavedChanges || !isLatestVersion;

  const RunButton = () => {
    return (
      <Button
        type="button"
        size="sm"
        className="gap-1 h-7 text-xs rounded-md"
        disabled={isButtonDisabled}
        onClick={handleStartRubricJob}
      >
        {isStartingEvaluation ? 'Starting rubric...' : 'Run rubric'}
      </Button>
    );
  };

  if (rubricJobId) {
    return (
      <Button
        type="button"
        size="sm"
        className="gap-1 h-7 text-xs"
        disabled={isCancellingEvaluation}
        onClick={handleCancelRubricJob}
      >
        {isCancellingEvaluation ? 'Stopping rubric...' : 'Stop rubric'}
      </Button>
    );
  }

  if (isButtonDisabled) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <div>
            <RunButton />
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          <p>Switch to the latest version to run.</p>
        </TooltipContent>
      </Tooltip>
    );
  }

  return <RunButton />;
};

export default RunRubricButton;
