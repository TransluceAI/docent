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
import { useState, useMemo } from 'react';
import { useSelector } from 'react-redux';
import { useGetAgentRunMetadataFieldsQuery } from '@/app/api/collectionApi';
import { FilterControls } from '@/app/components/FilterControls';
import { FilterChips } from '@/app/components/FilterChips';
import { ComplexFilter } from '@/app/types/collectionTypes';
import {
  useStartEvaluationMutation,
  useEstimateCostQuery,
  rubricApi,
} from '@/app/api/rubricApi';
import { useLabelSets } from '@/providers/use-label-sets';
import { useDebounce } from '@/hooks/use-debounce';

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
  const [runMode, setRunMode] = useState<'all' | 'first-n'>('all');
  const [maxResults, setMaxResults] = useState<string>('10');
  const [rolloutsPerInput, setRolloutsPerInput] = useState<string>('1');
  const [startEvaluation, { isLoading: isStarting }] =
    useStartEvaluationMutation();
  const { activeLabelSet } = useLabelSets(rubricId);

  const [filter, setFilter] = useState<ComplexFilter | null>(null);

  const { data: metadataFieldsData } = useGetAgentRunMetadataFieldsQuery(
    collectionId,
    {
      skip: !collectionId,
    }
  );

  const costEstimateParams = useMemo(
    () => ({
      collectionId,
      rubricId,
      max_agent_runs:
        runMode === 'all'
          ? null
          : maxResults !== ''
            ? parseInt(maxResults, 10)
            : null,
      n_rollouts_per_input:
        rolloutsPerInput !== '' ? parseInt(rolloutsPerInput, 10) : 1,
      label_set_id: activeLabelSet?.id,
      filter,
    }),
    [
      collectionId,
      rubricId,
      runMode,
      maxResults,
      rolloutsPerInput,
      activeLabelSet?.id,
      filter,
    ]
  );

  const debouncedParams = useDebounce(costEstimateParams, 1000);

  const selectCachedEstimate = useMemo(
    () => rubricApi.endpoints.estimateCost.select(costEstimateParams),
    [costEstimateParams]
  );
  const cachedResult = useSelector(selectCachedEstimate);
  const { isFetching } = useEstimateCostQuery(debouncedParams, {
    skip: !isOpen,
  });

  const isDebouncing =
    JSON.stringify(costEstimateParams) !== JSON.stringify(debouncedParams);
  const costEstimate = cachedResult?.data;
  const isCostLoading = !costEstimate && (isDebouncing || isFetching);

  // Backend doesn't support filtering on rubric outputs
  const agentRunMetadataFields = (metadataFieldsData?.fields || []).filter(
    (field) => !field.name.startsWith('rubric.')
  );

  const handleRun = async () => {
    await startEvaluation(costEstimateParams);
    onClose();
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Run Rubric Configuration</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Filter */}
          <div className="space-y-2">
            <Label>Filter agent runs</Label>
            <div className="border rounded-md p-2 space-y-2">
              <FilterControls
                filters={filter}
                onFiltersChange={setFilter}
                metadataFields={agentRunMetadataFields}
                collectionId={collectionId}
                showStepFilter={false}
              />
              <FilterChips
                filters={filter}
                onFiltersChange={setFilter}
                allowToggle={false}
              />
            </div>
          </div>

          {/* Number of runs */}
          <div className="space-y-2">
            <Label>Number of agent runs</Label>
            <RadioGroup
              value={runMode}
              onValueChange={(value) => {
                setRunMode(value as 'all' | 'first-n');
                if (value === 'first-n' && maxResults === '') {
                  setMaxResults('10');
                }
              }}
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
                    onChange={(e) => {
                      const value = e.target.value;
                      setMaxResults(value);
                      setRunMode(value === '' ? 'all' : 'first-n');
                    }}
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
          </div>

          {/* Cost estimate */}
          <div className="rounded-md bg-muted/50 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Estimated cost</span>
              <span className="text-sm font-semibold">
                {isCostLoading || !costEstimate
                  ? '—'
                  : costEstimate.fraction_of_daily_limit != null
                    ? `${(costEstimate.fraction_of_daily_limit * 100).toFixed(1)}% of daily limit`
                    : `$${(costEstimate.cost_cents / 100).toFixed(2)}`}
              </span>
            </div>
            <div className="text-xs text-muted-foreground">
              {isCostLoading || !costEstimate
                ? '—'
                : costEstimate.rollouts_needed}{' '}
              new rollouts needed
            </div>
          </div>
        </div>

        <DialogFooter>
          <div className="flex space-x-2">
            <Button onClick={handleRun} disabled={isStarting}>
              {isStarting && (
                <Loader2
                  size={16}
                  className="animate-spin text-muted-foreground mr-1"
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
