'use client';

import { useRouter } from 'next/navigation';
import { useGetResultByIdQuery } from '@/app/api/rubricApi';
import { useEffect } from 'react';
import { Loader2 } from 'lucide-react';

export default function ResultRedirectPage({
  params,
}: {
  params: { collection_id: string; rubric_id: string; result_id: string };
}) {
  const { collection_id, rubric_id, result_id } = params;
  const router = useRouter();

  const { data: judgeResult, isLoading } = useGetResultByIdQuery({
    collectionId: collection_id,
    resultId: result_id,
  });

  useEffect(() => {
    if (isLoading) return;

    if (!judgeResult) {
      router.replace(`/dashboard/${collection_id}/rubric/${rubric_id}`);
      return;
    }

    router.replace(
      `/dashboard/${collection_id}/rubric/${rubric_id}/agent_run/${judgeResult.agent_run_id}/result/${result_id}`
    );
  }, [judgeResult, isLoading, router, collection_id, rubric_id, result_id]);

  // Show loading state while redirecting
  return (
    <div className="flex-1 flex items-center justify-center min-h-0 h-full">
      <Loader2 size={16} className="animate-spin text-muted-foreground" />
    </div>
  );
}
