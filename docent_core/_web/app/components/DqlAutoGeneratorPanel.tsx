'use client';

import { useCallback, useMemo, useState, useEffect, useRef } from 'react';
import { History, Sparkles, Trash2 } from 'lucide-react';

import {
  useGenerateDqlMutation,
  useGetDqlSchemaQuery,
} from '@/app/api/collectionApi';
import { useGetChatModelsQuery } from '@/app/api/chatApi';
import {
  ChatArea,
  type SuggestedMessage,
} from '@/app/dashboard/[collection_id]/components/chat/ChatArea';
import {
  type DqlAutogenMessage,
  type DqlExecuteResponse,
  type DqlGenerateResponse,
} from '@/app/types/dqlTypes';
import type {
  ChatStateData,
  QueryHistoryEntry,
} from '@/app/types/dataTableTypes';
import ModelPicker from '@/components/ModelPicker';
import { ModelOption } from '@/app/store/rubricSlice';
import { type ChatMessage } from '@/app/types/transcriptTypes';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useDqlChat } from '@/hooks/use-dql-chat';

interface DqlAutoGeneratorPanelProps {
  dataTableId?: string;
  collectionId?: string;
  currentQuery: string;
  onQueryUpdate: (next: string) => void;
  onResultUpdate: (result: DqlExecuteResponse | null) => void;
  onErrorUpdate: (message: string | null) => void;
  pendingMessage?: string | null;
  onPendingMessageConsumed?: () => void;
  initialChatState?: ChatStateData | null;
  /** Signal that a query was manually executed by the user */
  executedQuery?: { query: string; key: number; rowCount?: number } | null;
}

type DiffRecord = { anchorIndex: number; message: ChatMessage };

const formatHistoryTimestamp = (isoString: string): string => {
  const date = new Date(isoString);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const truncateQuery = (query: string, maxLength = 200): string => {
  // Collapse all whitespace (newlines, tabs, multiple spaces) into single spaces
  const collapsed = query.replace(/\s+/g, ' ').trim();
  if (collapsed.length <= maxLength) return collapsed;
  return collapsed.slice(0, maxLength - 1) + '…';
};

const DEFAULT_DQL_MODEL: ModelOption = {
  provider: 'openai',
  model_name: 'gpt-4o-2024-08-06',
  reasoning_effort: null,
  context_window: 128000,
  uses_byok: false,
};

const DQL_MODEL_STORAGE_KEY_PREFIX = 'dql-assistant-model-';

const getStoredModel = (collectionId: string): ModelOption | null => {
  if (typeof window === 'undefined') return null;
  try {
    const stored = localStorage.getItem(
      `${DQL_MODEL_STORAGE_KEY_PREFIX}${collectionId}`
    );
    if (!stored) return null;
    return JSON.parse(stored) as ModelOption;
  } catch (_e) {
    return null;
  }
};

const storeModel = (collectionId: string, model: ModelOption): void => {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(
      `${DQL_MODEL_STORAGE_KEY_PREFIX}${collectionId}`,
      JSON.stringify(model)
    );
  } catch (_e) {
    // Ignore storage errors
  }
};

const computeUnifiedDiff = (
  before: string | null,
  after: string | null
): string | null => {
  if (!before || !after) return null;
  const a = before.split('\n');
  const b = after.split('\n');
  const m = a.length;
  const n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    Array(n + 1).fill(0)
  );
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] =
        a[i] === b[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const diffLines: string[] = ['--- before', '+++ after'];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      diffLines.push(` ${a[i]}`);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      diffLines.push(`-${a[i]}`);
      i++;
    } else {
      diffLines.push(`+${b[j]}`);
      j++;
    }
  }
  while (i < m) {
    diffLines.push(`-${a[i++]}`);
  }
  while (j < n) {
    diffLines.push(`+${b[j++]}`);
  }
  return diffLines.join('\n');
};

export const DqlAutoGeneratorPanel = ({
  dataTableId,
  collectionId,
  currentQuery,
  onQueryUpdate,
  onResultUpdate,
  onErrorUpdate,
  pendingMessage,
  onPendingMessageConsumed,
  initialChatState,
  executedQuery,
}: DqlAutoGeneratorPanelProps) => {
  const {
    chatState,
    addMessage,
    addResponse,
    addHistoryEntry,
    setError,
    handleClearChat,
  } = useDqlChat(dataTableId ?? null, collectionId ?? null, initialChatState);

  const messages = useMemo(
    () => chatState?.messages ?? [],
    [chatState?.messages]
  );
  const diffMessages = useMemo(
    () => chatState?.diffMessages ?? [],
    [chatState?.diffMessages]
  );
  const queryHistory = chatState?.queryHistory ?? [];
  const inputError = chatState?.inputError ?? null;
  const isLoading = chatState?.pendingRequestId !== null;

  const requestIdRef = useRef<number>(0);
  const [selectedModel, setSelectedModel] = useState<ModelOption | null>(() => {
    if (collectionId) {
      return getStoredModel(collectionId) ?? DEFAULT_DQL_MODEL;
    }
    return DEFAULT_DQL_MODEL;
  });
  const [generateDql] = useGenerateDqlMutation();
  const { data: schemaData } = useGetDqlSchemaQuery(collectionId ?? '', {
    skip: !collectionId,
  });
  const { data: availableModels } = useGetChatModelsQuery();

  const handleRestoreQuery = useCallback(
    (entry: QueryHistoryEntry) => {
      onQueryUpdate(entry.query);
      onResultUpdate(null);
      onErrorUpdate(null);
    },
    [onQueryUpdate, onResultUpdate, onErrorUpdate]
  );

  // Load stored model when collectionId changes
  useEffect(() => {
    if (!collectionId) return;
    const stored = getStoredModel(collectionId);
    if (stored) {
      setSelectedModel(stored);
    }
  }, [collectionId]);

  // Sync with available models to ensure selected model is valid
  useEffect(() => {
    if (!availableModels || availableModels.length === 0) {
      return;
    }
    if (!selectedModel) {
      const stored = collectionId ? getStoredModel(collectionId) : null;
      setSelectedModel(stored ?? availableModels[0]);
      return;
    }
    const matched = availableModels.find(
      (m) =>
        m.provider === selectedModel.provider &&
        m.model_name === selectedModel.model_name &&
        m.reasoning_effort === selectedModel.reasoning_effort
    );
    if (matched && matched !== selectedModel) {
      setSelectedModel(matched);
    }
  }, [availableModels, collectionId, selectedModel]);

  // Add to history when user manually executes a query
  const lastExecutedKeyRef = useRef<number | null>(null);
  useEffect(() => {
    if (!executedQuery || executedQuery.key === lastExecutedKeyRef.current) {
      return;
    }
    lastExecutedKeyRef.current = executedQuery.key;
    if (executedQuery.query.trim()) {
      addHistoryEntry(executedQuery.query, 'user', executedQuery.rowCount);
    }
  }, [executedQuery, addHistoryEntry]);

  // Persist model choice when it changes
  const handleModelChange = useCallback(
    (model: ModelOption | null) => {
      setSelectedModel(model);
      if (collectionId && model) {
        storeModel(collectionId, model);
      }
    },
    [collectionId]
  );

  const chatMessages: ChatMessage[] = useMemo(
    () =>
      messages.map((msg) => ({
        role: msg.role,
        content: msg.content,
      })) as ChatMessage[],
    [messages]
  );

  const createSuccessHandler = useCallback(
    (requestId: string, submittedQuery: string) =>
      (response: DqlGenerateResponse) => {
        const assistantText = response.assistant_message?.trim() ?? '';
        const generatedQuery = response.dql?.trim();

        if (!generatedQuery) {
          if (assistantText) {
            const assistantMessage: DqlAutogenMessage = {
              role: 'assistant',
              content: assistantText,
              query: '',
            };
            addResponse(assistantMessage, requestId);
            onErrorUpdate(null);
            return;
          }

          const errorText = (
            response.error || 'Model response did not include a DQL query.'
          ).trim();
          const assistantMessage: DqlAutogenMessage = {
            role: 'assistant',
            content: errorText,
            query: '',
          };
          addResponse(assistantMessage, requestId);
          onResultUpdate(null);
          onErrorUpdate(errorText);
          return;
        }

        const assistantMessage: DqlAutogenMessage = {
          role: 'assistant',
          content: assistantText || '',
          query: generatedQuery,
        };

        const diffContent = computeUnifiedDiff(
          submittedQuery ?? currentQuery,
          response.dql
        );

        const anchorIndex = messages.length;
        let diffRecord: DiffRecord | null = null;

        if (diffContent && diffContent.trim().length > 0) {
          const diffMessage = {
            role: 'assistant' as const,
            content: '',
            metadata: {
              diffContent,
              query: response.dql,
              previous_query: submittedQuery ?? currentQuery,
              execution: response.execution ?? null,
              error: response.error ?? null,
              used_tables: response.used_tables ?? [],
            },
          } as unknown as ChatMessage;
          diffRecord = { anchorIndex, message: diffMessage };
        }

        addResponse(assistantMessage, requestId, diffRecord);

        if (response.execution) {
          onQueryUpdate(generatedQuery);
          addHistoryEntry(
            generatedQuery,
            'agent',
            response.execution.row_count
          );
        }

        if (response.execution) {
          onResultUpdate(response.execution);
          onErrorUpdate(null);
        } else {
          onResultUpdate(null);
          onErrorUpdate(
            response.error ?? 'The generated query could not be executed.'
          );
        }
      },
    [
      addHistoryEntry,
      addResponse,
      currentQuery,
      messages.length,
      onErrorUpdate,
      onQueryUpdate,
      onResultUpdate,
    ]
  );

  const handleSendMessage = useCallback(
    (text: string) => {
      if (!collectionId || !dataTableId) {
        setError('Select a collection to generate DQL.');
        return;
      }

      if (currentQuery.trim()) {
        addHistoryEntry(currentQuery, 'user');
      }

      requestIdRef.current += 1;
      const requestId = `${dataTableId}-${requestIdRef.current}`;

      const userMessage: DqlAutogenMessage = { role: 'user', content: text };
      addMessage(userMessage, requestId, currentQuery);

      const nextMessages = [...messages, userMessage];

      generateDql({
        collectionId,
        messages: nextMessages.map((msg) => ({
          role: msg.role,
          content: msg.content,
          query: msg.query ?? undefined,
        })),
        current_query: currentQuery,
        model: selectedModel
          ? `${selectedModel.provider}/${selectedModel.model_name}`
          : `${DEFAULT_DQL_MODEL.provider}/${DEFAULT_DQL_MODEL.model_name}`,
      })
        .unwrap()
        .then(createSuccessHandler(requestId, currentQuery))
        .catch((error: unknown) => {
          const detail =
            (
              (error as { data?: { detail?: string } })?.data?.detail as
                | string
                | undefined
            )?.trim() || 'Failed to generate a DQL draft.';
          setError(detail, requestId);
          onErrorUpdate(detail);
        });
    },
    [
      addHistoryEntry,
      addMessage,
      collectionId,
      createSuccessHandler,
      currentQuery,
      dataTableId,
      generateDql,
      messages,
      onErrorUpdate,
      selectedModel,
      setError,
    ]
  );

  // Handle pending message from parent (e.g., "Fix with Agent" button)
  useEffect(() => {
    if (pendingMessage && !isLoading) {
      handleSendMessage(pendingMessage);
      onPendingMessageConsumed?.();
    }
  }, [pendingMessage, isLoading, handleSendMessage, onPendingMessageConsumed]);

  const hasUserStartedConversation = useMemo(
    () => messages.some((msg) => msg.role === 'user'),
    [messages]
  );

  const starterSuggestions: SuggestedMessage[] = useMemo(() => {
    if (hasUserStartedConversation || !schemaData) return [];

    const tables = schemaData.tables || [];
    const agentRuns = tables.find((t) => t.name.toLowerCase() === 'agent_runs');
    const judgeResults = tables.find(
      (t) => t.name.toLowerCase() === 'judge_results'
    );

    const suggestions: SuggestedMessage[] = [];

    if (agentRuns) {
      const agentRunCols = agentRuns.columns.map((c) => c.name);
      const lowerCols = agentRunCols.map((c) => c.toLowerCase());
      const hasCreatedAt = lowerCols.includes('created_at');
      const hasModel = lowerCols.includes('model');

      const displayCols: string[] = ['id'];
      if (hasModel) displayCols.push(agentRunCols[lowerCols.indexOf('model')]);
      if (hasCreatedAt)
        displayCols.push(agentRunCols[lowerCols.indexOf('created_at')]);

      const extra = agentRunCols.find(
        (c, idx) =>
          !['id', 'collection_id', 'created_at', 'model'].includes(
            lowerCols[idx]
          )
      );
      if (extra) {
        displayCols.push(extra);
      }

      suggestions.push(
        `List the latest 30 agent_runs with ${displayCols.join(
          ', '
        )} ordered by ${hasCreatedAt ? 'created_at' : 'id'}`
      );
    }

    if (agentRuns && judgeResults) {
      const hasRubricId = judgeResults.columns.some(
        (c) => c.name.toLowerCase() === 'rubric_id'
      );
      const hasOutput = judgeResults.columns.some(
        (c) => c.name.toLowerCase() === 'output'
      );
      if (hasRubricId && hasOutput) {
        suggestions.push(
          'Show rubric results with mode() to aggregate multiple rollouts per agent_run'
        );
        suggestions.push(
          'Compare rubric label distributions across agent_runs using mode()'
        );
      }
    }

    if (agentRuns) {
      const metadataCols = agentRuns.columns
        .filter((c) => c.name.toLowerCase().startsWith('metadata'))
        .map((c) => c.name);
      const someMetadata = metadataCols.find((c) =>
        c.toLowerCase().includes('locale')
      );
      if (someMetadata) {
        suggestions.push(
          `Filter agent_runs where ${someMetadata} = "en-US" and order by created_at desc`
        );
      }

      if (metadataCols.length > 0) {
        const firstMeta = metadataCols[0];
        suggestions.push(
          `List distinct ${firstMeta} values with counts from agent_runs`
        );
      }
    }

    return suggestions.slice(0, 3);
  }, [hasUserStartedConversation, schemaData]);

  const chatMessagesWithDiff = useMemo(() => {
    if (diffMessages.length === 0) {
      return chatMessages;
    }
    const grouped = new Map<number, ChatMessage[]>();
    diffMessages.forEach(({ anchorIndex, message }) => {
      const list = grouped.get(anchorIndex) ?? [];
      list.push(message);
      grouped.set(anchorIndex, list);
    });

    const output: ChatMessage[] = [];
    chatMessages.forEach((msg, idx) => {
      output.push(msg);
      const extras = grouped.get(idx);
      if (extras) {
        output.push(...extras);
      }
    });
    return output;
  }, [chatMessages, diffMessages]);

  const handleApplyQuery = useCallback(
    (q: string) => {
      onQueryUpdate(q);
      onResultUpdate(null);
      onErrorUpdate(null);
    },
    [onQueryUpdate, onResultUpdate, onErrorUpdate]
  );

  return (
    <div className="border rounded-lg h-full min-h-[620px] flex flex-col bg-background overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">DQL Assistant</span>
          <Badge variant="secondary" className="text-[11px] px-2">
            Beta
          </Badge>
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              onClick={handleClearChat}
              title="Clear chat"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
          {queryHistory.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0"
                  title="Query history"
                >
                  <History className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                className="max-w-lg max-h-72 overflow-y-auto"
              >
                {queryHistory.map((entry) => {
                  const sourceLabel =
                    entry.source === 'agent' ? 'Agent' : 'Manual';
                  return (
                    <DropdownMenuItem
                      key={entry.id}
                      onClick={() => handleRestoreQuery(entry)}
                      className="flex flex-col items-start gap-1 py-2.5"
                    >
                      <span className="text-xs font-medium truncate w-full">
                        {truncateQuery(entry.query)}
                      </span>
                      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                        <span>{formatHistoryTimestamp(entry.timestamp)}</span>
                        <span>·</span>
                        <span>{sourceLabel}</span>
                        {entry.lines !== undefined && entry.lines > 1 && (
                          <>
                            <span>·</span>
                            <span>{entry.lines} query lines</span>
                          </>
                        )}
                        {entry.rowCount !== undefined && (
                          <>
                            <span>·</span>
                            <span>{entry.rowCount} result rows</span>
                          </>
                        )}
                      </div>
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 flex flex-col px-3 py-2 overflow-hidden">
        <ChatArea
          isReadonly={!collectionId || isLoading}
          messages={chatMessagesWithDiff}
          onSendMessage={handleSendMessage}
          onApplyQuery={handleApplyQuery}
          isSendingMessage={isLoading}
          suggestedMessages={starterSuggestions}
          byoFlexDiv={true}
          inputAreaClassName="pt-2"
          scrollContainerClassName="px-1 py-2"
          inputErrorMessage={inputError}
          inputHeaderElement={
            <div className="text-xs text-muted-foreground pb-1">
              Ask for a query or request edits to the current one.
            </div>
          }
          inputAreaFooter={
            selectedModel ? (
              <div className="flex items-center justify-end w-full">
                <div className="w-56">
                  <ModelPicker
                    selectedModel={selectedModel}
                    availableModels={availableModels}
                    onChange={handleModelChange}
                    shortenName
                    borderless
                  />
                </div>
              </div>
            ) : null
          }
        />
      </div>
    </div>
  );
};

export default DqlAutoGeneratorPanel;
