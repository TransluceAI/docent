/** A tool call error */
interface ToolCallError {
  type: string;
  message: string;
}

/** Tool call in a chat message */
interface ToolCall {
  id: string;
  function: string;
  type: string;
  arguments?: Record<string, unknown>;
  view?: {
    content: string;
    format: string;
  };
}

/** Base interface for chat message content */
interface Content {
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

/** A citation referencing a specific datapoint */
interface Citation {
  start_idx: number;
  end_idx: number;
  block_idx: number;
  transcript_idx: number | null;
  action_unit_idx: number | null;
}

interface LowLevelAction {
  action_unit_idx: number;
  title: string;
  summary: string;
  citations: Citation[];
}

interface HighLevelAction {
  step_idx: number;
  title: string;
  summary: string;
  action_unit_indices: number[];
  first_block_idx: number | null;
  citations: Citation[];
}

type ObservationCategory =
  | 'mistake'
  | 'critical_insight'
  | 'near_miss'
  | 'weird_behavior'
  | 'cheating';

interface ObservationType {
  category: ObservationCategory;
  description: string;
  action_unit_idx: number;
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

type ChatMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage;

/** A transcript containing chat messages and metadata */
interface Transcript {
  id: string;
  sample_id: string;
  epoch_id: number;
  messages: ChatMessage[];
  metadata: TranscriptMetadata;
}

/** Metadata for a transcript */
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

  // Inspect metadata
  inspect_metadata: Record<string, any> | null;
  inspect_score_data: Record<string, any> | null;
}

/** A datapoint containing text, extracted attributes and metadata */
interface Datapoint {
  id: string;
  text: string;
  attributes: Record<string, string[]>;
  obj: Transcript;
}

/** A judgment indicating whether a datapoint matches a filter */
interface Judgment {
  data_id: string;
  attribute_id: string;
  attribute_idx: number;

  matches: boolean;
  reason: string | null;

  sub_judgments: Judgment[];
}

/** Valid filter types */
type FilterLiteral =
  | 'metadata'
  | 'predicate'
  | 'complex'
  | 'residual'
  | 'datapoint_id'
  | 'attribute'
  | 'transcript_contains';

/** Base interface for all frame filters */
interface FrameFilter {
  id: string;
  type: FilterLiteral;
  /** Substring for transcript_contains filter */
  substring?: string;
}

/** A filter that checks if a datapoint's metadata matches a specified key-value pair */
interface MetadataFilter extends FrameFilter {
  type: 'metadata';
  key: string;
  value: string | boolean | number | null;
  op?: '==' | '!=' | '<' | '<=' | '>' | '>=';
}

/** A filter that checks if a datapoint's ID matches a specified ID */
interface DatapointIdFilter extends FrameFilter {
  type: 'datapoint_id';
  value: string;
}

/** A filter that checks if a datapoint has any attribute matching a specified attribute_id */
interface AttributeFilter extends FrameFilter {
  type: 'attribute';
  attribute_id: string;
}

/** A filter that uses an LLM to determine which data points satisfy a predicate */
interface FramePredicate extends FrameFilter {
  type: 'predicate';
  predicate: string;
  attribute: string | null;
  metadata_key: string | null;
  backend: 'o1-mini' | 'gpt-4o-mini'; // Matching the Python Literal type
}

/** A filter that combines multiple filters using AND/OR operations */
interface ComplexFrameFilter extends FrameFilter {
  type: 'complex';
  filters: FrameFilter[];
  op: 'and' | 'or'; // Matching the Python Literal type
}

/** A filter representing datapoints that don't match any other filters */
interface ResidualFilter extends FrameFilter {
  type: 'residual';
  id: '_residual';
}

/** A dimension containing bins (filters) for categorizing datapoints */
interface FrameDimension {
  id: string;
  bins: FrameFilter[] | null;
  attribute: string | null;
  includeResidual: boolean;
}

/** State of a dimension including loading states */
interface DimState {
  dim: FrameDimension;
  loading_clusters: boolean;
  loading_marginal: boolean;
}

/** Map of dimension IDs to bin IDs to judgments */
interface Marginals {
  [dimensionId: string]: {
    [binId: string]: (Judgment | null)[][];
  };
}

/** Statistics for accuracy with confidence interval */
interface AccuracyWithCI {
  mean: number;
  ci_lower: number;
  ci_upper: number;
  n: number;
}

export interface DockerConfig {
  apt_get_installs: string[];
  pip3_installs: string[];
  network_mode: 'none' | 'bridge';
  dockerfile_template: string;
  docker_compose_template: string;
}

export interface SolverConfig {
  solver_system_message: string;
  solver_max_messages: number;
  solver_timeout: number;
  solver_max_attempts: number;
}

export type MetadataType = 'str' | 'int' | 'float' | 'bool';

export interface TranscriptMetadataField {
  name: string;
  type: MetadataType;
}

/** Node in a transcript diff graph representing an action unit */
export interface TranscriptDiffNode {
  id: string;
  data: any;
  datapoint_id: string;
  action_unit_idx: number;
  starting_block_idx: number;
}

/** Edge in a transcript diff graph connecting action units */
export interface TranscriptDiffEdge {
  id: string;
  source: string;
  target: string;
  type: 'chain' | 'exact_match' | 'near_match';
  explanation: string;
}

export interface ExportNode {
  id: string;
  data: any;
}

export interface ExportEdge {
  id: string;
  source: string;
  target: string;
}

export interface ExperimentForest {
  nodes: ExportNode[];
  edges: ExportEdge[];
  sample_id: string;
  experiments_to_transcripts: Record<string, string[]>;
}

export interface TranscriptDerivationTree {
  nodes: ExportNode[];
  edges: ExportEdge[];
  sample_id: string;
}

export interface ExperimentTree {
  nodes: ExportNode[];
  edges: ExportEdge[];
  sample_id: string;
}

/** Complete graph structure for transcript diff visualization */
export interface TranscriptDiffGraph {
  nodes: TranscriptDiffNode[];
  edges: TranscriptDiffEdge[];
}

/** An attribute with citation information */
interface AttributeWithCitation {
  attribute: string;
  citations: Citation[];
}

/** A streamed attribute update */
interface StreamedAttribute {
  datapoint_id: string | null;
  attribute_id: string | null;
  attributes: AttributeWithCitation[] | null;
  num_datapoints_done: number;
  num_datapoints_total: number;
}

export interface SolutionSummary {
  summary: string;
  parts: string[];
}

export interface ActionsSummary {
  low_level: LowLevelAction[];
  high_level: HighLevelAction[];
  observations: ObservationType[];
}

export interface TaskStats {
  [scoreKey: string]: {
    mean: number | null;
    ci: number | null;
    n: number;
  };
}

export interface TranscriptComparison {
  text: string;
  citations: Citation[];
}

export type {
  Content,
  ToolCallError,
  ToolCall,
  BaseChatMessage,
  SystemMessage,
  UserMessage,
  AssistantMessage,
  ToolMessage,
  ChatMessage,
  Transcript,
  TranscriptMetadata,
  Datapoint,
  Judgment,
  FilterLiteral,
  FrameFilter,
  FramePredicate,
  ComplexFrameFilter,
  ResidualFilter,
  FrameDimension,
  DimState,
  Marginals,
  MetadataFilter,
  AccuracyWithCI,
  Citation,
  LowLevelAction,
  HighLevelAction,
  ObservationType,
  ObservationCategory,
  AttributeWithCitation,
  StreamedAttribute,
  DatapointIdFilter,
  AttributeFilter,
};
