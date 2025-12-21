import { toast } from 'sonner';

import { copyToClipboard } from '@/lib/utils';

export async function copyDqlToClipboard(dql: string): Promise<boolean> {
  const trimmed = dql.trim();
  if (!trimmed) {
    toast.error('No DQL to copy.');
    return false;
  }

  const didCopy = await copyToClipboard(trimmed);
  if (!didCopy) {
    toast.error('Could not copy to clipboard');
    return false;
  }

  toast.success('DQL copied to clipboard');
  return true;
}
