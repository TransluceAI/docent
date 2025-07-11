'use client';

import { useMemo, useEffect, useRef } from 'react';
import { useSearchParams } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

import { useAppDispatch, useAppSelector } from '../store/hooks';

import {
  setActiveRubricId,
  clearJudgeResults,
  setEditingRubricId,
} from '../store/rubricSlice';

import { ProgressBar } from './ProgressBar';
import RubricEditor from '../dashboard/[collection_id]/components/RubricEditor';
import RubricList from '../dashboard/[collection_id]/components/RubricList';
import { JudgeResultsList } from '../dashboard/[collection_id]/components/JudgeResultsSection';
import {
  useCancelEvaluationMutation,
  useUpdateRubricMutation,
  useListenForJudgeResultsQuery,
  useStartEvaluationMutation,
} from '../api/rubricApi';
import { toast } from '@/hooks/use-toast';

const RubricArea = () => {
  const dispatch = useAppDispatch();
  const searchParams = useSearchParams();

  const [cancelEvaluation] = useCancelEvaluationMutation();
  const [updateRubric, { isLoading: isUpdatingRubric }] =
    useUpdateRubricMutation();

  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const isPollingResults = useAppSelector(
    (state) => state.rubric.isPollingResults
  );
  const activeJobId = useAppSelector((state) => state.rubric.activeJobId);
  const totalAgentRuns = useAppSelector((state) => state.rubric.totalAgentRuns);
  const judgeResultsMap = useAppSelector(
    (state) => state.rubric.judgeResultsMap
  );

  // Collect rubrics
  const rubricsMap = useAppSelector((state) => state.rubric.rubricsMap);
  const activeRubricId = useAppSelector((state) => state.rubric.activeRubricId);
  const editingRubricId = useAppSelector(
    (state) => state.rubric.editingRubricId
  );
  const activeRubric = useMemo(() => {
    if (!activeRubricId) return null;
    return rubricsMap[activeRubricId];
  }, [activeRubricId, rubricsMap]);
  const editingRubric = useMemo(() => {
    if (!editingRubricId) return null;
    return rubricsMap[editingRubricId];
  }, [editingRubricId, rubricsMap]);

  // Handle starting evaluations
  const [startEvaluation] = useStartEvaluationMutation();
  const handleEvaluate = async (rubricId: string, activateUi = true) => {
    if (!collectionId) return;

    // First start the job
    await startEvaluation({
      collectionId,
      rubricId,
    });
    if (activateUi) {
      // We set the active rubric afterward; this helps avoid a race condition
      // where we start listening before the job even exists, and thus it immediately closes.
      dispatch(setActiveRubricId(rubricId));
    }
  };

  // Handle URL-based rubric activation
  const alreadyInitiated = useRef(false);
  useEffect(() => {
    const urlRubricId = searchParams.get('activeRubricId');
    if (
      urlRubricId &&
      rubricsMap &&
      rubricsMap[urlRubricId] &&
      activeRubricId === null
    ) {
      if (alreadyInitiated.current) return;
      alreadyInitiated.current = true;
      handleEvaluate(urlRubricId);
    }
  }, [searchParams, rubricsMap, activeRubricId, dispatch]);

  // If there is an active job, listen for judge results with RTK
  useListenForJudgeResultsQuery(
    {
      collectionId: collectionId!,
      rubricId: activeRubric?.id || '',
    },
    {
      skip: !collectionId || !activeRubric || !activeJobId,
    }
  );

  const resetInterface = (cancelJob = false) => {
    dispatch(setActiveRubricId(null));
    dispatch(clearJudgeResults());
    if (cancelJob) {
      if (!collectionId || !activeJobId || !activeRubricId) return;
      cancelEvaluation({
        collectionId,
        rubricId: activeRubricId,
        jobId: activeJobId,
      });
    }
  };

  const handleSaveRubric = async (rubric: any) => {
    if (!collectionId) return;

    try {
      await updateRubric({
        collectionId,
        rubricId: rubric.id,
        rubric,
      }).unwrap();

      // Clear editing state after successful update
      dispatch(setEditingRubricId(null));
    } catch (error) {
      console.error('Failed to update rubric:', error);
      toast({
        title: 'Error',
        description: 'Failed to update rubric',
        variant: 'destructive',
      });
    }
  };

  const handleShare = async () => {
    if (!activeRubricId) return;

    try {
      const currentUrl = new URL(window.location.href);
      currentUrl.searchParams.set('activeRubricId', activeRubricId);

      await navigator.clipboard.writeText(currentUrl.toString());

      toast({
        title: 'Link copied',
        description: 'Rubric link copied to clipboard',
      });
    } catch (error) {
      console.error('Failed to copy link:', error);
      toast({
        title: 'Error',
        description: 'Failed to copy link to clipboard',
        variant: 'destructive',
      });
    }
  };

  return (
    <Card className="h-full flex overflow-y-auto flex-col flex-1 p-3 custom-scrollbar space-y-3">
      {/* Rubric Display */}
      <div className="space-y-2">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Rubric Evaluation</div>
          <div className="text-xs text-muted-foreground">
            Define evaluation criteria and rules for agent performance
          </div>
        </div>

        {/* Rubric List - show when not actively evaluating */}
        {!activeRubric && <RubricList handleEvaluate={handleEvaluate} />}

        {/* Display the active rubric but with read only */}
        {activeRubric && (
          <RubricEditor
            initRubric={activeRubric}
            onSave={() => {}}
            onCloseWithoutSave={() => {}}
            readOnly={true}
          />
        )}
        {/* Editor */}
        {editingRubric && (
          <RubricEditor
            initRubric={editingRubric}
            onSave={handleSaveRubric}
            onCloseWithoutSave={() => dispatch(setEditingRubricId(null))}
            readOnly={isPollingResults || isUpdatingRubric}
          />
        )}

        {/* Progress bar */}
        {activeRubric && isPollingResults && (
          <ProgressBar
            current={Object.keys(judgeResultsMap ?? {}).length}
            total={totalAgentRuns}
            paused={false}
          />
        )}

        {/* Action Buttons */}
        {activeRubric && (
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1 h-7 text-xs"
              onClick={handleShare}
            >
              Share
            </Button>
            {!isPollingResults && (
              <Button
                type="button"
                size="sm"
                className="gap-1 h-7 text-xs"
                onClick={() => resetInterface()}
              >
                Exit
              </Button>
            )}
            {isPollingResults && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="gap-1 h-7 text-xs"
                  onClick={() => resetInterface()}
                >
                  Run in background
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="gap-1 h-7 text-xs"
                  onClick={() => resetInterface(true)}
                >
                  Cancel
                </Button>
              </>
            )}
          </div>
        )}

        {/* Results */}
        {activeRubric && <JudgeResultsList />}
      </div>
    </Card>
  );
};

export default RubricArea;
