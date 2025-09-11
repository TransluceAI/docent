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

interface RunRubricButtonProps {
  collectionId: string;
  rubricId: string;
  activeRubricJobId?: string;
  setShowOnlyLabeled: (showOnlyLabeled: boolean) => void;
  hasUnsavedChanges: boolean;
}

const RunRubricButton = ({
  collectionId,
  rubricId,
  activeRubricJobId,
  setShowOnlyLabeled,
  hasUnsavedChanges,
}: RunRubricButtonProps) => {
  const [startEvaluation, { isLoading: isStartingEvaluation }] =
    useStartEvaluationMutation();
  const [cancelEvaluation, { isLoading: isCancellingEvaluation }] =
    useCancelEvaluationMutation();

  const [runMode, setRunMode] = useState<'all' | 'labeled'>('all');

  const handleStartRubricJob = async () => {
    await startEvaluation({
      collectionId,
      rubricId,
      only_run_on_labeled_runs: runMode === 'labeled',
    });
  };

  const handleCancelRubricJob = async () => {
    if (!activeRubricJobId) return;
    await cancelEvaluation({
      collectionId,
      rubricId,
      jobId: activeRubricJobId,
    });
  };

  return (
    <>
      {!activeRubricJobId && (
        <div className="flex flex-row">
          <Button
            type="button"
            size="sm"
            className="gap-1 h-7 text-xs rounded-r-none border-r-0"
            disabled={isStartingEvaluation || hasUnsavedChanges}
            onClick={handleStartRubricJob}
          >
            {isStartingEvaluation
              ? 'Starting rubric...'
              : runMode === 'labeled'
                ? 'Run over labels'
                : 'Run rubric'}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="sm"
                className="h-7 w-7 px-1 rounded-l-none"
                disabled={isStartingEvaluation || hasUnsavedChanges}
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
      {activeRubricJobId && (
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
