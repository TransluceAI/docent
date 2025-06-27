import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useSearchParams, useRouter } from 'next/navigation';
import React, { useEffect, useRef, useState } from 'react';
import { useAppDispatch } from '../store/hooks';
import { requestDiffs } from '../store/diffSlice';
import { toast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';

type NewDiffsReportProps = {
  experimentId1?: string;
  experimentId2?: string;
};

export function NewDiffsReport({
  experimentId1,
  experimentId2,
}: NewDiffsReportProps) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const dispatch = useAppDispatch();
  const [loading, setLoading] = useState(false);
  const experiment1Ref = useRef<HTMLInputElement>(null);
  const experiment2Ref = useRef<HTMLInputElement>(null);

  // Get frameGridId from URL for navigation
  const frameGridId =
    searchParams.get('fg_id') || searchParams.get('frameGridId');

  useEffect(() => {
    const param1 = searchParams.get('experimentId1') || '';
    const param2 = searchParams.get('experimentId2') || '';
    if (param1 && experiment1Ref.current) experiment1Ref.current.value = param1;
    if (param2 && experiment2Ref.current) experiment2Ref.current.value = param2;
  }, []);

  const handleCompare = async () => {
    const exp1 = experiment1Ref.current?.value;
    const exp2 = experiment2Ref.current?.value;

    if (!exp1 || !exp2) {
      toast({
        title: 'Missing experiment IDs',
        description: 'Please enter both experiment IDs',
        variant: 'destructive',
      });
      return;
    }
    setLoading(true);
    try {
      const diffsReportId = await dispatch(
        requestDiffs({ experimentId1: exp1, experimentId2: exp2 })
      ).unwrap();
      // Navigate to the diff reports page with the diffs report ID
      console.log('Diff Report ID', diffsReportId);
      if (frameGridId) {
        router.push(
          `/dashboard/${frameGridId}/diff_reports?diffsReportId=${diffsReportId}`
        );
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <div>
        <div className="text-sm font-semibold">Compare Experiments</div>
        <div className="text-xs">
          Compare results between two different experiment runs.
        </div>
      </div>
      <div
        className={cn(
          'border rounded-md p-2 space-y-2',
          'bg-gray-50 dark:bg-gray-900/60'
        )}
      >
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <div className="text-xs text-gray-600 dark:text-gray-400">
              Experiment 1
            </div>
            <Input
              ref={experiment1Ref}
              defaultValue={experimentId1}
              placeholder="e.g. experiment-1"
              className={cn(
                'h-8 text-xs font-mono',
                'bg-white dark:bg-gray-800',
                'text-gray-600 dark:text-gray-300'
              )}
              disabled={loading}
            />
          </div>
          <div className="space-y-1">
            <div className="text-xs text-gray-600 dark:text-gray-400">
              Experiment 2
            </div>
            <Input
              ref={experiment2Ref}
              defaultValue={experimentId2}
              placeholder="e.g. experiment-2"
              className={cn(
                'h-8 text-xs font-mono',
                'bg-white dark:bg-gray-800',
                'text-gray-600 dark:text-gray-300'
              )}
              disabled={loading}
            />
          </div>
        </div>
        <Button
          size="sm"
          className="text-xs w-full"
          disabled={loading}
          onClick={handleCompare}
        >
          {loading ? 'Comparing...' : 'Compare Experiments'}
        </Button>
      </div>
    </div>
  );
}
