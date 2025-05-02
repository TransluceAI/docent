import { Citation } from './experimentViewerTypes';

export interface Datapoint {
  id: string;
  text: string;
  attributes: Record<string, string[]>;
  obj: Transcript;
}

export interface Content {
  type: 'text' | 'image' | 'reasoning';
  text?: string;
  reasoning?: string;
  signature?: string | null;
  redacted?: boolean;
  refusal?: string | null;
  // Could add image specific fields if needed
}

/** A chat message in a transcript */
interface BaseChatMessage {
  content: string | Content[];
  source?: 'input' | 'generate';
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

export interface Transcript {
  id: string;
  sample_id: string;
  epoch_id: number;
  messages: ChatMessage[];
  metadata: TranscriptMetadata;
}

interface TranscriptMetadata {
  // Identification of the task
  task_id: string;

  // Identification of this particular run
  sample_id: string | number;
  epoch_id: number;

  // Experiment
  experiment_id: string;
  intervention_description: string | null;
  intervention_index: number | null;
  intervention_timestamp: string | null;

  // Parameters for the run
  model: string;
  task_args: Record<string, any>;
  epochs: number | null;

  // Runtime
  is_loading_messages: boolean;

  // Outcome
  scores: Record<string, number | boolean>;
  default_score_key: string | null;
  scoring_metadata: Record<string, any> | null;

  // Inspect metadata
  inspect_metadata: Record<string, any> | null;
  inspect_score_data: Record<string, any> | null;
}

export interface SolutionSummary {
  datapoint_id: string;
  summary: string;
  parts: string[];
}

export interface ActionsSummary {
  datapoint_id: string;
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
