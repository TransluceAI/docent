'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

import { Rubric } from '../../../store/rubricSlice';

import { Pickaxe, Tags } from 'lucide-react';
import RubricEditor from './RubricEditor';
import { JudgeResultsList } from './JudgeResultsList';
import {
  useUpdateRubricMutation,
  useDeleteAllJudgeRunLabelsMutation,
  useGetJudgeRunLabelsQuery,
} from '../../../api/rubricApi';
import { useCreateOrGetRefinementSessionMutation } from '@/app/api/refinementApi';
import { Button } from '@/components/ui/button';
import {
  ResultFilterControlsTrigger,
  ResultFilterControlsBadges,
} from '@/app/components/ResultFilterControls';
import RunRubricButton from './RunRubricButton';
import ClusterButton from './ClusterButton';
import { AgreementPopover } from './AgreementPopover';
import useJobStatus from '@/app/hooks/use-job-status';
import { ProgressBar } from '@/app/components/ProgressBar';
import { cn } from '@/lib/utils';
import { useResultFilterControls } from '@/providers/use-result-filters';
import { useRubricVersion } from '@/providers/use-rubric-version';
import ShareRubricButton from './ShareRubricButton';

interface SingleRubricAreaProps {
  rubricId: string;
}

export default function SingleRubricArea({ rubricId }: SingleRubricAreaProps) {
  const router = useRouter();
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();

  const [updateRubric] = useUpdateRubricMutation();
  const [deleteAllJudgeRunLabels] = useDeleteAllJudgeRunLabelsMutation();
  const hasWritePermission = useHasCollectionWritePermission();

  // Unsaved changes from the editor
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const { version, setVersion } = useRubricVersion();
  const { labeled, setLabeled } = useResultFilterControls();

  const {
    // Rubric job status
    shouldPollRubricRunState,
    activeRubricJobId,
    totalAgentRuns,
    currentAgentRuns,

    // Rubric run results
    judgeResults,

    // Clustering job status
    activeClusteringJobId,
    centroids,

    // Clustering results
    assignments,
    shouldPollClusteringState,
  } = useJobStatus({
    collectionId,
    rubricId,
  });

  // Judge run labels
  const { data: labels, isSuccess: isLabelsSuccess } =
    useGetJudgeRunLabelsQuery({
      collectionId,
      rubricId,
    });
  const hasLabels = (labels?.length ?? 0) > 0;

  const handleRubricSave = async (rubric: Rubric) => {
    setVersion(rubric.version);

    if (hasLabels) {
      deleteAllJudgeRunLabels({
        collectionId,
        rubricId: rubric.id,
      });
    }
    updateRubric({
      collectionId,
      rubricId: rubric.id,
      rubric,
    });
  };

  // Create refinement session button
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

  return (
    <div className="space-y-2 flex flex-col flex-1 min-w-0">
      <RubricEditor
        collectionId={collectionId}
        rubricId={rubricId}
        rubricVersion={version}
        setRubricVersion={setVersion}
        onSave={handleRubricSave}
        onCloseWithoutSave={() => {}}
        shouldConfirmOnSave={hasLabels}
        onHasUnsavedChangesUpdated={setHasUnsavedChanges}
        editable={
          !shouldPollRubricRunState &&
          hasWritePermission &&
          !activeClusteringJobId &&
          isLabelsSuccess
        }
      />

      {/* Action Buttons */}
      <div className="flex flex-wrap items-center justify-between">
        {/* Version changer */}
        <div className="flex items-center gap-2">
          {/* Filter controls -- disabled if rubric job is running */}
          <ResultFilterControlsTrigger />
          {/* Bookmark filter - show only labeled results */}
          <Button
            type="button"
            size="icon"
            variant="outline"
            className={cn('h-7 w-7 text-xs', labeled ? 'bg-blue-bg' : '')}
            onClick={() => setLabeled(!labeled)}
            title="Show only labeled results"
          >
            <Tags
              className={labeled ? 'h-3 w-3 stroke-blue-text' : 'h-3 w-3'}
            />
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground"
            onClick={handleStartRefinement}
            disabled={isCreatingRefinementSession}
          >
            <Pickaxe className="h-3 w-3" />
          </Button>
          <ShareRubricButton rubricId={rubricId} collectionId={collectionId} />
          {/* Clustering controls */}
          {!shouldPollRubricRunState && hasWritePermission && (
            <ClusterButton
              collectionId={collectionId}
              rubricId={rubricId}
              activeClusteringJobId={activeClusteringJobId}
              hasUnsavedChanges={hasUnsavedChanges}
            />
          )}

          {/* Rubric controls */}
          {!activeClusteringJobId && hasWritePermission && (
            <RunRubricButton
              collectionId={collectionId}
              rubricId={rubricId}
              activeRubricJobId={activeRubricJobId}
              setShowOnlyLabeled={setLabeled}
              hasUnsavedChanges={hasUnsavedChanges}
            />
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 px-0.5 justify-between">
        <ResultFilterControlsBadges />
        <AgreementPopover
          judgeResults={judgeResults}
          judgeRunLabels={labels ?? []}
        />
      </div>

      {shouldPollRubricRunState && (
        <ProgressBar
          current={currentAgentRuns}
          total={totalAgentRuns}
          paused={false}
        />
      )}

      {/* Results */}
      <JudgeResultsList
        judgeRunLabels={labels ?? []}
        centroids={centroids}
        assignments={assignments}
        judgeResults={judgeResults}
        isClusteringActive={shouldPollClusteringState}
      />
    </div>
  );
}
