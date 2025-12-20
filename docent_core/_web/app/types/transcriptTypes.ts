import { InlineCitation } from './citationTypes';

export interface AgentRun {
  id: string;
  name?: string | null;
  description?: string | null;
  transcripts: Transcript[];
  transcript_groups?: TranscriptGroup[];
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
  id?: string;
  content: string | Content[];
  metadata?: BaseMetadata;
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
  citations?: InlineCitation[];
  suggested_messages?: string[];
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

/** Function tool call with JSON arguments */
export interface FunctionToolCall {
  id: string;
  function: string;
  type: 'function';
  arguments?: Record<string, unknown> | string;
  view?: {
    content: string;
    format: string;
  };
}

/** Custom tool call with text input */
export interface CustomToolCall {
  id: string;
  function: string;
  type: 'custom';
  input?: string;
  view?: {
    content: string;
    format: string;
  };
}

/** Tool call in a chat message */
export type ToolCall = FunctionToolCall | CustomToolCall;

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
