'use client';

import { useParams, useRouter } from 'next/navigation';
import { Card } from '@/components/ui/card';

import RubricList from './RubricList';
import {
  useStartEvaluationMutation,
  useCreateRubricMutation,
} from '../../../api/rubricApi';
import { useCreateOrGetRefinementSessionMutation } from '../../../api/refinementApi';
import { toast } from '@/hooks/use-toast';
import QuickSearchBox from './QuickSearchBox';

const RubricArea = () => {
  const router = useRouter();
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();

  // Mutations
  const [startEvaluation, { isLoading: isStartingEvaluation }] =
    useStartEvaluationMutation();
  const [createRubric, { isLoading: isCreatingRubric }] =
    useCreateRubricMutation();
  const [createOrGetSession, { isLoading: isCreatingOrGettingSession }] =
    useCreateOrGetRefinementSessionMutation();

  const handleAddNewRubric = async (rubricText: string) => {
    if (!collectionId) return undefined;

    return await createRubric({
      collectionId,
      rubric: {
        rubric_text: rubricText,
      },
    })
      .unwrap()
      .catch((error) => {
        console.error('Failed to create rubric', error);
        toast({
          title: 'Error',
          description: 'Failed to create rubric',
          variant: 'destructive',
        });
      });
  };

  const handleGuidedSubmit = async (highLevelDescription: string) => {
    const rubricId = await handleAddNewRubric(highLevelDescription);
    if (!rubricId) return;

    await createOrGetSession({
      collectionId,
      rubricId,
      sessionType: 'guided',
    })
      .unwrap()
      .then(() => {
        router.push(`/dashboard/${collectionId}/rubric/${rubricId}`);
      })
      .catch((error) => {
        console.error('Failed to create or get session:', error);
        toast({
          title: 'Error',
          description: 'Failed to create or get session',
          variant: 'destructive',
        });
      });
  };

  const handleDirectSubmit = async (highLevelDescription: string) => {
    const rubricId = await handleAddNewRubric(highLevelDescription);
    if (!rubricId) return;

    await startEvaluation({
      collectionId,
      rubricId,
    }).catch((error) => {
      console.error('Failed to start full search:', error);
      toast({
        title: 'Error',
        description: 'Failed to start full search',
        variant: 'destructive',
      });
    });

    await createOrGetSession({
      collectionId,
      rubricId,
      sessionType: 'direct',
    })
      .then(() => {
        router.push(`/dashboard/${collectionId}/rubric/${rubricId}`);
      })
      .catch((error) => {
        console.error('Failed to create or get session:', error);
        toast({
          title: 'Error',
          description: 'Failed to create or get session',
          variant: 'destructive',
        });
      });
  };

  return (
    <Card className="h-full flex overflow-y-auto flex-col flex-1 p-3 custom-scrollbar space-y-3">
      {/* Rubric Display */}
      <div className="space-y-2">
        <QuickSearchBox
          onGuided={handleGuidedSubmit}
          onDirect={handleDirectSubmit}
          isLoading={
            isCreatingRubric ||
            isCreatingOrGettingSession ||
            isStartingEvaluation
          }
        />
        <RubricList />
      </div>
    </Card>
  );
};

export default RubricArea;
