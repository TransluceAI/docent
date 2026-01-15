'use client';

import React, { useMemo, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { Loader2, ChevronRight, MessageSquarePlus } from 'lucide-react';
import { ResultResponse, useGetResultQuery } from '@/app/api/resultSetApi';
import { PanelCitationProvider } from '@/components/sliding-panels';
import {
  MarkdownWithCitations,
  TextWithCitations,
  hasTextWithCitations,
} from '@/components/CitationRenderer';
import { InlineCitation } from '@/app/types/citationTypes';
import { MetadataBlock } from '@/components/metadata/MetadataBlock';
import { BaseMetadata } from '@/app/types/transcriptTypes';
import {
  LLMContextSpec,
  useCreateFollowupFromResultMutation,
} from '@/app/api/chatApi';
import { cn } from '@/lib/utils';
import { useCitationNavigation } from '@/providers/CitationNavigationProvider';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import {
  SerializedContextItem,
  resolveAliasToContextItem,
  makeSyntheticCitation,
  formatContextGroupSummary,
  ContextItemCard,
} from '@/components/context-items';

function isPending(result: ResultResponse): boolean {
  return result.output === null && result.error_json === null;
}

function isPlainJsonObject(output: unknown): output is Record<string, unknown> {
  return (
    typeof output === 'object' &&
    output !== null &&
    !Array.isArray(output) &&
    !(
      'citations' in output &&
      Array.isArray((output as { citations: unknown }).citations) &&
      'output' in output
    )
  );
}

function JsonObjectDisplay({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="space-y-2">
      {Object.entries(data).map(([key, value]) => (
        <div key={key} className="text-xs">
          <span className="font-semibold">{key}:</span>{' '}
          {hasTextWithCitations(value) ? (
            <TextWithCitations text={value.text} citations={value.citations} />
          ) : typeof value === 'string' ? (
            <span className="whitespace-pre-wrap">{value}</span>
          ) : typeof value === 'number' || typeof value === 'boolean' ? (
            <span>{String(value)}</span>
          ) : value === null ? (
            <span className="text-muted-foreground">null</span>
          ) : (
            <span className="whitespace-pre-wrap">
              {JSON.stringify(value, null, 2)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

type SegmentGroup =
  | { type: 'text'; content: string }
  | { type: 'context'; items: SerializedContextItem[] };

function groupSegments(
  segments: (string | { alias: string })[],
  contextSpec: LLMContextSpec | undefined
): SegmentGroup[] {
  const groups: SegmentGroup[] = [];
  const itemsByAlias = contextSpec?.items || {};

  for (const segment of segments) {
    const alias =
      typeof segment === 'object' && 'alias' in segment ? segment.alias : null;

    if (alias && alias in itemsByAlias) {
      const item = resolveAliasToContextItem(alias, contextSpec);
      if (!item) continue;

      const lastGroup = groups[groups.length - 1];
      if (lastGroup && lastGroup.type === 'context') {
        lastGroup.items.push(item);
      } else {
        groups.push({ type: 'context', items: [item] });
      }
    } else {
      const text = typeof segment === 'string' ? segment : String(segment);
      const lastGroup = groups[groups.length - 1];
      if (lastGroup && lastGroup.type === 'text') {
        lastGroup.content += text;
      } else {
        groups.push({ type: 'text', content: text });
      }
    }
  }

  return groups;
}

function ContextGroupAccordion({
  items,
  onItemClick,
}: {
  items: SerializedContextItem[];
  onItemClick: (item: SerializedContextItem) => void;
}) {
  const [isExpanded, setIsExpanded] = React.useState(false);
  const summary = formatContextGroupSummary(items);

  return (
    <div className="rounded border border-indigo-border bg-indigo-bg/50">
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-xs text-indigo-text hover:bg-indigo-muted/50 transition-colors"
      >
        <ChevronRight
          className={cn(
            'h-3 w-3 transition-transform',
            isExpanded ? 'rotate-90' : ''
          )}
        />
        <span className="font-medium">{summary}</span>
      </button>
      {isExpanded && (
        <div className="flex flex-col gap-1.5 px-2 pb-2">
          {items.map((item, idx) => (
            <ContextItemCard
              key={`${item.alias}-${idx}`}
              item={item}
              onItemClick={onItemClick}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function PromptSegmentsDisplay({
  segments,
  contextSpec,
}: {
  segments: (string | { alias: string })[];
  contextSpec: LLMContextSpec | undefined;
}) {
  const citationNav = useCitationNavigation();

  const groups = useMemo(
    () => groupSegments(segments, contextSpec),
    [segments, contextSpec]
  );

  const handleItemClick = useCallback(
    (item: SerializedContextItem) => {
      const syntheticTarget = makeSyntheticCitation(item);
      if (!syntheticTarget || !citationNav) return;

      citationNav.navigateToCitation({
        target: syntheticTarget,
        source: 'result_detail_context',
      });
    },
    [citationNav]
  );

  return (
    <div className="space-y-2">
      {groups.map((group, idx) => {
        if (group.type === 'text') {
          return (
            <span key={idx} className="whitespace-pre-wrap">
              {group.content}
            </span>
          );
        }

        if (group.items.length === 1) {
          return (
            <ContextItemCard
              key={idx}
              item={group.items[0]}
              onItemClick={handleItemClick}
            />
          );
        }

        return (
          <ContextGroupAccordion
            key={idx}
            items={group.items}
            onItemClick={handleItemClick}
          />
        );
      })}
    </div>
  );
}

interface ResultDetailContentProps {
  result: ResultResponse;
  hasActiveJob: boolean;
}

export function ResultDetailContent({
  result,
  hasActiveJob,
}: ResultDetailContentProps) {
  const params = useParams();
  const collectionId = params.collection_id as string | undefined;
  const showPendingState = isPending(result) && hasActiveJob;
  const [isPromptExpanded, setIsPromptExpanded] = React.useState(true);
  const [createFollowup, { isLoading: isCreatingFollowup }] =
    useCreateFollowupFromResultMutation();

  const contextSpec = result.llm_context_spec as LLMContextSpec | undefined;

  const canFollowup = Boolean(collectionId) && Boolean(result.output);

  const handleFollowup = async () => {
    if (!collectionId) return;
    if (!result.output) return;

    try {
      const res = await createFollowup({
        collectionId,
        resultId: result.id,
      }).unwrap();
      window.open(
        `/dashboard/${collectionId}/chat/${res.session_id}`,
        '_blank',
        'noopener,noreferrer'
      );
    } catch (err) {
      console.error('Failed to create followup chat', err);
      toast.error('Failed to create followup chat');
    }
  };

  return (
    <div className="p-4 space-y-3">
      {/* Prompt */}
      <div className="space-y-2">
        <button
          type="button"
          onClick={() => setIsPromptExpanded(!isPromptExpanded)}
          className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground hover:text-primary transition-colors"
        >
          <ChevronRight
            className={cn(
              'h-3 w-3 transition-transform',
              isPromptExpanded ? 'rotate-90' : ''
            )}
          />
          Prompt
        </button>
        {isPromptExpanded && (
          <div className="text-xs bg-secondary p-2 rounded">
            <PromptSegmentsDisplay
              segments={result.prompt_segments}
              contextSpec={contextSpec}
            />
          </div>
        )}
      </div>

      {/* Output */}
      {showPendingState ? (
        <div>
          <div className="text-xs text-muted-foreground mb-1">Output</div>
          <div className="text-xs bg-secondary p-2 rounded flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            <span className="text-muted-foreground">Processing...</span>
          </div>
        </div>
      ) : result.output ? (
        <div>
          <div className="text-xs text-muted-foreground mb-1">Output</div>
          <div className="text-xs bg-secondary p-2 rounded">
            {(() => {
              if (
                typeof result.output === 'object' &&
                result.output !== null &&
                'citations' in result.output &&
                Array.isArray(result.output.citations)
              ) {
                const outputText =
                  'output' in result.output &&
                  typeof result.output.output === 'string'
                    ? result.output.output
                    : typeof result.output === 'object'
                      ? JSON.stringify(result.output, null, 2)
                      : String(result.output);
                const citations = (result.output.citations ||
                  []) as InlineCitation[];
                return (
                  <MarkdownWithCitations
                    text={outputText}
                    citations={citations}
                  />
                );
              }
              if (isPlainJsonObject(result.output)) {
                return <JsonObjectDisplay data={result.output} />;
              }
              return (
                <span className="whitespace-pre-wrap">
                  {String(result.output)}
                </span>
              );
            })()}
          </div>
        </div>
      ) : null}

      {/* Error */}
      {result.error_json && (
        <div>
          <div className="text-xs text-muted-foreground mb-1">Error</div>
          <MetadataBlock
            metadata={result.error_json as unknown as BaseMetadata}
            showSearchControls={false}
          />
        </div>
      )}

      {/* Model & Tokens */}
      {(result.model ||
        result.input_tokens !== null ||
        result.output_tokens !== null ||
        result.cost_cents !== null) && (
        <div>
          <div className="text-xs text-muted-foreground mb-1">Usage & Cost</div>
          <div className="bg-secondary rounded-lg border border-border overflow-hidden">
            <table className="w-full text-xs">
              <tbody>
                {result.model && (
                  <tr className="border-b border-border">
                    <td className="px-3 py-2 font-medium text-primary w-1/3">
                      Model
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {result.model}
                    </td>
                  </tr>
                )}
                {result.input_tokens !== null && (
                  <tr className="border-b border-border">
                    <td className="px-3 py-2 font-medium text-primary w-1/3">
                      Input Tokens
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {result.input_tokens.toLocaleString()}
                    </td>
                  </tr>
                )}
                {result.output_tokens !== null && (
                  <tr
                    className={
                      result.cost_cents !== null &&
                      result.cost_cents !== undefined &&
                      typeof result.cost_cents === 'number' &&
                      !isNaN(result.cost_cents)
                        ? 'border-b border-border'
                        : ''
                    }
                  >
                    <td className="px-3 py-2 font-medium text-primary w-1/3">
                      Output Tokens
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {result.output_tokens.toLocaleString()}
                    </td>
                  </tr>
                )}
                {result.cost_cents !== null &&
                  result.cost_cents !== undefined &&
                  typeof result.cost_cents === 'number' &&
                  !isNaN(result.cost_cents) && (
                    <tr>
                      <td className="px-3 py-2 font-medium text-primary w-1/3">
                        Cost
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        ${(result.cost_cents / 100).toFixed(4)}
                      </td>
                    </tr>
                  )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Metadata */}
      {result.user_metadata && (
        <div>
          <div className="text-xs text-muted-foreground mb-1">Metadata</div>
          <MetadataBlock
            metadata={result.user_metadata as unknown as BaseMetadata}
            showSearchControls={false}
          />
        </div>
      )}

      {canFollowup && (
        <Button
          type="button"
          variant="outline"
          className="w-full gap-2"
          onClick={handleFollowup}
          disabled={showPendingState || isCreatingFollowup}
        >
          {isCreatingFollowup ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <MessageSquarePlus className="h-4 w-4" />
          )}
          Followup chat
        </Button>
      )}
    </div>
  );
}

interface ResultDetailPanelContentProps {
  result: ResultResponse;
  hasActiveJob: boolean;
  panelId: string;
}

export function ResultDetailPanelContent({
  result,
  hasActiveJob,
  panelId,
}: ResultDetailPanelContentProps) {
  return (
    <PanelCitationProvider panelId={panelId}>
      <ResultDetailContent result={result} hasActiveJob={hasActiveJob} />
    </PanelCitationProvider>
  );
}

interface ResultDetailPanelContentByIdProps {
  resultId: string;
  collectionId: string;
  hasActiveJob: boolean;
  panelId: string;
}

export function ResultDetailPanelContentById({
  resultId,
  collectionId,
  hasActiveJob,
  panelId,
}: ResultDetailPanelContentByIdProps) {
  const {
    data: result,
    isLoading,
    error,
  } = useGetResultQuery({
    collectionId,
    resultId,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={16} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !result) {
    return (
      <div className="p-4 text-red-text text-sm">Failed to load result</div>
    );
  }

  return (
    <PanelCitationProvider panelId={panelId}>
      <ResultDetailContent result={result} hasActiveJob={hasActiveJob} />
    </PanelCitationProvider>
  );
}
