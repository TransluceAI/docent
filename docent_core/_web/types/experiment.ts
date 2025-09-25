// Types for Investigator Experiment data

export interface CounterfactualContext {
  id: string;
  name?: string;
  value?: string;
}

export interface ExperimentStatus {
  status?: string;
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

export interface ExperimentStreamData {
  activeJobId?: string;
  counterfactualIdeaOutput?: string;
  counterfactualContextById?: Record<string, CounterfactualContext>;
  experimentStatus?: ExperimentStatus;
  agentRunMetadataById?: Record<string, AgentRunMetadata>;
  docentCollectionId?: string;
}

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
