import { useParams, useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { useLazyGetResultByAgentRunQuery } from '@/app/api/rubricApi';

interface UseRouteGuardProps {
  version: number | null;
}

export const useRouteGuard = ({ version }: UseRouteGuardProps) => {
  const {
    collection_id: collectionId,
    rubric_id: rubricId,
    agent_run_id: agentRunId,
    result_id: resultId,
  } = useParams<{
    collection_id: string;
    rubric_id: string;
    agent_run_id?: string;
    result_id?: string;
  }>();

  const router = useRouter();

  const [getResultByAgentRun] = useLazyGetResultByAgentRunQuery();

  // Suppose I'm at rubric/[ru]/agent_run/[ar]/result/[re] (with version v)
  // - Check whether ru exists -- if not: 404. if yes, continue
  // - Check whether ar exists -- if not: redirect to rubric/[ru]. if yes, continue
  // - Use the useGetResultByAgentRunQuery to get the re'.
  // - If re is null, redirect to rubric/[ru]/agent_run/[ar].
  // - If re' isn't null and re' != re, redirect to rubric/[ru]/agent_run/[ar]/result/[re'].
  useEffect(() => {
    const check = async () => {
      // TODO Check whether ru exists
      // TODO Check whether ar exists
      // Assume the above is valid for now

      if (!agentRunId || !version) return;

      // Check whether re exists on this agent run
      const { data: result } = await getResultByAgentRun({
        collectionId,
        rubricId,
        agentRunId,
        version,
      });

      // No result exists on this (ru, ar, v) combination; redirect to rubric/[ru]/agent_run/[ar]
      if (!result) {
        router.push(
          `/dashboard/${collectionId}/rubric/${rubricId}/agent_run/${agentRunId}`
        );
      } else {
        // We're looking at the wrong result (or null); redirect to the appropriate one
        if (result.id !== resultId) {
          router.push(
            `/dashboard/${collectionId}/rubric/${rubricId}/agent_run/${agentRunId}/result/${result.id}`
          );
        }
        // Otherwise, nothing to do; we're looking at the correct result
      }
    };
    check();
  }, [agentRunId, version, collectionId, rubricId, resultId, router]);
};
