'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

import { Rubric } from '../../../store/rubricSlice';

import { Loader2, Tags, ChevronRight } from 'lucide-react';
import RubricEditor, { RubricVersionNavigator } from './RubricEditor';
import { JudgeResultsList } from './JudgeResultsList';
import {
  AgentRunJudgeResults,
  useGetRubricQuery,
  useGetLatestRubricVersionQuery,
} from '../../../api/rubricApi';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import LabelSetsDialog from './LabelSetsDialog';
import { ResultFilterControlsBadges } from '@/app/components/ResultFilterControls';
import { AgreementPopover } from './AgreementPopover';
import ClusterButton from './ClusterButton';
import useJobStatus from '@/app/hooks/use-job-status';
import { ProgressBar } from '@/app/components/ProgressBar';
import { useRubricVersion } from '@/providers/use-rubric-version';
import { useRefinementTab } from '@/providers/use-refinement-tab';
import { usePostRubricUpdateToRefinementSessionMutation } from '@/app/api/refinementApi';
import { toast } from '@/hooks/use-toast';
import { Label, useGetLabelsInLabelSetQuery } from '@/app/api/labelApi';
import { useLabelSets } from '@/providers/use-label-sets';
import { skipToken } from '@reduxjs/toolkit/query';
import { SchemaDefinition } from '@/app/types/schema';
import { cn } from '@/lib/utils';
import UuidPill from '@/components/UuidPill';

interface AgreementWidgetProps {
  agentRunResults: AgentRunJudgeResults[];
  activeLabelSet: any;
  setIsLabelSetsDialogOpen: (open: boolean) => void;
  labels: Label[];
  schema?: SchemaDefinition;
  className?: string;
}

function AgreementWidget({
  agentRunResults,
  activeLabelSet,
  setIsLabelSetsDialogOpen,
  labels,
  schema,
  className,
}: AgreementWidgetProps) {
  return (
    <div className={cn('flex flex-row', className)}>
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
      {activeLabelSet && (
        <AgreementPopover
          agentRunResults={agentRunResults}
          labels={labels}
          schema={schema}
        />
      )}
    </div>
  );
}

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

  const noJudgeResults = agentRunResults.length == 0;
  const [isEditorCollapsed, setIsEditorCollapsed] = useState(false);

  // Get the latest version number for the version navigator
  const minVersion = 1;
  const { data: maxVersion } = useGetLatestRubricVersionQuery({
    collectionId,
    rubricId,
  });

  // Determine if the editor is editable
  const isEditable =
    !rubricJobId && hasWritePermission && !clusteringJobId && !isLabelsLoading;

  const isClusteringActive = clusteringJobId !== null || centroids.length > 0;

  const ResultsSection = (
    <>
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <ResultFilterControlsBadges
          agentRunResults={agentRunResults}
          labels={labels ?? []}
          className="mr-auto"
        />
        <div className="flex items-center gap-1.5 ml-auto">
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
          {!isClusteringActive && (
            <AgreementWidget
              agentRunResults={agentRunResults}
              activeLabelSet={activeLabelSet}
              setIsLabelSetsDialogOpen={setIsLabelSetsDialogOpen}
              schema={schema}
              labels={labels ?? []}
            />
          )}
        </div>
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
    </>
  );

  return (
    <div className="space-y-2 flex flex-col flex-1 min-w-0">
      {/* Clickable header with disclosure triangle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="flex items-center gap-1 cursor-pointer hover:text-foreground/80"
            onClick={() => setIsEditorCollapsed(!isEditorCollapsed)}
            aria-expanded={!isEditorCollapsed}
          >
            <ChevronRight
              className={cn(
                'h-4 w-4 transition-transform',
                !isEditorCollapsed && 'rotate-90'
              )}
            />
            <span className="text-sm font-semibold">Rubric</span>
          </button>
          <UuidPill uuid={rubricId} stopPropagation={true} />
        </div>

        <RubricVersionNavigator
          rubric={rubric}
          maxVersion={maxVersion}
          minVersion={minVersion}
          setRubricVersion={setVersion}
        />
      </div>

      {!isEditorCollapsed && (
        <RubricEditor
          collectionId={collectionId}
          rubricId={rubricId}
          rubricVersion={version}
          onSave={handleRubricSave}
          onCloseWithoutSave={() => {}}
          shouldConfirmOnSave={hasLabels}
          onHasUnsavedChangesUpdated={setHasUnsavedChanges}
          editable={isEditable}
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
