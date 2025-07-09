export interface DiffQuery {
  id: string;
  grouping_md_fields: string[];
  md_field_value_1: [string, any];
  md_field_value_2: [string, any];
  focus: string | null;
}

export interface DiffInstance {
  id: string;
  summary: string;
  shared_context: string;
  agent_1_action: string;
  agent_1_evidence: {
    evidence: string;
    citations: any[];
  };
  agent_2_action: string;
  agent_2_evidence: {
    evidence: string;
    citations: any[];
  };
}

export interface DiffResult {
  id: string;
  agent_run_1_id: string;
  agent_run_2_id: string;
  instances: DiffInstance[] | null;
}
