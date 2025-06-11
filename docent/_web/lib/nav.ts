import { BASE_DOCENT_PATH } from '@/app/constants';
import { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime';

export const getAgentRunUrl = (
  fgId: string,
  agentRunId: string,
  blockIdx?: number,
  blockIdx2?: number,
  paired?: boolean
) => {
  let prefix =
    `${BASE_DOCENT_PATH}/${fgId}/` +
    (paired ? 'paired_transcript' : 'transcript') +
    `/${agentRunId}`;

  if (blockIdx != undefined) {
    prefix += `?block_id=${blockIdx}`;
    if (blockIdx2 != undefined) {
      prefix += `&block_id_2=${blockIdx2}`;
    }
  }

  return prefix;
};

export const navToAgentRun = (
  e: React.MouseEvent,
  router: AppRouterInstance,
  window: Window,
  agentRunId: string,
  blockId?: number,
  frameGridId?: string,
  searchQuery?: string
) => {
  e.stopPropagation();
  if (!frameGridId) {
    console.error('frameGridId is required');
    return;
  }

  if (e.metaKey || e.ctrlKey || e.button === 1) {
    // Open in new tab
    let url = `${window.location.origin}${BASE_DOCENT_PATH}/${frameGridId}/transcript/${agentRunId}`;

    const blockIdParam = blockId ? `?block_id=${blockId}` : '';
    url += blockIdParam;

    if (searchQuery) {
      url += blockIdParam
        ? `&searchQuery=${searchQuery}`
        : `?searchQuery=${searchQuery}`;
    }

    window.open(url, '_blank');
  } else if (e.button === 0) {
    // Open in same tab
    const url = getAgentRunUrl(frameGridId, agentRunId, blockId);
    console.log('url', url);
    router.push(url);
  }
};
