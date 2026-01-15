import { CitationTarget } from '@/app/types/citationTypes';
import { LLMContextSpec } from '@/app/api/chatApi';
import {
  SerializedContextItem,
  AgentRunContextItem,
  FormattedAgentRunContextItem,
  TranscriptContextItem,
  FormattedTranscriptContextItem,
  ResultSetContextItem,
  AnalysisResultContextItem,
} from './types';

export function shortUUID(uuid: string): string {
  return uuid.split('-')[0];
}

export function parseContextSerialized(
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
    } else if (ref.type === 'result_set') {
      const item: ResultSetContextItem = {
        type: 'result_set',
        id: ref.id,
        alias: rootItem,
        collection_id: ref.collection_id,
        visible: visibilityMap[rootItem] !== false,
        cutoff_datetime: ref.cutoff_datetime,
      };
      items.push(item);
    } else if (ref.type === 'result') {
      const item: AnalysisResultContextItem = {
        type: 'analysis_result',
        id: ref.id,
        alias: rootItem,
        collection_id: ref.collection_id,
        result_set_id: ref.result_set_id,
        visible: visibilityMap[rootItem] !== false,
      };
      items.push(item);
    }
  }

  return items;
}

export function resolveAliasToContextItem(
  alias: string,
  contextSpec: LLMContextSpec | undefined
): SerializedContextItem | null {
  if (!contextSpec) return null;

  const itemsByAlias = contextSpec.items || {};
  const ref = itemsByAlias[alias];
  if (!ref) return null;

  const inlineData = contextSpec.inline_data || {};
  const visibilityMap = contextSpec.visibility || {};

  const agent_run_to_transcripts: Record<string, string[]> = {};
  for (const a in itemsByAlias) {
    const r = itemsByAlias[a];
    if (r.type === 'transcript') {
      if (!agent_run_to_transcripts[r.agent_run_id]) {
        agent_run_to_transcripts[r.agent_run_id] = [];
      }
      agent_run_to_transcripts[r.agent_run_id].push(r.id);
    }
  }

  if (ref.type === 'agent_run') {
    return {
      type: inlineData[ref.id] ? 'formatted_agent_run' : 'agent_run',
      id: ref.id,
      alias,
      transcript_ids: agent_run_to_transcripts[ref.id] || [],
      collection_id: ref.collection_id,
      visible: visibilityMap[alias] !== false,
    };
  } else if (ref.type === 'transcript') {
    return {
      type: inlineData[ref.id] ? 'formatted_transcript' : 'transcript',
      id: ref.id,
      alias,
      collection_id: ref.collection_id,
      agent_run_id: ref.agent_run_id,
      visible: visibilityMap[alias] !== false,
    };
  } else if (ref.type === 'result_set') {
    return {
      type: 'result_set',
      id: ref.id,
      alias,
      collection_id: ref.collection_id,
      visible: visibilityMap[alias] !== false,
      cutoff_datetime: ref.cutoff_datetime,
    };
  } else if (ref.type === 'result') {
    return {
      type: 'analysis_result',
      id: ref.id,
      alias,
      collection_id: ref.collection_id,
      result_set_id: ref.result_set_id,
      visible: visibilityMap[alias] !== false,
    };
  }

  return null;
}

export function makeSyntheticCitation(
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
    case 'result_set':
      return undefined;
    case 'analysis_result':
      return {
        item: {
          item_type: 'analysis_result',
          result_set_id: item.result_set_id,
          result_id: item.id,
          collection_id: item.collection_id,
        },
        text_range: null,
      };
  }
}

export function getContextItemLabel(
  item: SerializedContextItem,
  resultSetNames?: Map<string, string | null>
): {
  badge: string;
  title: string;
  subtitle?: string;
} {
  switch (item.type) {
    case 'agent_run':
    case 'formatted_agent_run': {
      const transcriptCount = item.transcript_ids.length;
      const transcriptLabel =
        transcriptCount === 1
          ? '1 transcript'
          : `${transcriptCount} transcripts`;
      return {
        badge:
          item.type === 'formatted_agent_run'
            ? 'Formatted Agent Run'
            : 'Agent Run',
        title: `Agent Run ${shortUUID(item.id)}`,
        subtitle: transcriptLabel,
      };
    }
    case 'transcript':
    case 'formatted_transcript':
      return {
        badge:
          item.type === 'formatted_transcript'
            ? 'Formatted Transcript'
            : 'Transcript',
        title: `Transcript ${shortUUID(item.id)}`,
      };
    case 'result_set': {
      const resultSetName = resultSetNames?.get(item.id);
      return {
        badge: 'Result Set',
        title: resultSetName
          ? `Result Set ${resultSetName}`
          : `Result Set ${shortUUID(item.id)}`,
        subtitle: item.cutoff_datetime
          ? `Cutoff ${item.cutoff_datetime}`
          : undefined,
      };
    }
    case 'analysis_result': {
      const resultSetName = resultSetNames?.get(item.result_set_id);
      return {
        badge: 'Analysis Result',
        title: `Result ${shortUUID(item.id)}`,
        subtitle: resultSetName
          ? `Result Set ${resultSetName}`
          : `Result Set ${shortUUID(item.result_set_id)}`,
      };
    }
  }
}

export function formatContextGroupSummary(
  items: SerializedContextItem[]
): string {
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

  const parts: string[] = [];
  if (agentRuns > 0) {
    parts.push(`${agentRuns} ${agentRuns === 1 ? 'agent run' : 'agent runs'}`);
  }
  if (transcripts > 0) {
    parts.push(
      `${transcripts} ${transcripts === 1 ? 'transcript' : 'transcripts'}`
    );
  }
  if (resultSets > 0) {
    parts.push(
      `${resultSets} ${resultSets === 1 ? 'result set' : 'result sets'}`
    );
  }
  if (analysisResults > 0) {
    parts.push(
      `${analysisResults} ${analysisResults === 1 ? 'result' : 'results'}`
    );
  }

  return parts.join(', ');
}

export function getItemKey(item: SerializedContextItem, index: number): string {
  switch (item.type) {
    case 'agent_run':
      return `agent-run-${index}-${item.id}`;
    case 'formatted_agent_run':
      return `formatted-agent-run-${index}-${item.id}`;
    case 'transcript':
      return `transcript-${index}-${item.id}`;
    case 'formatted_transcript':
      return `formatted-transcript-${index}-${item.id}`;
    case 'result_set':
      return `result-set-${index}-${item.id}`;
    case 'analysis_result':
      return `analysis-result-${index}-${item.id}`;
  }
}

export function isItemSelected(
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
      return (
        'agent_run_id' in citationItem && item.id === citationItem.agent_run_id
      );
    case 'transcript':
    case 'formatted_transcript':
      return (
        'transcript_id' in citationItem &&
        item.id === citationItem.transcript_id
      );
    case 'result_set':
      return (
        'result_set_id' in citationItem &&
        item.id === citationItem.result_set_id
      );
    case 'analysis_result':
      return (
        citationItem.item_type === 'analysis_result' &&
        citationItem.result_id === item.id &&
        citationItem.result_set_id === item.result_set_id
      );
  }
}
