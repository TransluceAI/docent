import { Button } from '@/components/ui/button';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { requestDiffClusters } from '../store/diffSlice';
import { toast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';
import { Sparkles } from 'lucide-react';
import { useHasFramegridWritePermission } from '@/lib/permissions/hooks';

export function DiffReportConfig() {
  const dispatch = useAppDispatch();
  const diffsReport = useAppSelector((state) => state.diff.diffsReport);
  const hasWritePermission = useHasFramegridWritePermission()

  const onProposeClustersClick = async () => {
    if (!diffsReport) {
      toast({
        title: 'Missing diffs report',
        description: 'Please wait for the diffs report to load',
        variant: 'destructive',
      });
      return;
    }
    dispatch(requestDiffClusters({ diffsReportId: diffsReport.id }));
    toast({
      title: 'Proposing clusters',
      description: 'Please wait for the clusters to be proposed',
    });
  };

  if (!diffsReport) {
    return <div>Config waiting for diffs report to load...</div>;
  }

  return (
    <div className="space-y-2">
      <div>
        <div className="text-sm font-semibold">Analyze themes</div>
        <div className="text-xs">
          Analyze the differences between experiments and propose themes.
        </div>
      </div>
      <div
        className={cn(
          'border rounded-md p-2',
          'bg-gray-50 dark:bg-gray-900/60'
        )}
      >
        <Button
          size="sm"
          className="text-xs w-full"
          onClick={onProposeClustersClick}
          disabled={!hasWritePermission}
        >
          <Sparkles className="h-3 w-3 mr-2" />
          Find themes
        </Button>
      </div>
    </div>
  );
}
