import { Citation } from './experimentViewerTypes';

export interface AgentRun {
  id: string;
  name?: string | null;
  description?: string | null;
  transcripts: Record<string, Transcript>;
  transcript_groups?: Record<string, TranscriptGroup>;
  metadata: BaseAgentRunMetadata;
}

export interface Content {
  type: 'text' | 'image' | 'reasoning';
  text?: string;
  reasoning?: string;
  signature?: string | null;
  redacted?: boolean;
  refusal?: string | null;
}

interface BaseChatMessage {
  content: string | Content[];
}

interface SystemMessage extends BaseChatMessage {
  role: 'system';
}

interface UserMessage extends BaseChatMessage {
  role: 'user';
  tool_call_id?: string;
}

interface AssistantMessage extends BaseChatMessage {
  role: 'assistant';
  tool_calls?: ToolCall[];
  citations?: Citation[];
}

interface ToolMessage extends BaseChatMessage {
  role: 'tool';
  tool_call_id?: string;
  function?: string;
  error?: ToolCallError;
}

interface ToolCallError {
  type: string;
  message: string;
}

/** Tool call in a chat message */
export interface ToolCall {
  id: string;
  function: string;
  type: string;
  arguments?: Record<string, unknown>;
  view?: {
    content: string;
    format: string;
  };
}

export interface TaMessage {
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
}

export type ChatMessage =
  | SystemMessage
  | UserMessage
  | AssistantMessage
  | ToolMessage;

export type MetadataPrimitive = string | number | boolean;

export interface BaseMetadata {
  [key: string]:
    | MetadataPrimitive
    | MetadataPrimitive[]
    | { [key: string]: MetadataPrimitive | MetadataPrimitive[] }
    | undefined;
}

export interface BaseAgentRunMetadata extends BaseMetadata {
  run_id?: string;
  scores: { [key: string]: number | boolean };
}

export function getMetadataValue<T>(
  metadata: BaseMetadata,
  key: string,
  defaultValue: T | null = null
): T | null {
  return key in metadata ? (metadata[key] as T) : defaultValue;
}

export interface Transcript {
  id: string;
  name?: string | null;
  transcript_group_id?: string | null;
  created_at?: string | null;
  messages: ChatMessage[];
  metadata: BaseMetadata;
}

export interface TranscriptGroup {
  id: string;
  name?: string | null;
  description?: string | null;
  collection_id: string;
  agent_run_id: string;
  parent_transcript_group_id?: string | null;
  created_at?: string | null;
  metadata: BaseMetadata;
}

export interface SolutionSummary {
  agent_run_id: string;
  summary: string;
  parts: string[];
}

export interface ActionsSummary {
  agent_run_id: string;
  low_level: LowLevelAction[];
  high_level: HighLevelAction[];
  observations: ObservationType[];
}

export interface LowLevelAction {
  action_unit_idx: number;
  title: string;
  summary: string;
  citations: Citation[];
}

export interface HighLevelAction {
  step_idx: number;
  title: string;
  summary: string;
  action_unit_indices: number[];
  first_block_idx: number | null;
  citations: Citation[];
}

export type ObservationCategory =
  | 'mistake'
  | 'critical_insight'
  | 'near_miss'
  | 'weird_behavior'
  | 'cheating';

export interface ObservationType {
  category: ObservationCategory;
  description: string;
  action_unit_idx: number;
}
