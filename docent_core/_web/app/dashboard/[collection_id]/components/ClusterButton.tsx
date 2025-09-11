import {
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
import { useState } from 'react';

interface ClusterButtonProps {
  hasUnsavedChanges: boolean;
  collectionId: string;
  rubricId: string;
  activeClusteringJobId?: string;
  hasCentroids?: boolean;
}

const ClusterButton = ({
  hasUnsavedChanges,
  collectionId,
  rubricId,
  activeClusteringJobId,
  hasCentroids,
}: ClusterButtonProps) => {
  // Cancel clustering job
  const [cancelClusteringJob, { isLoading: isCancellingClustering }] =
    useCancelClusteringJobMutation();
  const handleCancelClustering = async () => {
    if (!activeClusteringJobId || !collectionId || !rubricId) return;
    await cancelClusteringJob({
      collectionId,
      rubricId,
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
    if (!collectionId || !rubricId) return;
    await startClusteringJob({
      collectionId,
      rubricId,
      clustering_feedback: feedback,
      recluster: recluster,
    });
  };

  // Clear clusters
  const [clearClusters, { isLoading: isClearingClusters }] =
    useClearClustersMutation();
  const handleClearClusters = async () => {
    if (!collectionId || !rubricId) return;
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

  return (
    <>
      {!activeClusteringJobId && !hasCentroids && (
        <Button
          type="button"
          size="sm"
          className="gap-1 h-7 text-xs"
          disabled={hasUnsavedChanges || isStartingClustering}
          variant="outline"
          onClick={() => handleStartClustering(undefined, false)}
        >
          {isStartingClustering ? 'Starting clustering...' : 'Cluster results'}
        </Button>
      )}
      {!activeClusteringJobId && hasCentroids && (
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
  );
};

export default ClusterButton;
