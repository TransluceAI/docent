import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  useStartEvaluationMutation,
  useCancelEvaluationMutation,
} from '@/app/api/rubricApi';
import { ChevronDown } from 'lucide-react';
import { useRubricVersion } from '@/providers/use-rubric-version';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface RunRubricButtonProps {
  collectionId: string;
  rubricId: string;
  rubricJobId: string | null;
  setShowOnlyLabeled: (showOnlyLabeled: boolean) => void;
  hasUnsavedChanges: boolean;
}

const RunRubricButton = ({
  collectionId,
  rubricId,
  rubricJobId,
  setShowOnlyLabeled,
  hasUnsavedChanges,
}: RunRubricButtonProps) => {
  const [startEvaluation, { isLoading: isStartingEvaluation }] =
    useStartEvaluationMutation();
  const [cancelEvaluation, { isLoading: isCancellingEvaluation }] =
    useCancelEvaluationMutation();

  const [runMode, setRunMode] = useState<'all' | 'labeled'>('all');
  const { version, latestVersion } = useRubricVersion();
  const isLatestVersion = version === latestVersion;

  const handleStartRubricJob = async () => {
    if (!isLatestVersion) return;
    await startEvaluation({
      collectionId,
      rubricId,
      only_run_on_labeled_runs: runMode === 'labeled',
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
        className="gap-1 h-7 text-xs rounded-r-none border-r-0"
        disabled={isButtonDisabled}
        onClick={handleStartRubricJob}
      >
        {isStartingEvaluation
          ? 'Starting rubric...'
          : runMode === 'labeled'
            ? 'Run over labels'
            : 'Run rubric'}
      </Button>
    );
  };

  return (
    <>
      {!rubricJobId && (
        <div className="flex flex-row">
          {isButtonDisabled ? (
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
          ) : (
            <RunButton />
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="sm"
                className="h-7 w-7 px-1 rounded-l-none"
                disabled={isButtonDisabled}
              >
                <ChevronDown className="h-3 w-3 text-primary-foreground" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem
                onClick={() => setRunMode('all')}
                className="text-xs"
              >
                <div className="flex flex-col">
                  <span className={runMode === 'all' ? 'font-bold' : ''}>
                    Run rubric
                  </span>
                  <span className="text-muted-foreground text-[11px]">
                    Run a quick search across all data
                  </span>
                </div>
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  setRunMode('labeled');
                  setShowOnlyLabeled(true);
                }}
                className="text-xs"
              >
                <div className="flex flex-col">
                  <span className={runMode === 'labeled' ? 'font-bold' : ''}>
                    Run over labels
                  </span>
                  <span className="text-muted-foreground text-[11px]">
                    Run a rubric over labeled agent runs
                  </span>
                </div>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}
      {rubricJobId && (
        <Button
          type="button"
          size="sm"
          className="gap-1 h-7 text-xs"
          disabled={isCancellingEvaluation}
          onClick={handleCancelRubricJob}
        >
          {isCancellingEvaluation ? 'Stopping rubric...' : 'Stop rubric'}
        </Button>
      )}
    </>
  );
};

export default RunRubricButton;
