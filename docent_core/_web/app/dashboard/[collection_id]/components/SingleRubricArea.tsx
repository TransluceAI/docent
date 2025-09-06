'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Textarea } from '@/components/ui/textarea';

import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

import { JudgeResultWithCitations, Rubric } from '../../../store/rubricSlice';

import { ProgressBar } from '../../../components/ProgressBar';
import { Loader2 } from 'lucide-react';
import RubricEditor from './RubricEditor';
import { JudgeResultsList } from './JudgeResultsSection';
import {
  useCancelEvaluationMutation,
  useUpdateRubricMutation,
  useStartEvaluationMutation,
  RubricCentroid,
  useGetRubricRunStateQuery,
  useStartClusteringJobMutation,
  useGetClusteringStateQuery,
  useCancelClusteringJobMutation,
  useClearClustersMutation,
  useGetRubricQuery,
} from '../../../api/rubricApi';
import { toast } from '@/hooks/use-toast';
import { NavigateToCitation } from '@/components/CitationRenderer';
import { useCreateOrGetRefinementSessionMutation } from '@/app/api/refinementApi';

interface SingleRubricAreaProps {
  rubricId: string;
  selectedResultId?: string;
  onNavigateToCitation?: NavigateToCitation;
}

export default function SingleRubricArea({
  rubricId,
  selectedResultId,
}: SingleRubricAreaProps) {
  const params = useParams();
  const collectionId = params.collection_id as string;

  const [cancelEvaluation, { isLoading: isCancellingEvaluation }] =
    useCancelEvaluationMutation();
  const [updateRubric] = useUpdateRubricMutation();
  const hasWritePermission = useHasCollectionWritePermission();

  // Unsaved changes from the editor
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  /**
   * Rubric jobs
   */

  const [shouldPollRubricRunState, setShouldPollRubricRunState] =
    useState(false);
  const { data: rubricRunState, isLoading: isLoadingRubricRunState } =
    useGetRubricRunStateQuery(
      {
        collectionId,
        rubricId,
      },
      {
        pollingInterval: shouldPollRubricRunState ? 1000 : 0,
      }
    );
  // Job state
  const activeRubricJobId = rubricRunState?.job_id ?? null;
  useEffect(() => {
    setShouldPollRubricRunState(rubricRunState?.job_id !== null);
  }, [rubricRunState?.job_id]);
  // Parse out results
  const judgeResultsList = rubricRunState?.results;
  const judgeResultsMap =
    judgeResultsList?.reduce(
      (acc, result) => {
        acc[result.id] = result;
        return acc;
      },
      {} as Record<string, JudgeResultWithCitations>
    ) ?? {};
  const totalAgentRuns = rubricRunState?.total_agent_runs ?? null;

  // Rubric job lifecyles
  const [startEvaluation, { isLoading: isStartingEvaluation }] =
    useStartEvaluationMutation();
  const handleStartRubricJob = async () => {
    await startEvaluation({
      collectionId,
      rubricId,
    });
  };
  const handleCancelRubricJob = async () => {
    if (!collectionId || !activeRubricJobId || !rubricId) return;
    await cancelEvaluation({
      collectionId,
      rubricId: rubricId,
      jobId: activeRubricJobId,
    });
  };

  /**
   * Clustering (centroids + assignments)
   */

  const [shouldPollClusteringState, setShouldPollClusteringState] =
    useState(false);
  const { data: clusteringState } = useGetClusteringStateQuery(
    {
      collectionId,
      rubricId,
    },
    {
      pollingInterval: shouldPollClusteringState ? 1000 : 0,
    }
  );

  // Job state
  const activeClusteringJobId = clusteringState?.job_id ?? null;
  useEffect(() => {
    setShouldPollClusteringState(activeClusteringJobId !== null);
  }, [activeClusteringJobId]);

  // Extract data
  const centroidsMap =
    clusteringState?.centroids?.reduce(
      (acc, centroid) => {
        acc[centroid.id] = centroid;
        return acc;
      },
      {} as Record<string, RubricCentroid>
    ) ?? {};
  const centroidAssignments = clusteringState?.assignments ?? {};

  // Cancel clustering job
  const [cancelClusteringJob, { isLoading: isCancellingClustering }] =
    useCancelClusteringJobMutation();
  const handleCancelClustering = async () => {
    if (!activeClusteringJobId) return;
    await cancelClusteringJob({
      collectionId,
      rubricId: rubricId,
      jobId: activeClusteringJobId,
    });
  };

  // Clustering job lifecyles
  const [startClusteringJob, { isLoading: isStartingClustering }] =
    useStartClusteringJobMutation();
  const handleStartClustering = async (
    feedback: string | undefined,
    recluster: boolean
  ) => {
    await startClusteringJob({
      collectionId,
      rubricId: rubricId,
      clustering_feedback: feedback,
      recluster: recluster,
    });
  };

  // Clear clusters
  const [clearClusters, { isLoading: isClearingClusters }] =
    useClearClustersMutation();
  const handleClearClusters = async () => {
    await clearClusters({ collectionId, rubricId });
  };

  /**
   * Re-clustering UI
   */

  const [isReclusterPopoverOpen, setIsReclusterPopoverOpen] = useState(false);
  const [feedbackText, setFeedbackText] = useState('');
  const handleReclusterSubmit = async () => {
    await handleStartClustering(feedbackText.trim() || undefined, true);
    setIsReclusterPopoverOpen(false);
    setFeedbackText('');
  };
  const handleReclusterCancel = () => {
    setIsReclusterPopoverOpen(false);
    setFeedbackText('');
  };

  const reclusterPopover = (
    <Popover
      open={isReclusterPopoverOpen}
      onOpenChange={setIsReclusterPopoverOpen}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          size="sm"
          className="gap-1 h-7 text-xs"
          variant="outline"
          disabled={activeClusteringJobId !== null || hasUnsavedChanges}
        >
          {activeClusteringJobId ? 'Proposing...' : 'Re-cluster results'}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-96 p-2 space-y-2">
        <div className="space-y-2">
          <div className="text-sm">
            Provide feedback for re-clustering (optional)
          </div>
          <Textarea
            id="feedback"
            placeholder="Describe how you'd like clusters to be improved..."
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            className="min-h-[80px] resize-none text-xs"
          />
        </div>
        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="text-xs"
            onClick={handleReclusterCancel}
          >
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            className="text-xs"
            onClick={handleReclusterSubmit}
            disabled={activeClusteringJobId !== null}
          >
            {activeClusteringJobId !== null ? 'Proposing...' : 'Re-cluster'}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );

  const router = useRouter();
  const handleExit = () => {
    router.push(`/dashboard/${collectionId}`);
  };

  const handleShare = async () => {
    try {
      const currentUrl = new URL(window.location.href);
      currentUrl.searchParams.set('rubricId', rubricId);

      // If centroids exist, add parameter to auto-load them in the shared link
      if (Object.keys(centroidsMap).length > 0) {
        currentUrl.searchParams.set('includeCentroids', 'true');
      }

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

  const handleRubricSave = async (rubric: Rubric) => {
    updateRubric({
      collectionId,
      rubricId: rubric.id,
      rubric,
    });
  };

  const [
    createOrGetRefinementSession,
    { isLoading: isCreatingRefinementSession },
  ] = useCreateOrGetRefinementSessionMutation();
  const handleStartRefinement = async () => {
    const result = await createOrGetRefinementSession({
      collectionId,
      rubricId,
    }).unwrap();
    router.push(`/dashboard/${collectionId}/refine/${result.id}`);
  };

  const uniqueAgentRunsInJudgeResults = useMemo(
    () => new Set(Object.values(judgeResultsMap).map((r) => r.agent_run_id)),
    [judgeResultsMap]
  );

  const { data: rubric } = useGetRubricQuery({
    collectionId,
    rubricId,
    version: null,
  });
  const labels = rubric?.output_schema?.properties?.label?.enum ?? [];

  return (
    <div className="space-y-2 flex flex-col flex-1 min-w-0">
      <RubricEditor
        rubricId={rubricId}
        rubricVersion={null}
        onSave={handleRubricSave}
        onCloseWithoutSave={() => {}}
        onHasUnsavedChangesUpdated={setHasUnsavedChanges}
        editable={
          !activeRubricJobId && !activeClusteringJobId && hasWritePermission
        }
      />

      {/* Progress bar */}
      {activeRubricJobId && (
        <ProgressBar
          current={uniqueAgentRunsInJudgeResults.size}
          total={totalAgentRuns}
          paused={false}
        />
      )}

      {/* Action Buttons */}
      <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
        {/* Exit and share buttons - always visible */}
        <Button
          type="button"
          size="sm"
          className="gap-1 h-7 text-xs"
          variant="outline"
          onClick={handleExit}
        >
          Exit
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-1 h-7 text-xs"
          onClick={handleShare}
        >
          Share
        </Button>

        {/* Refinement controls - available when nothing else is running */}
        {!activeRubricJobId && !activeClusteringJobId && hasWritePermission && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleStartRefinement}
            disabled={isCreatingRefinementSession}
          >
            Refine
          </Button>
        )}

        {/* Clustering controls */}
        {!activeRubricJobId && hasWritePermission && (
          <>
            {!activeClusteringJobId &&
              Object.keys(centroidsMap).length === 0 && (
                <Button
                  type="button"
                  size="sm"
                  className="gap-1 h-7 text-xs"
                  disabled={hasUnsavedChanges || isStartingClustering}
                  variant="outline"
                  onClick={() => handleStartClustering(undefined, false)}
                >
                  {isStartingClustering
                    ? 'Starting clustering...'
                    : 'Cluster results'}
                </Button>
              )}
            {!activeClusteringJobId && Object.keys(centroidsMap).length > 0 && (
              <>
                {reclusterPopover}
                <Button
                  type="button"
                  size="sm"
                  className="gap-1 h-7 text-xs"
                  disabled={hasUnsavedChanges || isClearingClusters}
                  variant="outline"
                  onClick={handleClearClusters}
                >
                  {isClearingClusters ? 'Clearing…' : 'Clear clusters'}
                </Button>
              </>
            )}
            {activeClusteringJobId && (
              <Button
                type="button"
                size="sm"
                className="gap-1 h-7 text-xs"
                disabled={isCancellingClustering}
                variant="outline"
                onClick={handleCancelClustering}
              >
                {isCancellingClustering
                  ? 'Stopping clustering...'
                  : 'Stop clustering'}
              </Button>
            )}
          </>
        )}

        {/* Rubric controls */}
        {!activeClusteringJobId && hasWritePermission && (
          <>
            {!activeRubricJobId && (
              <Button
                type="button"
                size="sm"
                className="gap-1 h-7 text-xs"
                disabled={isStartingEvaluation || hasUnsavedChanges}
                onClick={handleStartRubricJob}
              >
                {isStartingEvaluation ? 'Starting rubric...' : 'Run rubric'}
              </Button>
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
        )}
      </div>

      {/* Loading indicator */}
      {isLoadingRubricRunState && Object.keys(judgeResultsMap).length === 0 && (
        <div className="flex items-center justify-center">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        </div>
      )}
      {/* Not loading but no results */}
      {!isLoadingRubricRunState &&
        Object.keys(judgeResultsMap).length === 0 && (
          <div className="flex items-center justify-center gap-2 py-2 text-xs text-muted-foreground">
            No results yet. Run the rubric to see results!
          </div>
        )}

      {/* Results */}
      <JudgeResultsList
        judgeResultsMap={judgeResultsMap}
        labels={labels}
        centroidsMap={centroidsMap}
        centroidAssignments={centroidAssignments}
        isPollingAssignments={activeClusteringJobId !== null}
        selectedResultId={selectedResultId}
      />
    </div>
  );
}
