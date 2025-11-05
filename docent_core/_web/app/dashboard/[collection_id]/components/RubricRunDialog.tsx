import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Loader2 } from 'lucide-react';
import { useState } from 'react';
import { useStartEvaluationMutation } from '@/app/api/rubricApi';
import { useGetUsageSummaryQuery } from '@/app/api/settingsApi';
import { useLabelSets } from '@/providers/use-label-sets';

interface RunRubricDialogProps {
  isOpen: boolean;
  onClose: () => void;
  collectionId: string;
  rubricId: string;
}

export default function RunRubricDialog({
  isOpen,
  onClose,
  collectionId,
  rubricId,
}: RunRubricDialogProps) {
  const [runMode, setRunMode] = useState<'all' | 'first-n'>('first-n');
  const [maxResults, setMaxResults] = useState<string>('10');
  const [rolloutsPerInput, setRolloutsPerInput] = useState<string>('1');
  const [startEvaluation, { isLoading: isStarting }] =
    useStartEvaluationMutation();
  const { data: usageSummary } = useGetUsageSummaryQuery();
  const { activeLabelSet } = useLabelSets(rubricId);
  const handleRun = async () => {
    const maxResultsNum =
      runMode === 'all'
        ? null
        : maxResults !== ''
          ? parseInt(maxResults, 10)
          : null;
    const rolloutsNum =
      rolloutsPerInput !== '' ? parseInt(rolloutsPerInput, 10) : 1;

    await startEvaluation({
      collectionId,
      rubricId,
      max_agent_runs: maxResultsNum,
      n_rollouts_per_input: rolloutsNum,
      label_set_id: activeLabelSet?.id,
    });
    onClose();
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Run Rubric Configuration</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Number of runs */}
          <div className="space-y-2">
            <Label>Number of runs</Label>
            <RadioGroup
              value={runMode}
              onValueChange={(value) => setRunMode(value as 'all' | 'first-n')}
            >
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="all" id="all" />
                <Label htmlFor="all" className="font-normal">
                  All
                </Label>
              </div>
              <div className="space-y-1">
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="first-n" id="first-n" />
                  <Label htmlFor="first-n" className="font-normal">
                    First
                  </Label>
                  <Input
                    id="max-results"
                    type="number"
                    min="1"
                    placeholder="10"
                    value={maxResults}
                    onChange={(e) => setMaxResults(e.target.value)}
                    disabled={runMode !== 'first-n'}
                    className="h-8 w-24"
                  />
                </div>
                <p className="text-xs text-muted-foreground ml-6">
                  Labeled runs are evaluated first. Then, runs are sorted by
                  UUID.
                </p>
              </div>
            </RadioGroup>
          </div>

          {/* Rollouts per input */}
          <div className="space-y-2">
            <Label htmlFor="rollouts-per-input">Rollouts per agent run</Label>
            <Input
              id="rollouts-per-input"
              type="number"
              min="1"
              max="10"
              placeholder="1"
              value={rolloutsPerInput}
              onChange={(e) => setRolloutsPerInput(e.target.value)}
              className="h-8"
            />
            {usageSummary?.free?.has_cap && (
              <p className="text-xs text-muted-foreground">
                Generating multiple rollouts per agent run consumes usage limits
                faster.
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <div className="flex space-x-2">
            <Button onClick={handleRun} disabled={isStarting}>
              {isStarting && (
                <Loader2
                  size={16}
                  className="animate-spin text-muted-foreground mr-2"
                />
              )}
              Run rubric
            </Button>
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
