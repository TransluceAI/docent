// Types for Investigator Experiment data

export type ExperimentType = 'counterfactual' | 'simple_rollout';

export interface CounterfactualContext {
  id: string;
  name?: string;
  value?: string;
}

export interface ExperimentStatus {
  status?: 'pending' | 'running' | 'completed' | 'cancelled' | 'error';
  progress?: number;
  error_message?: string;
}

export interface AgentRunMetadata {
  model: string;
  counterfactual_id: string;
  counterfactual_name: string;
  counterfactual_description: string;
  replica_idx: number;
  grade?: { grade: number };
  state?: 'in_progress' | 'completed' | 'errored';
  error_type?: string;
  error_message?: string;
}

// TODO: have strongly typed version of this for both counterfactual and simple rollout experiments
export interface ExperimentStreamData {
  activeJobId?: string;
  counterfactualIdeaOutput?: string;
  counterfactualContextById?: Record<string, CounterfactualContext>;
  experimentStatus?: ExperimentStatus;
  agentRunMetadataById?: Record<string, AgentRunMetadata>;
  docentCollectionId?: string;
}

// TODO: have strongly typed version of this for both counterfactual and simple rollout experiments
export interface ExperimentResult {
  counterfactual_idea_output?: string;
  counterfactual_context_output?: Record<string, string>;
  parsed_counterfactual_ideas?: {
    counterfactuals?: Record<string, { name?: string }>;
  };
  experiment_status?: ExperimentStatus;
  agent_run_metadata?: Record<string, AgentRunMetadata>;
  docent_collection_id?: string;
}

// TODO: have strongly typed version of this for both counterfactual and simple rollout experiments
// SSE message types for experiment streaming
export interface ExperimentSSEMessage {
  type: string;
  data?: unknown;
  job_id?: string;
  counterfactual_idea_output?: string;
  counterfactual_context_output?: Record<string, string>;
  parsed_counterfactual_ideas?: {
    counterfactuals?: Record<string, { name?: string }>;
  };
  experiment_status?: ExperimentStatus;
  agent_run_metadata?: Record<string, AgentRunMetadata>;
  docent_collection_id?: string;
}

// Experiment Config Types
export interface BaseExperimentConfig {
  id: string;
  workspace_id: string;
  created_at: string;
  judge_config_id?: string | null;
  openai_compatible_backend_id: string;
  base_context_id: string;
  num_replicas: number;
  max_turns: number;
}

export interface CounterfactualExperimentConfig extends BaseExperimentConfig {
  type: 'counterfactual';
  judge_config_id: string;
  idea_id: string;
  num_counterfactuals: number;
}

export interface SimpleRolloutExperimentConfig extends BaseExperimentConfig {
  type: 'simple_rollout';
  judge_config_id?: string | null;
}

export type ExperimentConfig =
  | CounterfactualExperimentConfig
  | SimpleRolloutExperimentConfig;
