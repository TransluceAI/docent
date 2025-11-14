'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

import { Rubric } from '../../../store/rubricSlice';

import { Loader2, Minimize2, Maximize2, Tags } from 'lucide-react';
import RubricEditor from './RubricEditor';
import { JudgeResultsList } from './JudgeResultsList';
import { useGetRubricQuery } from '../../../api/rubricApi';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import LabelSetsDialog from './LabelSetsDialog';
import { ResultFilterControlsBadges } from '@/app/components/ResultFilterControls';
import RunRubricButton from './RunRubricButton';
import { AgreementPopover } from './AgreementPopover';
import ClusterButton from './ClusterButton';
import useJobStatus from '@/app/hooks/use-job-status';
import { ProgressBar } from '@/app/components/ProgressBar';
import { useRubricVersion } from '@/providers/use-rubric-version';
import ShareRubricButton from './ShareRubricButton';
import { useRefinementTab } from '@/providers/use-refinement-tab';
import { usePostRubricUpdateToRefinementSessionMutation } from '@/app/api/refinementApi';
import { toast } from '@/hooks/use-toast';
import RubricRunDialog from './RubricRunDialog';
import ViewModeDropdown from './ViewModeDropdown';
import { useGetLabelsInLabelSetQuery } from '@/app/api/labelApi';
import { useLabelSets } from '@/providers/use-label-sets';
import { skipToken } from '@reduxjs/toolkit/query';

interface SingleRubricAreaProps {
  rubricId: string;
  sessionId?: string;
}

export default function SingleRubricArea({
  rubricId,
  sessionId,
}: SingleRubricAreaProps) {
  const {
    collection_id: collectionId,
    result_id: resultId,
    agent_run_id: agentRunId,
  } = useParams<{
    collection_id: string;
    result_id?: string;
    agent_run_id?: string;
  }>();

  const [
    postRubricUpdateToRefinementSession,
    { error: postRubricUpdateError },
  ] = usePostRubricUpdateToRefinementSessionMutation();
  const hasWritePermission = useHasCollectionWritePermission();

  const { activeLabelSet, setLabelSet: setActiveLabelSet } =
    useLabelSets(rubricId);
  const activeLabelSetId = activeLabelSet?.id;

  // Unsaved changes from the editor
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [isRunDialogOpen, setIsRunDialogOpen] = useState(false);
  const { version, setVersion } = useRubricVersion();
  const { setRefinementJobId } = useRefinementTab();

  const {
    // Rubric job status
    rubricJobId,
    rubricJobStatus,
    totalResultsNeeded,
    currentResultsCount,

    // Rubric run results
    agentRunResults,

    // Clustering job status
    clusteringJobId,
    clusteringJobStatus,
    centroids,

    // Clustering results
    assignments,
    // Loading flags
    isResultsLoading,
  } = useJobStatus({
    collectionId,
    rubricId,
    labelSetId: activeLabelSetId ?? null,
  });

  // Get the remote rubric
  const { data: rubric } = useGetRubricQuery({
    collectionId,
    rubricId,
    version,
  });
  const schema = rubric?.output_schema;

  const { data: labels = [], isLoading: isLabelsLoading } =
    useGetLabelsInLabelSetQuery(
      activeLabelSet
        ? { collectionId, labelSetId: activeLabelSet.id }
        : skipToken
    );
  const hasLabels = (labels?.length ?? 0) > 0;

  const [isLabelSetsDialogOpen, setIsLabelSetsDialogOpen] = useState(false);

  const handleImportLabelSet = (labelSet: any) => {
    setActiveLabelSet(labelSet);
  };

  const handleRubricSave = async (
    rubric: Rubric,
    clearLabels: boolean = false
  ) => {
    // Just unlink the labels from the current rubric.
    if (hasLabels && clearLabels) {
      setActiveLabelSet(null);
    }

    if (sessionId) {
      const res = await postRubricUpdateToRefinementSession({
        collectionId,
        sessionId,
        rubric,
      }).unwrap();

      if (postRubricUpdateError) {
        toast({
          title: 'Error',
          description: 'Failed to update refinement session',
          variant: 'destructive',
        });
      } else {
        setVersion(rubric.version);
        if (res?.job_id) setRefinementJobId(res.job_id);
      }
    }
  };

  const [showDiff, setShowDiff] = useState(false);
  const noJudgeResults = agentRunResults.length == 0;
  const [isExpanded, setIsExpanded] = useState(false);

  const ResultsSection = (
    <>
      {/* Action Buttons */}
      <div className="flex flex-wrap items-center justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          {/* View mode dropdown */}
          <ViewModeDropdown
            agentRunResults={agentRunResults}
            labels={labels ?? []}
          />

          {/* Label set */}
          <TooltipProvider>
            <div className="flex">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setIsLabelSetsDialogOpen(true)}
                  >
                    <Tags />
                    {activeLabelSet ? (
                      <span className="hidden xl:inline">
                        {activeLabelSet.name}
                      </span>
                    ) : (
                      <span className="hidden xl:inline">Select label set</span>
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Manage label sets</TooltipContent>
              </Tooltip>
            </div>
          </TooltipProvider>

          {/* Clustering controls */}
          {!rubricJobId && hasWritePermission && !noJudgeResults && (
            <ClusterButton
              collectionId={collectionId}
              rubricId={rubricId}
              clusteringJobId={clusteringJobId}
              clusteringJobStatus={clusteringJobStatus}
              hasUnsavedChanges={hasUnsavedChanges}
              hasCentroids={centroids.length > 0}
            />
          )}

          {/* Rubric controls */}
          {!clusteringJobId && hasWritePermission && centroids.length === 0 && (
            <RunRubricButton
              collectionId={collectionId}
              rubricId={rubricId}
              rubricJobId={rubricJobId}
              rubricJobStatus={rubricJobStatus}
              hasUnsavedChanges={hasUnsavedChanges}
              onClick={() => setIsRunDialogOpen(true)}
            />
          )}

          {/* Expand / collapse and sharing */}
          <div className="hidden lg:flex items-center gap-2">
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="size-7 text-xs text-muted-foreground"
              onClick={() => setIsExpanded(!isExpanded)}
            >
              {isExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </Button>

            <ShareRubricButton
              rubricId={rubricId}
              collectionId={collectionId}
            />
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2 px-0.5 justify-between">
        <ResultFilterControlsBadges />
        <AgreementPopover
          agentRunResults={agentRunResults}
          schema={schema}
          labels={labels ?? []}
        />
      </div>

      {rubricJobId && (
        <ProgressBar
          current={currentResultsCount}
          total={totalResultsNeeded}
          paused={false}
        />
      )}

      {/* Clustering loader (non-blocking) */}
      {clusteringJobId !== null && (
        <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground px-0.5">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
          Clustering results...
        </div>
      )}

      {/* Results */}
      {isResultsLoading || !schema ? (
        <div className="flex items-center justify-center">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        </div>
      ) : !rubricJobId && agentRunResults.length === 0 ? (
        <div className="text-xs text-muted-foreground text-center">
          No results yet
        </div>
      ) : (
        <JudgeResultsList
          labels={labels ?? []}
          centroids={centroids}
          assignments={assignments}
          agentRunResults={agentRunResults}
          isClusteringActive={clusteringJobId !== null}
          activeResultId={resultId}
          activeAgentRunId={agentRunId}
          schema={schema}
          activeLabelSet={activeLabelSet}
        />
      )}

      <RubricRunDialog
        isOpen={isRunDialogOpen}
        onClose={() => setIsRunDialogOpen(false)}
        collectionId={collectionId}
        rubricId={rubricId}
      />
    </>
  );

  return (
    <div className="space-y-2 flex flex-col flex-1 min-w-0">
      {!isExpanded && (
        <RubricEditor
          collectionId={collectionId}
          rubricId={rubricId}
          rubricVersion={version}
          setRubricVersion={setVersion}
          showDiff={showDiff}
          setShowDiff={setShowDiff}
          forceOpenSchema={false}
          onSave={handleRubricSave}
          onCloseWithoutSave={() => {}}
          shouldConfirmOnSave={hasLabels}
          onHasUnsavedChangesUpdated={setHasUnsavedChanges}
          editable={
            !rubricJobId &&
            hasWritePermission &&
            !clusteringJobId &&
            !isLabelsLoading
          }
        />
      )}

      {ResultsSection}

      <LabelSetsDialog
        open={isLabelSetsDialogOpen}
        onOpenChange={setIsLabelSetsDialogOpen}
        onImportLabelSet={handleImportLabelSet}
        onClearActiveLabelSet={() => setActiveLabelSet(null)}
        currentRubricSchema={schema}
        activeLabelSetId={activeLabelSet?.id}
      />
    </div>
  );
}
