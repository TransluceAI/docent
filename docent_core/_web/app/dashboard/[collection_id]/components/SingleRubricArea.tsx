'use client';

import { useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

import { Rubric } from '../../../store/rubricSlice';

import { Tags, Loader2, Minimize2, Maximize2 } from 'lucide-react';
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
import {
  ResultFilterControlsTrigger,
  ResultFilterControlsBadges,
} from '@/app/components/ResultFilterControls';
import RunRubricButton from './RunRubricButton';
import { AgreementPopover } from './AgreementPopover';
import ClusterButton from './ClusterButton';
import useJobStatus from '@/app/hooks/use-job-status';
import { ProgressBar } from '@/app/components/ProgressBar';
import { cn } from '@/lib/utils';
import { useResultFilterControls } from '@/providers/use-result-filters';
import { useRubricVersion } from '@/providers/use-rubric-version';
import ShareRubricButton from './ShareRubricButton';
import { useRefinementTab } from '@/providers/use-refinement-tab';
import { usePostRubricUpdateToRefinementSessionMutation } from '@/app/api/refinementApi';
import { toast } from '@/hooks/use-toast';
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
  const { collection_id: collectionId, result_id: resultId } = useParams<{
    collection_id: string;
    result_id?: string;
  }>();

  const [
    postRubricUpdateToRefinementSession,
    { error: postRubricUpdateError },
  ] = usePostRubricUpdateToRefinementSessionMutation();
  const hasWritePermission = useHasCollectionWritePermission();

  // Unsaved changes from the editor
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const { version, setVersion } = useRubricVersion();
  const { labeled, setLabeled } = useResultFilterControls();
  const { setRefinementJobId } = useRefinementTab();

  const {
    // Rubric job status
    rubricJobId,
    totalAgentRuns,
    currentAgentRuns,

    // Rubric run results
    judgeResults,

    // Clustering job status
    clusteringJobId,
    centroids,

    // Clustering results
    assignments,
    // Loading flags
    isResultsLoading,
  } = useJobStatus({
    collectionId,
    rubricId,
  });

  // Get the remote rubric
  const { data: rubric } = useGetRubricQuery({
    collectionId,
    rubricId,
    version,
  });
  const schema = rubric?.output_schema;

  const { activeLabelSet, setActiveLabelSet, clearLabelSets } = useLabelSets();
  const { data: labels = [], isSuccess: isLabelsSuccess } =
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
      clearLabelSets();
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
  const { applyFilters } = useResultFilterControls();
  const filteredJudgeResultsList = useMemo(
    () => applyFilters(judgeResults, labels ?? []),
    [applyFilters, judgeResults, labels]
  );

  const noJudgeResults = judgeResults.length == 0;
  const [isExpanded, setIsExpanded] = useState(false);

  const ResultsSection = (
    <>
      {/* Action Buttons */}
      <div className="flex flex-wrap items-center justify-between">
        {/* Version changer */}
        <div className="flex items-center gap-2">
          {/* Filter controls -- disabled if rubric job is running */}
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <ResultFilterControlsTrigger />
                </div>
              </TooltipTrigger>
              <TooltipContent>Filter results</TooltipContent>
            </Tooltip>
          </TooltipProvider>

          {/* Label Sets Button Group */}
          <TooltipProvider>
            <div className="flex">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    size="icon"
                    variant="outline"
                    className="h-7 w-7 text-xs rounded-r-none shadow-l"
                    onClick={() => setIsLabelSetsDialogOpen(true)}
                  >
                    <Tags className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Manage label sets</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    className={cn(
                      'h-7 px-2 text-xs rounded-l-none border-l-0',
                      labeled ? 'bg-blue-bg' : ''
                    )}
                    onClick={() => setLabeled(!labeled)}
                    disabled={!activeLabelSet}
                  >
                    {/* <Tags
                      className={cn('h-3 w-3', labeled && 'stroke-blue-text')}
                    /> */}
                    {activeLabelSet ? (
                      <span>{activeLabelSet.name}</span>
                    ) : (
                      <span>Select A Label Set</span>
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Show only labeled results</TooltipContent>
              </Tooltip>
            </div>
          </TooltipProvider>
        </div>

        <div className="flex items-center gap-2">
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
          {/* Clustering controls */}
          {!rubricJobId && hasWritePermission && !noJudgeResults && (
            <ClusterButton
              collectionId={collectionId}
              rubricId={rubricId}
              clusteringJobId={clusteringJobId}
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
              hasUnsavedChanges={hasUnsavedChanges}
            />
          )}
        </div>
      </div>
      <div className="flex items-start gap-2 px-0.5 justify-between">
        <div className="flex-1 min-w-0">
          <ResultFilterControlsBadges />
        </div>
        <div className="flex-shrink-0">
          <AgreementPopover
            filteredJudgeResults={filteredJudgeResultsList}
            labels={labels ?? []}
            schema={schema}
          />
        </div>
      </div>

      {rubricJobId && (
        <ProgressBar
          current={currentAgentRuns}
          total={totalAgentRuns}
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
      ) : !rubricJobId && judgeResults.length === 0 && !labeled ? (
        <div className="text-xs text-muted-foreground text-center">
          No results yet
        </div>
      ) : (
        <JudgeResultsList
          labels={labels ?? []}
          centroids={centroids}
          assignments={assignments}
          filteredJudgeResultsList={filteredJudgeResultsList}
          isClusteringActive={clusteringJobId !== null}
          activeResultId={resultId}
          schema={schema}
          activeLabelSet={activeLabelSet}
        />
      )}
    </>
  );

  if (isExpanded) {
    return (
      <div className="space-y-2 flex flex-col flex-1 min-w-0">
        {ResultsSection}
      </div>
    );
  }

  return (
    <div className="space-y-2 flex flex-col flex-1 min-w-0">
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
          isLabelsSuccess
        }
      />

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
