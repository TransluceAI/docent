'use client';

import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { useAppSelector } from '../store/hooks';
import { Claim, TranscriptDiff } from '../store/diffSlice';
import { AgentRunMetadata } from './AgentRunMetadata';
import React, { useCallback, useState } from 'react';
import { ChevronRight, Info, FileText } from 'lucide-react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { BASE_DOCENT_PATH } from '../constants';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { CitationRenderer } from '@/components/CitationRenderer';

type Props = {
  diffKey: string;
};
const useHandleShowAgentRun = () => {
  const router = useRouter();
  const fgId = useAppSelector((state) => state.frame.frameGridId);

  const handleShowAgentRun = useCallback(
    (
      agentRunId: string,
      blockIdx?: number,
      blockIdx2?: number,
      paired?: boolean
    ) => {
      console.log('PARAMS', agentRunId, blockIdx, blockIdx2, paired);
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
      console.log('PUSHING', prefix);
      router.push(prefix);
    },
    [router, fgId]
  );

  return handleShowAgentRun;
};

// Badge helper for agent names
export const agentBadge = (agent: 'Agent 1' | 'Agent 2') => {
  const map = {
    'Agent 1': {
      name: 'Sonnet 3.5',
      badge: '[Agent 1]',
      color:
        'bg-orange-100/20 text-orange-800 dark:bg-orange-900/50 dark:text-orange-200',
    },
    'Agent 2': {
      name: 'Sonnet 3.7',
      badge: '[Agent 2]',
      color: 'bg-sky-100/20 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200',
    },
  };
  const { name, badge, color } = map[agent];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded px-1 py-0.5 text-xs font-semibold',
        color
      )}
    >
      {name} <span className="opacity-70">{badge}</span>
    </span>
  );
};

// Helper to interpolate agent names in any string
export const interpolateAgentBadges = (text: string) => {
  // Split on Agent 1/Agent 2 and interleave with badges
  const parts = text.split(/(Agent 1|Agent 2)/g);
  return parts.map((part, idx) => {
    if (part === 'Agent 1' || part === 'Agent 2') {
      return (
        <React.Fragment key={idx}>
          {agentBadge(part as 'Agent 1' | 'Agent 2')}
        </React.Fragment>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
};

type AgentMetadataSummaryProps = {
  agentRunId: string;
  agentLabel: 'Agent 1' | 'Agent 2';
};

const AgentMetadataSummary = ({
  agentRunId,
  agentLabel,
}: AgentMetadataSummaryProps) => {
  const agentRunMetadata = useAppSelector(
    (state) => state.frame.agentRunMetadata
  );
  const meta = agentRunMetadata?.[agentRunId];
  let isCorrect: boolean | undefined = undefined;
  if (meta && meta.scores && typeof meta.default_score_key === 'string') {
    isCorrect = meta.scores[meta.default_score_key] as boolean | undefined;
  }
  const [showDetails, setShowDetails] = useState(false);

  const toggle = () => {
    setShowDetails((v) => !v);
  };

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-0.5 text-xs py-1">
        {agentBadge(agentLabel)}
        {isCorrect !== undefined && (
          <span
            className={cn(
              'text-xs px-1 py-0.5 font-semibold rounded',
              isCorrect
                ? 'text-green-500 dark:text-green-400'
                : 'text-red-500 dark:text-red-400'
            )}
          >
            {isCorrect ? '✓ Correct' : '✗ Incorrect'}
          </span>
        )}
        <button
          onClick={toggle}
          className="ml-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 focus:outline-none"
          aria-label="Show details"
        >
          <span className="text-lg leading-none">
            <Info className="w-4 h-4" />{' '}
          </span>
        </button>
      </div>
      {showDetails && (
        <div className="pl-5 pb-1">
          <AgentRunMetadata agentRunId={agentRunId} />
        </div>
      )}
    </div>
  );
};

export const TranscriptDiffSummary = ({ diffKey }: Props) => {
  const diff = useAppSelector(
    (state) => state.diff.transcriptDiffsByKey[diffKey]
  );
  const filteredClaimIds = useAppSelector(
    (state) => state.diff.filteredClaimIds
  );
  if (!diff) {
    return null;
  }
  if (!diff.claims || diff.claims.length === 0) {
    return (
      <Card>
        <CardContent>
          <div className="text-sm text-muted-foreground dark:text-gray-400">
            No differences found.
          </div>
        </CardContent>
      </Card>
    );
  }

  // Filter claims if filteredClaimIds is set
  const filteredClaims = filteredClaimIds
    ? diff.claims.filter((claim) => filteredClaimIds.includes(claim.id))
    : diff.claims;

  if (filteredClaims.length === 0) {
    return null;
  }

  return (
    <Card>
      <div className="">
        <h2
          className={cn(
            'text-xs font-semibold uppercase tracking-wide',
            'text-gray-500 dark:text-gray-400'
          )}
        >
          Transcript Differences for Task
        </h2>
        <h1 className={cn('text-sm  mb-1', 'text-gray-900 dark:text-gray-100')}>
          {diff.title}
        </h1>
      </div>
      <CardContent className="space-y-1">
        <div className={cn('grid grid-cols-1 sm:grid-cols-2 gap-2 mb-2')}>
          <AgentMetadataSummary
            agentRunId={diff.agent_run_1_id}
            agentLabel="Agent 1"
          />
          <AgentMetadataSummary
            agentRunId={diff.agent_run_2_id}
            agentLabel="Agent 2"
          />
        </div>
        {filteredClaims.map((claim, idx) => (
          <DiffClaimView key={idx} claim={claim} transcriptDiff={diff} />
        ))}
      </CardContent>
    </Card>
  );
};

type ClaimProps = {
  claim: Claim;
  transcriptDiff: TranscriptDiff;
};
const DiffClaimView = ({ claim, transcriptDiff }: ClaimProps) => {
  const [expanded, setExpanded] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const handleShowAgentRun = useHandleShowAgentRun();
  const fgId = useAppSelector((state) => state.frame.frameGridId);
  const router = useRouter();

  return (
    <div
      className={cn(
        'rounded-sm border border-gray-100 dark:border-gray-900 bg-gray-50 dark:bg-gray-900/60',
        'shadow-sm'
      )}
    >
      {/* Header row: chevron + summary */}
      <div className="flex">
        {/* Chevron column */}
        <div className="w-8 flex items-center justify-center">
          <button
            className={cn(
              'focus:outline-none',
              'transition-transform',
              expanded ? 'rotate-90' : 'rotate-0',
              'text-gray-500 dark:text-gray-300'
            )}
            aria-expanded={expanded}
            aria-controls={`claim-details-${claim.claim_summary}`}
            onClick={(e) => {
              setExpanded((v) => !v);
              e.stopPropagation();
            }}
            tabIndex={0}
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
        {/* Summary header */}
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <button
              className={cn(
                'w-full text-left px-0 py-3 focus:outline-none',
                'rounded-t-lg',
                'bg-transparent',
                'transition-colors duration-150'
              )}
              aria-expanded={expanded}
              aria-controls={`claim-details-${claim.claim_summary}`}
              onClick={(e) => {
                setExpanded((v) => !v);
                e.stopPropagation();
              }}
            >
              <span
                className={cn(
                  'text-gray-900 dark:text-gray-100 text-xs text-left'
                )}
              >
                {interpolateAgentBadges(claim.claim_summary)}
              </span>
            </button>
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  href={`${BASE_DOCENT_PATH}/${fgId}/paired_transcript/${transcriptDiff.agent_run_1_id}___${transcriptDiff.agent_run_2_id}?block_id=0&block_id_2=0&claim_id=${claim.id}`}
                  className={cn(
                    'ml-2 p-1 rounded-full',
                    'hover:bg-gray-200 dark:hover:bg-gray-700',
                    'focus:outline-none focus:ring-2 focus:ring-indigo-400',
                    'transition-colors'
                  )}
                  aria-label="View Transcript"
                >
                  <FileText className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                </Link>
              </TooltipTrigger>
              <TooltipContent side="left" align="center">
                View Transcript
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>
      {/* Collapsible content */}
      {expanded && (
        <div
          id={`claim-details-${claim.claim_summary}`}
          className="px-4 pl-7 pt-2 pb-3 mt-1 space-y-2"
        >
          {/* Shared context */}
          {claim.shared_context && (
            <div
              className={cn(
                'text-xs text-gray-500 dark:text-gray-400 italic',
                'mb-2'
              )}
            >
              {claim.shared_context}
            </div>
          )}
          {/* Agent actions side-by-side */}
          <div
            className={cn(
              'flex flex-col sm:flex-row gap-2 sm:gap-4',
              'divide-y sm:divide-y-0 sm:divide-x divide-gray-200 dark:divide-gray-700'
            )}
          >
            <div className="flex-1 py-2 sm:py-0 sm:pr-4">
              <div className="text-xs font-medium text-blue-700 dark:text-blue-300 mb-1">
                {agentBadge('Agent 1')}
              </div>
              <div className="text-xs text-gray-800 dark:text-gray-200 whitespace-pre-line">
                {claim.agent_1_action}
              </div>
            </div>
            <div className="flex-1 py-2 sm:py-0 sm:pl-4">
              <div className="text-xs font-medium text-purple-700 dark:text-purple-300 mb-1">
                {agentBadge('Agent 2')}
              </div>
              <div className="text-xs text-gray-800 dark:text-gray-200 whitespace-pre-line">
                {claim.agent_2_action}
              </div>
            </div>
          </div>
          {/* Evidence toggle */}
          {claim.evidence_with_citations && (
            <div className="mt-2">
              <button
                className={cn(
                  'text-xs font-medium underline text-indigo-600 dark:text-indigo-400',
                  'hover:text-indigo-800 dark:hover:text-indigo-200 transition-colors',
                  'focus:outline-none'
                )}
                onClick={() => setShowEvidence((v) => !v)}
                aria-expanded={showEvidence}
              >
                {showEvidence ? 'Hide Evidence' : 'Show Evidence'}
              </button>
              {showEvidence && (
                <div className="mt-1 text-xs text-gray-600 dark:text-gray-300 bg-indigo-50 dark:bg-indigo-900/30 rounded p-2 whitespace-pre-line">
                  <CitationRenderer
                    text={claim.evidence_with_citations.evidence}
                    citations={claim.evidence_with_citations.citations || []}
                    onCitationClick={(citation) => {
                      const url = `${BASE_DOCENT_PATH}/${fgId}/paired_transcript/${transcriptDiff.agent_run_1_id}___${transcriptDiff.agent_run_2_id}?block_id=${citation.block_idx}${citation.transcript_idx === 1 ? `&block_id_2=${citation.block_idx}` : ''}&claim_id=${claim.id}`;
                      router.push(url);
                    }}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
export default TranscriptDiffSummary;
