'use client';

import { useCallback, useState } from 'react';
import { useParams } from 'next/navigation';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

import { Rubric } from '../../../store/rubricSlice';

import {
  Loader2,
  Tags,
  ChevronRight,
  FunnelPlus,
  FileCode,
} from 'lucide-react';
import RubricEditor, { RubricVersionNavigator } from './RubricEditor';
import { JudgeResultsList } from './JudgeResultsList';
import {
  AgentRunJudgeResults,
  useGetRubricQuery,
  useGetLatestRubricVersionQuery,
  useGetJudgeResultFilterFieldsQuery,
} from '../../../api/rubricApi';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import LabelSetsDialog from './LabelSetsDialog';
import { AgreementPopover } from './AgreementPopover';
import ClusterButton from './ClusterButton';
import useJobStatus from '@/app/hooks/use-job-status';
import { ProgressBar } from '@/app/components/ProgressBar';
import { useRubricVersion } from '@/providers/use-rubric-version';
import { useRefinementTab } from '@/providers/use-refinement-tab';
import { usePostRubricUpdateToRefinementSessionMutation } from '@/app/api/refinementApi';
import { toast } from 'sonner';
import { Label, useGetLabelsInLabelSetQuery } from '@/app/api/labelApi';
import { useLabelSets } from '@/providers/use-label-sets';
import { skipToken } from '@reduxjs/toolkit/query';
import { SchemaDefinition } from '@/app/types/schema';
import { cn } from '@/lib/utils';
import UuidPill from '@/components/UuidPill';
import { FilterControls } from '@/app/components/FilterControls';
import { FilterChips } from '@/app/components/FilterChips';
import { ComplexFilter, PrimitiveFilter } from '@/app/types/collectionTypes';
import ViewModeDropdown from './ViewModeDropdown';
import { ViewMode } from '../utils/viewModeResults';
import DownloadMenu from '@/app/components/DownloadMenu';
import { BASE_URL } from '@/app/constants';
import { useDownloadApiKey } from '@/app/hooks/use-download-api-key';
import { downloadPythonSample } from '@/app/utils/pythonSamples';

interface AgreementWidgetProps {
  agentRunResults: AgentRunJudgeResults[];
  activeLabelSet: any;
  setIsLabelSetsDialogOpen: (open: boolean) => void;
  labels: Label[];
  schema?: SchemaDefinition;
  className?: string;
  activeFilters: any[];
}

function AgreementWidget({
  agentRunResults,
  activeLabelSet,
  setIsLabelSetsDialogOpen,
  labels,
  schema,
  className,
  activeFilters,
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
          activeFilters={activeFilters}
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

  // Filter and view mode state
  const [runsFilter, setRunsFilter] = useState<ComplexFilter | null>(null);
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false);
  const [editingFilter, setEditingFilter] = useState<PrimitiveFilter | null>(
    null
  );
  const [viewMode, setViewMode] = useState<ViewMode>('all');
  const [showFailures, setShowFailures] = useState(false);

  const { data: filterFieldsData } = useGetJudgeResultFilterFieldsQuery(
    {
      collectionId: collectionId!,
      rubricId,
      version,
    },
    {
      skip: !collectionId,
    }
  );
  const agentRunMetadataFields = filterFieldsData?.fields ?? [];

  const {
    // Rubric job status
    rubricJobId,
    rubricJobStatus,
    totalResultsNeeded,
    currentResultsCount,

    // Rubric run results
    agentRunResults: agentRunResultsAll,
    failureCount,

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
    filter: runsFilter,
  });

  // Filter out failures if not showing them
  const agentRunResults = showFailures
    ? agentRunResultsAll
    : agentRunResultsAll
        .map((run) => ({
          // This logic filters out the failures from the results of this agent run
          // Prevents issue where, if an agent run has both successes and failures, the failures slip through
          ...run,
          results:
            run.results?.filter(
              (result) => result.result_type === 'DIRECT_RESULT'
            ) ?? [],
        }))
        .filter((run) => run.results.length > 0);

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

  const { getApiKey: getDownloadApiKey, isLoading: isApiKeyLoading } =
    useDownloadApiKey();
  const [isDownloadingSample, setIsDownloadingSample] = useState(false);
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
        toast.error('Failed to update refinement session');
      } else {
        setVersion(rubric.version);
        if (res?.job_id) setRefinementJobId(res.job_id);
      }
    }
  };

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

  const handleRunsFilterChange = (filters: ComplexFilter | null) => {
    setRunsFilter(filters);
    setEditingFilter(null);
    setFilterPopoverOpen(false);
  };

  const handleRequestEditFilter = (filter: PrimitiveFilter) => {
    setEditingFilter(filter);
    setFilterPopoverOpen(true);
  };

  const handleDownloadRubricSample = useCallback(
    async (format: 'python' | 'notebook' = 'python') => {
      if (!collectionId) {
        toast.error('Open a collection before downloading a code sample.');
        return;
      }

      try {
        setIsDownloadingSample(true);
        const apiKey = await getDownloadApiKey();
        await downloadPythonSample({
          type: 'rubric_results',
          api_key: apiKey,
          server_url: BASE_URL,
          collection_id: collectionId,
          rubric_id: rubricId,
          rubric_version: version ?? null,
          runs_filter: runsFilter ?? null,
          format,
        });
      } catch (error) {
        console.error('Failed to download rubric Python sample', error);
        toast.error('Unable to generate a Python sample for this rubric.');
      } finally {
        setIsDownloadingSample(false);
      }
    },
    [
      agentRunResults.length,
      collectionId,
      getDownloadApiKey,
      rubricId,
      runsFilter,
      version,
    ]
  );

  const ResultsSection = (
    <>
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <div className="flex flex-wrap gap-1.5 items-center mr-auto">
          <div className="inline-flex items-center border border-border rounded-md overflow-hidden">
            <ViewModeDropdown
              agentRunResults={agentRunResults}
              labels={labels ?? []}
              className="!border-0 rounded-r-none rounded-l-md shadow-none"
              viewMode={viewMode}
              setViewMode={setViewMode}
            />
            <div className="h-7 w-px bg-border" />
            <Popover
              open={filterPopoverOpen}
              onOpenChange={setFilterPopoverOpen}
            >
              <Tooltip>
                <TooltipTrigger asChild>
                  <PopoverTrigger asChild>
                    <Button className="inline-flex items-center h-7 gap-x-1 text-xs bg-background text-muted-foreground hover:text-primary px-1.5 hover:bg-accent transition-all duration-200 rounded-l-none rounded-r-md">
                      <FunnelPlus size={14} className="stroke-[1.5]" />
                    </Button>
                  </PopoverTrigger>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Add filter</p>
                </TooltipContent>
              </Tooltip>
              <PopoverContent
                align="start"
                sideOffset={4}
                className="w-[520px] overflow-x-auto"
              >
                <FilterControls
                  filters={runsFilter}
                  onFiltersChange={handleRunsFilterChange}
                  metadataFields={agentRunMetadataFields}
                  collectionId={collectionId!}
                  showStepFilter={false}
                  initialFilter={editingFilter}
                />
              </PopoverContent>
            </Popover>
          </div>
          {runsFilter && (
            <FilterChips
              filters={runsFilter}
              onFiltersChange={handleRunsFilterChange}
              onRequestEdit={handleRequestEditFilter}
            />
          )}
          {failureCount > 0 && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Switch
                id="include-failures"
                checked={showFailures}
                onCheckedChange={setShowFailures}
                className="scale-75"
              />
              <label htmlFor="include-failures" className="cursor-pointer">
                Show <span className="text-red-500">{failureCount} errors</span>
              </label>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1.5 ml-auto">
          {!rubricJobId &&
            hasWritePermission &&
            agentRunResultsAll.some((run) =>
              run.results?.some((r) => r.result_type === 'DIRECT_RESULT')
            ) && (
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
              activeFilters={runsFilter?.filters ?? []}
            />
          )}
          <DownloadMenu
            options={[
              {
                key: 'python',
                label: 'Python',
                disabled: isDownloadingSample || isApiKeyLoading,
                icon:
                  isDownloadingSample || isApiKeyLoading ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <FileCode className="h-3 w-3" />
                  ),
                onSelect: () => {
                  void handleDownloadRubricSample('python');
                },
              },
              {
                key: 'notebook',
                label: 'Notebook',
                disabled: isDownloadingSample || isApiKeyLoading,
                icon:
                  isDownloadingSample || isApiKeyLoading ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <FileCode className="h-3 w-3" />
                  ),
                onSelect: () => {
                  void handleDownloadRubricSample('notebook');
                },
              },
            ]}
            isLoading={isDownloadingSample || isApiKeyLoading}
            triggerDisabled={isDownloadingSample || isApiKeyLoading}
            className="h-7 gap-1 text-xs"
            contentClassName="w-36"
          />
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
          viewMode={viewMode}
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
