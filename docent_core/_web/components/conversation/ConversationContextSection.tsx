'use client';

import { useState, useCallback, useMemo } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useCitationNavigation } from '@/providers/CitationNavigationProvider';
import { CitationTarget } from '@/app/types/citationTypes';
import { ContextSerialized } from '@/app/api/chatApi';

type AgentRunContextItem = {
  type: 'agent_run';
  id: string;
  transcript_ids: string[];
  collection_id: string;
};

type FormattedAgentRunContextItem = {
  type: 'formatted_agent_run';
  id: string;
  transcript_ids: string[];
  collection_id: string;
};

type TranscriptContextItem = {
  type: 'transcript';
  id: string;
  collection_id: string;
  agent_run_id: string;
};

type FormattedTranscriptContextItem = {
  type: 'formatted_transcript';
  id: string;
  collection_id: string;
  agent_run_id: string;
};

type SerializedContextItem =
  | AgentRunContextItem
  | FormattedAgentRunContextItem
  | TranscriptContextItem
  | FormattedTranscriptContextItem;

interface ConversationContextSectionProps {
  contextSerialized?: ContextSerialized;
}

function shortUUID(uuid: string): string {
  return uuid.split('-')[0];
}

// Convert data sent by the server into a format that's convenient to render
function parseContextSerialized(
  contextSerialized: ContextSerialized | undefined
): SerializedContextItem[] {
  if (!contextSerialized) {
    return [];
  }

  if (contextSerialized.version !== '1') {
    console.warn(
      `Unsupported context serialization version: ${contextSerialized.version}`
    );
    return [];
  }

  const agent_run_to_transcripts: Record<string, string[]> = {};

  for (const transcriptId in contextSerialized.transcript_to_agent_run) {
    const agentRunId = contextSerialized.transcript_to_agent_run[transcriptId];
    if (!agent_run_to_transcripts[agentRunId]) {
      agent_run_to_transcripts[agentRunId] = [];
    }
    agent_run_to_transcripts[agentRunId].push(transcriptId);
  }

  const items: SerializedContextItem[] = [];

  for (const rootItem of contextSerialized.root_items) {
    if (rootItem.startsWith('R')) {
      const aliasKey = rootItem.substring(1);
      const agentRunId = contextSerialized.agent_run_aliases[aliasKey];

      if (!agentRunId) {
        continue;
      }

      const item: AgentRunContextItem | FormattedAgentRunContextItem = {
        type: contextSerialized.formatted_data[agentRunId]
          ? 'formatted_agent_run'
          : 'agent_run',
        id: agentRunId,
        transcript_ids: agent_run_to_transcripts[agentRunId],
        collection_id: contextSerialized.agent_run_collection_ids[agentRunId],
      };

      items.push(item);
    } else if (rootItem.startsWith('T')) {
      const aliasKey = rootItem.substring(1);
      const transcriptId = contextSerialized.transcript_aliases[aliasKey];

      if (!transcriptId) {
        continue;
      }

      const agentRunId =
        contextSerialized.transcript_to_agent_run[transcriptId];
      if (!agentRunId) {
        console.warn(`No agent run found for transcript ${transcriptId}`);
        continue;
      }

      const collectionId =
        contextSerialized.agent_run_collection_ids[agentRunId];
      if (!collectionId) {
        console.warn(
          `No collection ID found for transcript's agent run ${agentRunId}`
        );
        continue;
      }

      const item: TranscriptContextItem | FormattedTranscriptContextItem = {
        type: contextSerialized.formatted_data[transcriptId]
          ? 'formatted_transcript'
          : 'transcript',
        id: transcriptId,
        collection_id: collectionId,
        agent_run_id: agentRunId,
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
  onSelect,
}: {
  item: SerializedContextItem;
  index: number;
  isSelected: boolean;
  onSelect: (key: string) => void;
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
    <button
      type="button"
      className={cn(
        'rounded-md border px-3 py-2 text-left transition-colors',
        isSelected
          ? 'border-indigo-border bg-indigo-muted text-primary'
          : 'border-border bg-background text-muted-foreground hover:bg-indigo-muted/40 hover:text-primary'
      )}
      onClick={() => {
        onSelect(key);
      }}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-sm">{title}</span>
        <span className="rounded-full bg-indigo-muted px-2 py-0.5 text-[10px] uppercase text-indigo-text">
          {badge}
        </span>
      </div>
      {subtitle && (
        <div className="mt-1 text-xs text-muted-foreground">{subtitle}</div>
      )}
    </button>
  );
}

export function ConversationContextSection({
  contextSerialized,
}: ConversationContextSectionProps) {
  const citationNav = useCitationNavigation();
  const selectedCitation = citationNav?.selectedCitation ?? null;
  const [isExpanded, setIsExpanded] = useState(true);

  const items = useMemo(
    () => parseContextSerialized(contextSerialized),
    [contextSerialized]
  );

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

  const numAgentRuns = items.filter(
    (item) => item.type === 'agent_run' || item.type === 'formatted_agent_run'
  ).length;
  const description =
    numAgentRuns > 0
      ? `Chatting with ${numAgentRuns} agent run${numAgentRuns > 1 ? 's' : ''}`
      : 'Start a conversation';

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <h4 className="font-semibold text-sm">Chat</h4>
          {description && (
            <span className="text-xs text-muted-foreground">{description}</span>
          )}
        </div>
      </div>
      {items.length > 0 && (
        <div className="border-b border-border bg-secondary/20">
          <div className="p-3 space-y-3">
            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground hover:text-primary transition-colors"
            >
              {isExpanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              Context
            </button>
            {isExpanded && (
              <div className="flex flex-col gap-2">
                {items.map((item, index) => (
                  <ContextItem
                    key={getItemKey(item, index)}
                    item={item}
                    index={index}
                    isSelected={isItemSelected(item, selectedCitation)}
                    onSelect={handleContextSelect}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
