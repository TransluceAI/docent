import { BASE_DOCENT_PATH } from '@/app/constants';
import { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime';

export const getAgentRunUrl = (
  collectionId: string,
  agentRunId: string,
  transcriptIdx?: number,
  blockIdx?: number,
  blockIdx2?: number,
  paired?: boolean,
  searchQuery?: string
) => {
  const prefix =
    `${BASE_DOCENT_PATH}/${collectionId}/` +
    (paired ? 'paired_transcript' : 'agent_run') +
    `/${agentRunId}`;
  const params = new URLSearchParams();

  if (transcriptIdx != undefined) {
    params.append('transcript_idx', transcriptIdx.toString());
  }

  if (blockIdx != undefined) {
    params.append('block_idx', blockIdx.toString());
    if (blockIdx2 != undefined) {
      params.append('block_idx_2', blockIdx2.toString());
    }
  }

  if (searchQuery) {
    params.append('searchQuery', searchQuery);
  }

  const queryString = params.toString();
  return queryString ? `${prefix}?${queryString}` : prefix;
};

export const navToAgentRun = (
  router: AppRouterInstance,
  window: Window,
  agentRunId: string,
  transcriptIdx?: number,
  blockIdx?: number,
  collectionId?: string,
  searchQuery?: string,
  openInNewTab?: boolean
) => {
  if (!collectionId) {
    console.error('collectionId is required');
    return;
  }

  openInNewTab = openInNewTab ?? false;

  const url = getAgentRunUrl(
    collectionId,
    agentRunId,
    transcriptIdx,
    blockIdx,
    undefined,
    undefined,
    searchQuery
  );
  if (openInNewTab) {
    window.open(url, '_blank');
  } else {
    router.push(url);
  }
};
