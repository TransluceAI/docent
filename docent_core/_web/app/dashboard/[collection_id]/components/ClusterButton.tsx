import {
  JobStatus,
  useCancelClusteringJobMutation,
  useClearClustersMutation,
  useStartClusteringJobMutation,
} from '@/app/api/rubricApi';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Textarea } from '@/components/ui/textarea';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useRubricVersion } from '@/providers/use-rubric-version';
import { useEffect, useState, type ReactNode } from 'react';

interface ClusterButtonProps {
  hasUnsavedChanges: boolean;
  collectionId: string;
  rubricId: string;
  clusteringJobId: string | null;
  clusteringJobStatus: JobStatus | null;
  hasCentroids?: boolean;
}

const ClusterButton = ({
  hasUnsavedChanges,
  collectionId,
  rubricId,
  clusteringJobId,
  clusteringJobStatus,
  hasCentroids,
}: ClusterButtonProps) => {
  // Cancel clustering job
  const [cancelClusteringJob, { isLoading: isCancellingClustering }] =
    useCancelClusteringJobMutation();
  const [hasPendingCancel, setHasPendingCancel] = useState(false);
  const handleCancelClustering = async () => {
    if (!clusteringJobId || !collectionId || !rubricId) return;
    setHasPendingCancel(true);
    await cancelClusteringJob({
      collectionId,
      rubricId,
      jobId: clusteringJobId,
    }).unwrap();
  };

  // Clustering job lifecyles
  const [startClusteringJob, { isLoading: isStartingClustering }] =
    useStartClusteringJobMutation();
  const [hasPendingStart, setHasPendingStart] = useState(false);
  const handleStartClustering = async (
    feedback: string | undefined,
    recluster: boolean
  ) => {
    if (!collectionId || !rubricId || clusteringJobId !== null) return;
    setHasPendingStart(true);
    try {
      await startClusteringJob({
        collectionId,
        rubricId,
        clustering_feedback: feedback,
        recluster: recluster,
      }).unwrap();
    } catch (error) {
      setHasPendingStart(false);
      throw error;
    }
  };

  // Clear clusters
  const [clearClusters, { isLoading: isClearingClusters }] =
    useClearClustersMutation();
  const handleClearClusters = async () => {
    if (!collectionId || !rubricId) return;
    await clearClusters({ collectionId, rubricId }).unwrap();
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

  const { latestVersion, version } = useRubricVersion();
  const isLatestVersion = version === latestVersion;
  const isJobCancelling = clusteringJobStatus === 'cancelling';
  const showCancellingState =
    isCancellingClustering || hasPendingCancel || isJobCancelling;

  useEffect(() => {
    if (!clusteringJobId || isJobCancelling) {
      setHasPendingCancel(false);
    }
    if (clusteringJobId) {
      setHasPendingStart(false);
    }
  }, [clusteringJobId, isJobCancelling]);

  const StartButton = () => {
    return (
      <Button
        type="button"
        size="sm"
        className="gap-1 h-7 text-xs"
        disabled={
          hasUnsavedChanges ||
          isStartingClustering ||
          hasPendingStart ||
          !isLatestVersion
        }
        variant="outline"
        onClick={() => handleStartClustering(undefined, false)}
      >
        {isStartingClustering || hasPendingStart ? 'Starting...' : 'Cluster'}
      </Button>
    );
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
          disabled={
            clusteringJobId !== null ||
            hasUnsavedChanges ||
            !isLatestVersion ||
            hasPendingStart
          }
        >
          {clusteringJobId ? 'Proposing...' : 'Re-cluster results'}
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
            disabled={
              clusteringJobId !== null || !isLatestVersion || hasPendingStart
            }
          >
            {clusteringJobId !== null ? 'Proposing...' : 'Re-cluster'}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );

  const renderWithVersionTooltip = (node: ReactNode) => {
    if (isLatestVersion) {
      return node;
    }
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <div>{node}</div>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          Switch to the latest version to cluster.
        </TooltipContent>
      </Tooltip>
    );
  };

  return (
    <>
      {!clusteringJobId && !hasCentroids && (
        <>
          {isLatestVersion ? (
            <StartButton />
          ) : (
            renderWithVersionTooltip(<StartButton />)
          )}
        </>
      )}
      {!clusteringJobId && hasCentroids && (
        <>
          {renderWithVersionTooltip(reclusterPopover)}
          {renderWithVersionTooltip(
            <Button
              type="button"
              size="sm"
              className="gap-1 h-7 text-xs"
              disabled={
                hasUnsavedChanges ||
                isClearingClusters ||
                !isLatestVersion ||
                hasPendingStart
              }
              variant="outline"
              onClick={handleClearClusters}
            >
              {isClearingClusters ? 'Clearing…' : 'Clear clusters'}
            </Button>
          )}
        </>
      )}
      {clusteringJobId && (
        <Button
          type="button"
          size="sm"
          className="gap-1 h-7 text-xs"
          disabled={showCancellingState}
          variant="outline"
          onClick={handleCancelClustering}
        >
          {showCancellingState ? 'Cancelling...' : 'Stop clustering'}
        </Button>
      )}
    </>
  );
};

export default ClusterButton;
