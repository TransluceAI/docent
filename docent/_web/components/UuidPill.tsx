import { toast } from '@/hooks/use-toast';

export default function UuidPill({ uuid }: { uuid?: string }) {
  if (!uuid) return null;
  const shortUuid = uuid.split('-')[0];

  const copyToClipboard = () => {
    navigator.clipboard.writeText(uuid);
    toast({
      title: 'Copied to clipboard',
      description: 'Full UUID copied to clipboard',
      variant: 'default',
    });
  };

  return (
    <span
      className="inline-flex items-center px-0.5 py-0.5 rounded-md text-xs font-mono text-gray-500 bg-gray-100 border border-gray-200 cursor-pointer hover:bg-gray-200 transition-colors"
      onClick={copyToClipboard}
      title="Click to copy full UUID"
    >
      {shortUuid}
    </span>
  );
}
