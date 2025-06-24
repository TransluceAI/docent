import { toast } from '@/hooks/use-toast';
import { copyToClipboard } from '@/lib/utils';

export default function UuidPill({ uuid }: { uuid?: string }) {
  if (!uuid) return null;
  const shortUuid = uuid.split('-')[0];

  const onClick = async () => {
    const success = await copyToClipboard(uuid);
    if (success) {
      toast({
        title: 'Copied to clipboard',
        description: 'Full UUID copied to clipboard',
        variant: 'default',
      });
    } else {
      toast({
        title: 'Failed to copy',
        description: 'Could not copy to clipboard',
        variant: 'destructive',
      });
    }
  };

  return (
    <span
      className="inline-flex items-center h-6 px-0.5 py-0.5 rounded-md text-xs font-mono text-gray-500 bg-gray-100 border border-gray-200 cursor-pointer hover:bg-gray-200 transition-colors"
      onClick={onClick}
      title="Click to copy full UUID"
    >
      {shortUuid}
    </span>
  );
}
