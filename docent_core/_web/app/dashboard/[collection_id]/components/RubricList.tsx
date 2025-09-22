'use client';

import {
  Play,
  FileText,
  Trash2,
  Pause,
  Loader2,
  ClipboardCopyIcon,
} from 'lucide-react';
import { useAppSelector } from '@/app/store/hooks';
import { type Rubric } from '@/app/store/rubricSlice';
import { useParams, useRouter } from 'next/navigation';
import { useCreateOrGetRefinementSessionMutation } from '@/app/api/refinementApi';
import {
  useGetRubricsQuery,
  useDeleteRubricMutation,
  useStartEvaluationMutation,
  useGetRubricJobStatusQuery,
  useCancelEvaluationMutation,
  useCopyRubricMutation,
} from '@/app/api/rubricApi';
import { useGetCollectionsQuery } from '@/app/api/collectionApi';
import { toast } from '@/hooks/use-toast';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface RubricCardProps {
  rubric: Rubric;
  collectionId: string;
  hasWritePermission: boolean;
}

function RubricCard({
  rubric,
  collectionId,
  hasWritePermission,
}: RubricCardProps) {
  const router = useRouter();
  const [createOrGetRefinementSession] =
    useCreateOrGetRefinementSessionMutation();

  // Get job status for this rubric
  const { data: jobDetails } = useGetRubricJobStatusQuery({
    collectionId,
    rubricId: rubric.id,
  });

  // Each card has its own cancellation mutation
  const [cancelEvaluation, { isLoading: isCancellingJob }] =
    useCancelEvaluationMutation();
  const { data: collections } = useGetCollectionsQuery();
  const [copyRubric, { isLoading: isCopyingRubric }] = useCopyRubricMutation();

  const copyableCollections = collections || [];

  const handleCopyRubric = async (targetCollectionId: string) => {
    try {
      await copyRubric({
        collectionId,
        rubricId: rubric.id,
        target_collection_id: targetCollectionId,
      }).unwrap();

      const targetCollection = collections?.find(
        (c) => c.id === targetCollectionId
      );
      toast({
        title: 'Rubric Copied',
        description: `Rubric copied to ${targetCollection?.name || targetCollectionId}`,
      });
    } catch (error) {
      console.error('Failed to copy rubric:', error);
      toast({
        title: 'Error',
        description: 'Failed to copy rubric',
        variant: 'destructive',
      });
    }
  };

  const handleCancelJob = async (jobId: string) => {
    try {
      await cancelEvaluation({
        collectionId,
        rubricId: rubric.id,
        jobId,
      }).unwrap();
    } catch (error) {
      console.error('Failed to cancel job:', error);
      toast({
        title: 'Error',
        description: 'Failed to cancel job',
        variant: 'destructive',
      });
    }
  };

  const [deleteRubric, { isLoading: isDeletingRubric }] =
    useDeleteRubricMutation();
  const handleDelete = async (rubricId: string) => {
    if (!collectionId) return;

    try {
      await deleteRubric({
        collectionId,
        rubricId,
      }).unwrap();
    } catch (error) {
      console.error('Failed to delete rubric:', error);
      toast({
        title: 'Error',
        description: 'Failed to delete rubric',
        variant: 'destructive',
      });
    }
  };

  const hasActiveJob =
    jobDetails?.status === 'pending' || jobDetails?.status === 'running';

  const handleClickRefine = async () => {
    if (!collectionId) return;

    if (!hasWritePermission) {
      router.push(`/dashboard/${collectionId}/rubric/${rubric.id}`);
      return;
    }

    try {
      const res = await createOrGetRefinementSession({
        collectionId,
        rubricId: rubric.id,
        sessionType: 'direct',
      }).unwrap();
      console.log('res', res);
      router.push(`/dashboard/${collectionId}/rubric/${rubric.id}`);
    } catch (error) {
      console.error('Failed to start refinement session:', error);
      toast({
        title: 'Error',
        description: 'Failed to start refinement session',
        variant: 'destructive',
      });
    }
  };

  const [startEvaluation] = useStartEvaluationMutation();

  return (
    <div
      key={rubric.id}
      className="group relative border rounded-md transition-all duration-200 cursor-pointer border-border bg-secondary/50 hover:bg-secondary hover:shadow-sm"
      onClick={handleClickRefine}
    >
      <div className={`p-2.5 ${hasWritePermission ? 'pr-28' : 'pr-12'}`}>
        {/* Icon and Description */}
        <div className="flex items-start gap-2">
          <FileText className="h-3.5 w-3.5 text-muted-foreground mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            {!rubric.rubric_text || rubric.rubric_text.trim() === '' ? (
              <p className="text-xs font-mono text-muted-foreground line-clamp-2">
                Empty rubric
              </p>
            ) : (
              <p className="text-xs font-mono text-primary line-clamp-2">
                {rubric.rubric_text.length > 100
                  ? rubric.rubric_text.substring(0, 100) + '...'
                  : rubric.rubric_text}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
        {hasWritePermission && copyableCollections.length > 0 && (
          <DropdownMenu>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuTrigger asChild>
                  <button
                    className="p-1.5 rounded transition-colors hover:bg-secondary text-muted-foreground hover:text-primary"
                    onClick={(e) => e.stopPropagation()}
                    aria-label="Copy this rubric to another collection"
                    disabled={isCopyingRubric}
                  >
                    <ClipboardCopyIcon className="h-3 w-3" />
                  </button>
                </DropdownMenuTrigger>
              </TooltipTrigger>
              <TooltipContent side="top">
                Copy this rubric to another collection
              </TooltipContent>
            </Tooltip>
            <DropdownMenuContent
              align="end"
              className="max-h-60 overflow-y-auto"
              onClick={(event) => event.stopPropagation()}
            >
              <DropdownMenuLabel className="text-xs">
                Select a collection to copy into
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              {copyableCollections.map((collection) => (
                <DropdownMenuItem
                  key={collection.id}
                  onClick={(event) => {
                    event.stopPropagation();
                    handleCopyRubric(collection.id);
                  }}
                  className="text-xs cursor-pointer"
                >
                  <div className="flex flex-col">
                    <span
                      className="font-medium block max-w-[14rem] truncate"
                      title={collection.name || 'Unnamed Collection'}
                    >
                      {collection.name || 'Unnamed Collection'}
                    </span>
                    <span className="text-muted-foreground font-mono text-xs">
                      {collection.id.split('-')[0]}
                    </span>
                  </div>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              className={`p-1.5 rounded transition-colors
                ${
                  hasActiveJob
                    ? 'bg-orange-bg text-orange-text'
                    : 'hover:bg-green-bg/50 text-muted-foreground hover:text-green-text'
                }`}
              onClick={(e) => {
                e.stopPropagation();
                if (hasActiveJob && jobDetails) {
                  handleCancelJob(jobDetails.id);
                } else {
                  startEvaluation({
                    collectionId,
                    rubricId: rubric.id,
                  });
                }
              }}
              aria-label={
                hasActiveJob
                  ? "Cancel this rubric's evaluation job"
                  : 'Run an evaluation with this rubric'
              }
              disabled={isCancellingJob}
            >
              {hasActiveJob ? (
                <Pause className="h-3 w-3" />
              ) : (
                <Play className="h-3 w-3" />
              )}
            </button>
          </TooltipTrigger>
          <TooltipContent side="top">
            {hasActiveJob
              ? "Cancel this rubric's evaluation job"
              : 'Run an evaluation with this rubric'}
          </TooltipContent>
        </Tooltip>
        {hasWritePermission && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                className="p-1.5 rounded transition-colors hover:bg-red-bg/50 text-muted-foreground hover:text-red-text"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(rubric.id);
                }}
                aria-label="Delete this rubric"
                disabled={isDeletingRubric}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">Delete this rubric</TooltipContent>
          </Tooltip>
        )}
      </div>
    </div>
  );
}

export default function RubricList() {
  const params = useParams();
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const effectiveCollectionId =
    collectionId || (params?.collection_id as string | undefined);

  // Check write permissions
  const hasWritePermission = useHasCollectionWritePermission();

  // Fetch rubrics using the new API
  const { data: rubrics, isLoading: isLoadingRubrics } = useGetRubricsQuery(
    effectiveCollectionId
      ? { collectionId: effectiveCollectionId }
      : (undefined as any),
    { skip: !effectiveCollectionId }
  );

  return (
    <div className="space-y-2">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <div className="text-sm font-semibold">Saved Rubrics</div>
          <div className="text-xs text-muted-foreground">
            Run and modify previously-created rubrics
          </div>
        </div>
      </div>

      {/* Rubrics List */}
      <div className="space-y-1.5">
        {!effectiveCollectionId ? (
          <div className="flex justify-center py-4">
            <Loader2 size={16} className="animate-spin text-muted-foreground" />
          </div>
        ) : isLoadingRubrics ? (
          <div className="flex justify-center py-4">
            <Loader2 size={16} className="animate-spin text-muted-foreground" />
          </div>
        ) : rubrics?.length === 0 ? (
          <div className="text-xs text-muted-foreground text-center py-4">
            No rubrics created yet
          </div>
        ) : (
          rubrics?.map((rubric) => (
            <RubricCard
              key={rubric.id}
              rubric={rubric}
              collectionId={effectiveCollectionId!}
              hasWritePermission={hasWritePermission}
            />
          ))
        )}
      </div>
    </div>
  );
}
