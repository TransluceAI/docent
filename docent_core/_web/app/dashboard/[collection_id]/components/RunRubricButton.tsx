import { Button } from '@/components/ui/button';
import { JobStatus, useCancelEvaluationMutation } from '@/app/api/rubricApi';
import { useRubricVersion } from '@/providers/use-rubric-version';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useEffect, useState } from 'react';

interface RunRubricButtonProps {
  collectionId: string;
  rubricId: string;
  rubricJobId: string | null;
  rubricJobStatus: JobStatus | null;
  hasUnsavedChanges: boolean;
  onClick: () => void;
}

const RunRubricButton = ({
  collectionId,
  rubricId,
  rubricJobId,
  rubricJobStatus,
  hasUnsavedChanges,
  onClick,
}: RunRubricButtonProps) => {
  const [cancelEvaluation, { isLoading: isCancellingEvaluation }] =
    useCancelEvaluationMutation();
  // Pending cancel state that can be set "optimistically" to show a cancelling state
  // Helps avoid UI flickering when cancelling a job
  const [hasPendingCancel, setHasPendingCancel] = useState(false);

  const { version, latestVersion } = useRubricVersion();
  const isLatestVersion = version === latestVersion;

  const handleStartRubricJob = () => {
    if (!isLatestVersion) return;
    onClick();
  };

  const handleCancelRubricJob = async () => {
    if (!rubricJobId) return;
    setHasPendingCancel(true);
    await cancelEvaluation({
      collectionId,
      rubricId,
      jobId: rubricJobId,
    }).unwrap();
  };

  const isButtonDisabled = hasUnsavedChanges || !isLatestVersion;
  const isJobCancelling = rubricJobStatus === 'cancelling';
  const showCancellingState =
    isCancellingEvaluation || hasPendingCancel || isJobCancelling;

  useEffect(() => {
    if (!rubricJobId || isJobCancelling) {
      setHasPendingCancel(false);
    }
  }, [rubricJobId, isJobCancelling]);

  if (showCancellingState) {
    // If we're cancelling, show a disabled button
    return (
      <Button type="button" size="sm" disabled={true}>
        Cancelling...
      </Button>
    );
  } else if (rubricJobId) {
    // If there's an active job but no cancelling state, show the stop button
    return (
      <Button type="button" size="sm" onClick={handleCancelRubricJob}>
        Stop rubric
      </Button>
    );
  } else {
    // Otherwise, show the run button
    // But if the button is disabled, show a tooltip

    const RunButton = () => (
      <Button
        type="button"
        size="sm"
        disabled={isButtonDisabled}
        onClick={handleStartRubricJob}
      >
        Run rubric
      </Button>
    );

    if (isButtonDisabled) {
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <RunButton />
          </TooltipTrigger>
          <TooltipContent side="bottom">
            Switch to the latest version to run.
          </TooltipContent>
        </Tooltip>
      );
    } else {
      return <RunButton />;
    }
  }
};

export default RunRubricButton;
