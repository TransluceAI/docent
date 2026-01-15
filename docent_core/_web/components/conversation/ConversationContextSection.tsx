'use client';

import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { ChevronRight, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useCitationNavigation } from '@/providers/CitationNavigationProvider';
import {
  LLMContextSpec,
  useAddConversationContextItemMutation,
  useLazyLookupConversationItemQuery,
  useRemoveConversationContextItemMutation,
  useUpdateConversationContextSelectionMutation,
} from '@/app/api/chatApi';
import { resultSetApi } from '@/app/api/resultSetApi';
import { useAppDispatch } from '@/app/store/hooks';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  SerializedContextItem,
  parseContextSerialized,
  makeSyntheticCitation,
  getItemKey,
  isItemSelected,
  ContextItemCard,
} from '@/components/context-items';

interface ConversationContextSectionProps {
  contextSerialized?: LLMContextSpec;
  sessionId: string | null;
  itemTokenEstimates?: Record<string, number> | null;
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

  const resultSetIdsWithCollection = useMemo(() => {
    const resultSetMap = new Map<
      string,
      { resultSetId: string; collectionId: string }
    >();
    for (const item of items) {
      if (item.type === 'result_set') {
        resultSetMap.set(item.id, {
          resultSetId: item.id,
          collectionId: item.collection_id,
        });
      } else if (item.type === 'analysis_result') {
        if (!resultSetMap.has(item.result_set_id)) {
          resultSetMap.set(item.result_set_id, {
            resultSetId: item.result_set_id,
            collectionId: item.collection_id,
          });
        }
      }
    }
    return Array.from(resultSetMap.values());
  }, [items]);

  const dispatch = useAppDispatch();
  const [resultSetNames, setResultSetNames] = useState<
    Map<string, string | null>
  >(new Map());

  useEffect(() => {
    if (resultSetIdsWithCollection.length === 0) {
      setResultSetNames(new Map());
      return;
    }

    const fetchNames = async () => {
      const nameMap = new Map<string, string | null>();
      const promises = resultSetIdsWithCollection.map(
        async ({ resultSetId, collectionId }) => {
          try {
            const result = await dispatch(
              resultSetApi.endpoints.getResultSet.initiate({
                collectionId,
                resultSetIdOrName: resultSetId,
              })
            ).unwrap();
            nameMap.set(resultSetId, result.name ?? null);
          } catch {
            nameMap.set(resultSetId, null);
          }
        }
      );
      await Promise.all(promises);
      setResultSetNames(nameMap);
    };

    fetchNames();
  }, [resultSetIdsWithCollection, dispatch]);

  const {
    agentRunCount,
    transcriptCount,
    resultSetCount,
    analysisResultCount,
  } = useMemo(() => {
    let agentRuns = 0;
    let transcripts = 0;
    let resultSets = 0;
    let analysisResults = 0;
    for (const item of items) {
      if (item.type === 'agent_run' || item.type === 'formatted_agent_run') {
        agentRuns++;
      } else if (
        item.type === 'transcript' ||
        item.type === 'formatted_transcript'
      ) {
        transcripts++;
      } else if (item.type === 'result_set') {
        resultSets++;
      } else if (item.type === 'analysis_result') {
        analysisResults++;
      }
    }
    return {
      agentRunCount: agentRuns,
      transcriptCount: transcripts,
      resultSetCount: resultSets,
      analysisResultCount: analysisResults,
    };
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
              {(agentRunCount > 0 ||
                transcriptCount > 0 ||
                resultSetCount > 0 ||
                analysisResultCount > 0) && (
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
                  {resultSetCount > 0 && (
                    <span className="rounded-full bg-indigo-muted px-2 py-0.5 text-[10px] uppercase text-indigo-text">
                      {resultSetCount}{' '}
                      {resultSetCount === 1 ? 'result set' : 'result sets'}
                    </span>
                  )}
                  {analysisResultCount > 0 && (
                    <span className="rounded-full bg-indigo-muted px-2 py-0.5 text-[10px] uppercase text-indigo-text">
                      {analysisResultCount}{' '}
                      {analysisResultCount === 1
                        ? 'analysis result'
                        : 'analysis results'}
                    </span>
                  )}
                </span>
              )}
            </button>
            {isExpanded && (
              <div className="flex flex-col gap-2">
                {items.map((item, index) => (
                  <ContextItemCard
                    key={getItemKey(item, index)}
                    item={item}
                    isSelected={isItemSelected(item, selectedCitation)}
                    tokenEstimate={itemTokenEstimates?.[item.alias]}
                    onItemClick={() =>
                      handleContextSelect(getItemKey(item, index))
                    }
                    onRemove={
                      sessionId ? () => handleRemove(item.id) : undefined
                    }
                    isRemoving={removingId === item.id}
                    onToggleVisible={
                      sessionId ? () => handleToggleVisible(item) : undefined
                    }
                    resultSetNames={resultSetNames}
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
