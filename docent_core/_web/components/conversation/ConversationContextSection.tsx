'use client';

import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { ChevronRight, X, Plus, Eye, EyeOff } from 'lucide-react';
import { cn, formatTokenCount } from '@/lib/utils';
import { useCitationNavigation } from '@/providers/CitationNavigationProvider';
import { CitationTarget } from '@/app/types/citationTypes';
import {
  LLMContextSpec,
  useAddConversationContextItemMutation,
  useLazyLookupConversationItemQuery,
  useRemoveConversationContextItemMutation,
  useUpdateConversationContextSelectionMutation,
} from '@/app/api/chatApi';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';

type AgentRunContextItem = {
  type: 'agent_run';
  id: string;
  alias: string;
  transcript_ids: string[];
  collection_id: string;
  visible: boolean;
};

type FormattedAgentRunContextItem = {
  type: 'formatted_agent_run';
  id: string;
  alias: string;
  transcript_ids: string[];
  collection_id: string;
  visible: boolean;
};

type TranscriptContextItem = {
  type: 'transcript';
  id: string;
  alias: string;
  collection_id: string;
  agent_run_id: string;
  visible: boolean;
};

type FormattedTranscriptContextItem = {
  type: 'formatted_transcript';
  id: string;
  alias: string;
  collection_id: string;
  agent_run_id: string;
  visible: boolean;
};

type SerializedContextItem =
  | AgentRunContextItem
  | FormattedAgentRunContextItem
  | TranscriptContextItem
  | FormattedTranscriptContextItem;

interface ConversationContextSectionProps {
  contextSerialized?: LLMContextSpec;
  sessionId: string | null;
  itemTokenEstimates?: Record<string, number> | null;
}

function shortUUID(uuid: string): string {
  return uuid.split('-')[0];
}

// Convert data sent by the server into a format that's convenient to render
function parseContextSerialized(
  contextSerialized: LLMContextSpec | undefined
): SerializedContextItem[] {
  if (!contextSerialized) {
    return [];
  }

  const version = contextSerialized.version;
  const supportedVersion = version === '3';
  if (!supportedVersion && version !== undefined) {
    console.warn(
      `Unsupported context serialization version: ${contextSerialized.version}`
    );
    return [];
  }

  const rootItems = contextSerialized.root_items || [];
  const itemsByAlias = contextSerialized.items || {};
  const inlineData = contextSerialized.inline_data || {};

  const agent_run_to_transcripts: Record<string, string[]> = {};

  for (const alias in itemsByAlias) {
    const ref = itemsByAlias[alias];
    if (ref.type !== 'transcript') {
      continue;
    }
    const agentRunId = ref.agent_run_id;
    if (!agent_run_to_transcripts[agentRunId]) {
      agent_run_to_transcripts[agentRunId] = [];
    }
    agent_run_to_transcripts[agentRunId].push(ref.id);
  }

  const items: SerializedContextItem[] = [];
  const visibilityMap = contextSerialized.visibility || {};

  for (const rootItem of rootItems) {
    const ref = itemsByAlias[rootItem];
    if (!ref) {
      continue;
    }

    if (ref.type === 'agent_run') {
      const agentRunId = ref.id;
      const collectionId = ref.collection_id;
      const item: AgentRunContextItem | FormattedAgentRunContextItem = {
        type: inlineData[agentRunId] ? 'formatted_agent_run' : 'agent_run',
        id: agentRunId,
        alias: rootItem,
        transcript_ids: agent_run_to_transcripts[agentRunId] || [],
        collection_id: collectionId,
        visible: visibilityMap[rootItem] !== false,
      };

      items.push(item);
    } else if (ref.type === 'transcript') {
      const transcriptId = ref.id;
      const agentRunId = ref.agent_run_id;
      const collectionId = ref.collection_id;
      const item: TranscriptContextItem | FormattedTranscriptContextItem = {
        type: inlineData[transcriptId] ? 'formatted_transcript' : 'transcript',
        id: transcriptId,
        alias: rootItem,
        collection_id: collectionId,
        agent_run_id: agentRunId,
        visible: visibilityMap[rootItem] !== false,
      };
      items.push(item);
    }
  }

  return items;
}

function getItemKey(item: SerializedContextItem, index: number): string {
  switch (item.type) {
    case 'agent_run':
      return `agent-run-${index}-${item.id}`;
    case 'formatted_agent_run':
      return `formatted-agent-run-${index}-${item.id}`;
    case 'transcript':
      return `transcript-${index}-${item.id}`;
    case 'formatted_transcript':
      return `formatted-transcript-${index}-${item.id}`;
  }
}

function isItemSelected(
  item: SerializedContextItem,
  selectedCitation: CitationTarget | null
): boolean {
  if (!selectedCitation) {
    return false;
  }

  const citationItem = selectedCitation.item;

  switch (item.type) {
    case 'agent_run':
    case 'formatted_agent_run':
      return item.id === citationItem.agent_run_id;
    case 'transcript':
    case 'formatted_transcript':
      return (
        'transcript_id' in citationItem &&
        item.id === citationItem.transcript_id
      );
  }
}

function makeSyntheticCitation(
  item: SerializedContextItem
): CitationTarget | undefined {
  switch (item.type) {
    case 'agent_run':
    case 'formatted_agent_run': {
      const firstTranscriptId = item.transcript_ids[0];
      if (!firstTranscriptId) {
        return undefined;
      }
      return {
        item: {
          item_type: 'block_content',
          agent_run_id: item.id,
          collection_id: item.collection_id,
          transcript_id: firstTranscriptId,
          block_idx: 0,
        },
        text_range: null,
      };
    }
    case 'transcript':
    case 'formatted_transcript':
      return {
        item: {
          item_type: 'block_content',
          agent_run_id: item.agent_run_id,
          collection_id: item.collection_id,
          transcript_id: item.id,
          block_idx: 0,
        },
        text_range: null,
      };
  }
}

function ContextItem({
  item,
  index,
  isSelected,
  tokenEstimate,
  onSelect,
  onRemove,
  isRemoving,
  onToggleVisible,
}: {
  item: SerializedContextItem;
  index: number;
  isSelected: boolean;
  tokenEstimate?: number;
  onSelect: (key: string) => void;
  onRemove?: () => void;
  isRemoving?: boolean;
  onToggleVisible?: () => void;
}) {
  const key = getItemKey(item, index);

  let badge: string;
  let title: string;
  let subtitle: string | undefined;

  switch (item.type) {
    case 'agent_run':
    case 'formatted_agent_run': {
      const transcriptCount = item.transcript_ids.length;
      const transcriptLabel =
        transcriptCount === 1
          ? '1 transcript'
          : `${transcriptCount} transcripts`;
      badge =
        item.type === 'formatted_agent_run'
          ? 'Formatted Agent Run'
          : 'Agent Run';
      title = `Agent Run ${shortUUID(item.id)}`;
      subtitle = transcriptLabel;
      break;
    }
    case 'transcript':
    case 'formatted_transcript': {
      badge =
        item.type === 'formatted_transcript'
          ? 'Formatted Transcript'
          : 'Transcript';
      title = `Transcript ${shortUUID(item.id)}`;
      break;
    }
  }

  return (
    <div className="flex items-start gap-2">
      <button
        className={cn(
          'flex flex-1 items-center gap-2 rounded-md border px-3 py-2 text-left transition-colors',
          isSelected
            ? 'border-indigo-border bg-indigo-muted text-primary'
            : 'border-border bg-background text-muted-foreground hover:bg-indigo-muted/40 hover:text-primary',
          !item.visible && 'opacity-50'
        )}
        onClick={() => {
          onSelect(key);
        }}
      >
        <div className="flex flex-1 flex-col">
          <div className="flex flex-row items-center gap-2">
            <span className="font-medium text-sm">{title}</span>
            <span className="rounded-full bg-indigo-muted px-2 py-0.5 text-[10px] uppercase text-indigo-text">
              {badge}
            </span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {tokenEstimate !== undefined && (
              <span className="text-xs text-muted-foreground">
                {formatTokenCount(tokenEstimate)} tokens
              </span>
            )}
            {subtitle && (
              <span>
                {' | '} {subtitle}
              </span>
            )}
          </div>
        </div>
        {onToggleVisible && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleVisible();
                }}
              >
                {item.visible ? (
                  <Eye className="h-4 w-4" />
                ) : (
                  <EyeOff className="h-4 w-4" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>{item.visible ? 'Hide from context' : 'Show in context'}</p>
            </TooltipContent>
          </Tooltip>
        )}
        {onRemove && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={(e) => {
                  e.stopPropagation();
                  onRemove();
                }}
                disabled={isRemoving}
              >
                <X className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>Remove from context</p>
            </TooltipContent>
          </Tooltip>
        )}
      </button>
    </div>
  );
}

export function ConversationContextSection({
  contextSerialized,
  sessionId,
  itemTokenEstimates,
}: ConversationContextSectionProps) {
  const citationNav = useCitationNavigation();
  const selectedCitation = citationNav?.selectedCitation ?? null;
  const [isExpanded, setIsExpanded] = useState(true);
  const [isAdding, setIsAdding] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookedUpItemId, setLookedUpItemId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const [lookupItem, { data: lookupData, isFetching: isLookupLoading }] =
    useLazyLookupConversationItemQuery();
  const [addItem, { isLoading: isAddingItem }] =
    useAddConversationContextItemMutation();
  const [removeItem] = useRemoveConversationContextItemMutation();
  const [updateContextItem, { isLoading: isUpdatingItem }] =
    useUpdateConversationContextSelectionMutation();

  const items = useMemo(
    () => parseContextSerialized(contextSerialized),
    [contextSerialized]
  );

  const { agentRunCount, transcriptCount } = useMemo(() => {
    let agentRuns = 0;
    let transcripts = 0;
    for (const item of items) {
      if (item.type === 'agent_run' || item.type === 'formatted_agent_run') {
        agentRuns++;
      } else if (
        item.type === 'transcript' ||
        item.type === 'formatted_transcript'
      ) {
        transcripts++;
      }
    }
    return { agentRunCount: agentRuns, transcriptCount: transcripts };
  }, [items]);

  const isValidLookupData = useMemo(() => {
    if (!lookupData || !lookedUpItemId) return false;
    return (
      lookupData.item_id === lookedUpItemId &&
      inputValue.trim() === lookedUpItemId
    );
  }, [lookupData, lookedUpItemId, inputValue]);

  useEffect(() => {
    if (isAdding && lookedUpItemId && inputValue.trim() !== lookedUpItemId) {
      setLookedUpItemId(null);
      setLookupError(null);
    }
  }, [inputValue, lookedUpItemId, isAdding]);

  const handleContextSelect = useCallback(
    (key: string) => {
      const targetItem = items.find(
        (item, index) => getItemKey(item, index) === key
      );
      if (!targetItem) return;

      const syntheticTarget = makeSyntheticCitation(targetItem);
      if (!syntheticTarget || !citationNav) return;

      citationNav.navigateToCitation({
        target: syntheticTarget,
        source: 'conversation_context',
      });
    },
    [items, citationNav]
  );

  const handleStartAdd = useCallback(() => {
    setIsAdding(true);
    setLookupError(null);
    setLookedUpItemId(null);
    setInputValue('');
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const handleLookup = useCallback(
    (value: string) => {
      if (!value) return;
      const trimmed = value.trim();
      setLookupError(null);
      lookupItem({ itemId: trimmed })
        .unwrap()
        .then(() => {
          setLookedUpItemId(trimmed);
        })
        .catch((err: any) => {
          setLookedUpItemId(null);
          setLookupError(
            err?.data?.detail || 'Could not find that ID. Check and try again.'
          );
        });
    },
    [lookupItem]
  );

  const handlePaste = useCallback(
    (event: React.ClipboardEvent<HTMLInputElement>) => {
      const pasted = event.clipboardData.getData('text');
      const trimmed = pasted.trim();
      if (!trimmed) return;
      event.preventDefault();
      setInputValue(trimmed);
      handleLookup(trimmed);
    },
    [handleLookup]
  );

  const handleCancel = useCallback(() => {
    setIsAdding(false);
    setInputValue('');
    setLookupError(null);
    setLookedUpItemId(null);
  }, []);

  const handleConfirmAdd = useCallback(async () => {
    if (!sessionId || !isValidLookupData || !lookupData) return;
    try {
      await addItem({ sessionId, itemId: lookupData.item_id }).unwrap();
      setIsAdding(false);
      setInputValue('');
      setLookupError(null);
      setLookedUpItemId(null);
    } catch (err: any) {
      setLookupError(err?.data?.detail || 'Failed to add item.');
    }
  }, [sessionId, isValidLookupData, lookupData, addItem]);

  const handleRemove = useCallback(
    async (itemId: string) => {
      if (!sessionId) return;
      setRemovingId(itemId);
      try {
        await removeItem({ sessionId, itemId }).unwrap();
      } catch (err) {
        // leave minimal error handling to console to keep UI light
        console.error('Failed to remove context item', err);
      } finally {
        setRemovingId(null);
      }
    },
    [removeItem, sessionId]
  );

  const handleToggleVisible = useCallback(
    async (item: SerializedContextItem) => {
      if (!sessionId) return;
      try {
        await updateContextItem({
          sessionId,
          itemId: item.id,
          visible: !item.visible,
        }).unwrap();
      } catch (err) {
        console.error('Failed to toggle visibility', err);
      }
    },
    [sessionId, updateContextItem]
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1"></div>
      </div>
      {sessionId && (
        <div>
          <div className="space-y-3">
            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground hover:text-primary transition-colors"
            >
              <ChevronRight
                className={cn(
                  'h-3 w-3 transition-transform',
                  isExpanded ? 'rotate-90' : ''
                )}
              />
              Context
              {(agentRunCount > 0 || transcriptCount > 0) && (
                <span
                  className={cn(
                    'flex items-center gap-2 transition-opacity',
                    isExpanded ? 'opacity-0 pointer-events-none' : 'opacity-100'
                  )}
                >
                  {agentRunCount > 0 && (
                    <span className="rounded-full bg-indigo-muted px-2 py-0.5 text-[10px] uppercase text-indigo-text">
                      {agentRunCount}{' '}
                      {agentRunCount === 1 ? 'agent run' : 'agent runs'}
                    </span>
                  )}
                  {transcriptCount > 0 && (
                    <span className="rounded-full bg-indigo-muted px-2 py-0.5 text-[10px] uppercase text-indigo-text">
                      {transcriptCount}{' '}
                      {transcriptCount === 1 ? 'transcript' : 'transcripts'}
                    </span>
                  )}
                </span>
              )}
            </button>
            {isExpanded && (
              <div className="flex flex-col gap-2">
                {items.map((item, index) => (
                  <ContextItem
                    key={getItemKey(item, index)}
                    item={item}
                    index={index}
                    isSelected={isItemSelected(item, selectedCitation)}
                    tokenEstimate={itemTokenEstimates?.[item.alias]}
                    onSelect={handleContextSelect}
                    onRemove={
                      sessionId ? () => handleRemove(item.id) : undefined
                    }
                    isRemoving={removingId === item.id}
                    onToggleVisible={
                      sessionId ? () => handleToggleVisible(item) : undefined
                    }
                  />
                ))}
                {!isAdding ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full gap-2"
                    onClick={handleStartAdd}
                  >
                    <Plus className="h-4 w-4" />
                    Add item
                  </Button>
                ) : (
                  <form
                    className="flex flex-col gap-2 border rounded-md p-3"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (isValidLookupData && !isAddingItem) {
                        handleConfirmAdd();
                      } else if (inputValue.trim()) {
                        handleLookup(inputValue.trim());
                      }
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <Input
                        ref={inputRef}
                        placeholder="Paste transcript or agent run UUID"
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        onPaste={handlePaste}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') {
                            handleCancel();
                          }
                        }}
                        className="flex-1"
                      />
                      {isValidLookupData && !isLookupLoading && lookupData && (
                        <span className="rounded-full bg-indigo-muted px-2 py-0.5 text-[10px] uppercase text-indigo-text whitespace-nowrap">
                          {lookupData.item_type === 'agent_run'
                            ? 'Agent Run'
                            : lookupData.item_type === 'transcript'
                              ? 'Transcript'
                              : 'Unknown'}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      {isLookupLoading && <span>Looking up…</span>}
                      {lookupError && (
                        <span className="text-destructive">{lookupError}</span>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <Button
                        type="submit"
                        size="sm"
                        disabled={!isValidLookupData || isAddingItem}
                      >
                        {isAddingItem ? 'Adding…' : 'Add'}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={handleCancel}
                      >
                        Cancel
                      </Button>
                    </div>
                  </form>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
