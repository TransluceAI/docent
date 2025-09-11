import {
  RubricCentroid,
  useGetClusteringStateQuery,
} from '@/app/api/rubricApi';
import { Button } from '@/components/ui/button';
import { toast } from '@/hooks/use-toast';
import { Share } from 'lucide-react';

interface ShareRubricButtonProps {
  rubricId: string;
  collectionId: string;
  pollingInterval?: number;
}

export default function ShareRubricButton({
  rubricId,
  collectionId,
  pollingInterval = 0,
}: ShareRubricButtonProps) {
  const { centroidsMap } = useGetClusteringStateQuery(
    {
      collectionId,
      rubricId,
    },
    {
      pollingInterval,
      selectFromResult: (result) => ({
        centroidsMap:
          result.data?.centroids?.reduce(
            (acc, centroid) => {
              acc[centroid.id] = centroid;
              return acc;
            },
            {} as Record<string, RubricCentroid>
          ) ?? {},
      }),
    }
  );

  const handleShare = async () => {
    try {
      const currentUrl = new URL(window.location.href);
      currentUrl.searchParams.set('rubricId', rubricId);

      // If centroids exist, add parameter to auto-load them in the shared link
      if (Object.keys(centroidsMap).length > 0) {
        currentUrl.searchParams.set('includeCentroids', 'true');
      }

      await navigator.clipboard.writeText(currentUrl.toString());

      toast({
        title: 'Link copied',
        description: 'Rubric link copied to clipboard',
      });
    } catch (error) {
      console.error('Failed to copy link:', error);
      toast({
        title: 'Error',
        description: 'Failed to copy link to clipboard',
        variant: 'destructive',
      });
    }
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="gap-1 h-7 w-7 text-muted-foreground text-xs"
      onClick={handleShare}
    >
      <Share size={14} />
    </Button>
  );
}
