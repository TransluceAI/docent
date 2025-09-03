'use client';

import {
  Plus,
  Play,
  FileText,
  Trash2,
  Pause,
  PickaxeIcon,
  Loader2,
} from 'lucide-react';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { type Rubric } from '@/app/store/rubricSlice';
import { Button } from '@/components/ui/button';
import { useParams, useRouter } from 'next/navigation';
import { useCreateOrGetRefinementSessionMutation } from '@/app/api/refinementApi';
import {
  useGetRubricsQuery,
  useCreateRubricMutation,
  useDeleteRubricMutation,
  useStartEvaluationMutation,
  useGetRubricJobStatusQuery,
  useCancelEvaluationMutation,
} from '@/app/api/rubricApi';
import { toast } from '@/hooks/use-toast';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

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
  const dispatch = useAppDispatch();
  const router = useRouter();
  const [
    createOrGetRefinementSession,
    { isLoading: isCreatingRefinementSession },
  ] = useCreateOrGetRefinementSessionMutation();

  // Get job status for this rubric
  const { data: jobDetails } = useGetRubricJobStatusQuery({
    collectionId,
    rubricId: rubric.id,
  });

  // Each card has its own cancellation mutation
  const [cancelEvaluation, { isLoading: isCancellingJob }] =
    useCancelEvaluationMutation();
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
    try {
      const res = await createOrGetRefinementSession({
        collectionId,
        rubricId: rubric.id,
      }).unwrap();
      console.log('res', res);
      router.push(`/dashboard/${collectionId}/refine/${res.id}`);
    } catch (error) {
      console.error('Failed to start refinement session:', error);
      toast({
        title: 'Error',
        description: 'Failed to start refinement session',
        variant: 'destructive',
      });
    }
  };

  const handleClick = () => {
    router.push(`/dashboard/${collectionId}/rubric/${rubric.id}`);
  };

  const [startEvaluation] = useStartEvaluationMutation();

  return (
    <div
      key={rubric.id}
      className="group relative border rounded-md transition-all duration-200 cursor-pointer border-border bg-secondary/50 hover:bg-secondary hover:shadow-sm"
      onClick={handleClick}
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
        {hasWritePermission && (
          <button
            className={`p-1.5 rounded transition-colors hover:bg-secondary text-muted-foreground hover:text-primary`}
            onClick={(e) => {
              e.stopPropagation();
              handleClickRefine();
            }}
            title="Refine rubric"
            disabled={isCreatingRefinementSession}
          >
            <PickaxeIcon className="h-3 w-3" />
          </button>
        )}
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
          title={hasActiveJob ? 'Cancel job' : 'Evaluate with this rubric'}
          disabled={isCancellingJob}
        >
          {hasActiveJob ? (
            <Pause className="h-3 w-3" />
          ) : (
            <Play className="h-3 w-3" />
          )}
        </button>
        {hasWritePermission && (
          <button
            className="p-1.5 rounded transition-colors hover:bg-red-bg/50 text-muted-foreground hover:text-red-text"
            onClick={(e) => {
              e.stopPropagation();
              handleDelete(rubric.id);
            }}
            title="Delete rubric"
            disabled={isDeletingRubric}
          >
            <Trash2 className="h-3 w-3" />
          </button>
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
  const router = useRouter();

  // Check write permissions
  const hasWritePermission = useHasCollectionWritePermission();

  // Fetch rubrics using the new API
  const { data: rubrics, isLoading: isLoadingRubrics } = useGetRubricsQuery(
    effectiveCollectionId
      ? { collectionId: effectiveCollectionId }
      : (undefined as any),
    { skip: !effectiveCollectionId }
  );

  const [createRubric, { isLoading: isCreatingRubric }] =
    useCreateRubricMutation();
  const [startEvaluation] = useStartEvaluationMutation();

  const handleAddNew = async () => {
    if (!collectionId) return;

    try {
      // Create a new rubric using the API
      const newRubric = { rubric_text: '' };

      const createdRubricId = await createRubric({
        collectionId,
        rubric: newRubric,
      }).unwrap();

      // Navigate to the created rubric for editing
      router.push(`/dashboard/${collectionId}?rubricId=${createdRubricId}`);
    } catch (error) {
      console.error('Failed to create rubric:', error);
      toast({
        title: 'Error',
        description: 'Failed to create rubric',
        variant: 'destructive',
      });
    }
  };

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
        <Button
          onClick={handleAddNew}
          size="sm"
          variant="outline"
          className="h-7 gap-1 text-xs"
          disabled={
            !hasWritePermission || isCreatingRubric || !effectiveCollectionId
          }
        >
          <Plus className="h-3 w-3 -ml-1" />
          {isCreatingRubric ? 'Creating...' : 'Rubric'}
        </Button>
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
