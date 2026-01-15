export type AgentRunContextItem = {
  type: 'agent_run';
  id: string;
  alias: string;
  transcript_ids: string[];
  collection_id: string;
  visible: boolean;
};

export type FormattedAgentRunContextItem = {
  type: 'formatted_agent_run';
  id: string;
  alias: string;
  transcript_ids: string[];
  collection_id: string;
  visible: boolean;
};

export type TranscriptContextItem = {
  type: 'transcript';
  id: string;
  alias: string;
  collection_id: string;
  agent_run_id: string;
  visible: boolean;
};

export type FormattedTranscriptContextItem = {
  type: 'formatted_transcript';
  id: string;
  alias: string;
  collection_id: string;
  agent_run_id: string;
  visible: boolean;
};

export type ResultSetContextItem = {
  type: 'result_set';
  id: string;
  alias: string;
  collection_id: string;
  visible: boolean;
  cutoff_datetime?: string;
};

export type AnalysisResultContextItem = {
  type: 'analysis_result';
  id: string;
  alias: string;
  collection_id: string;
  result_set_id: string;
  visible: boolean;
};

export type SerializedContextItem =
  | AgentRunContextItem
  | FormattedAgentRunContextItem
  | TranscriptContextItem
  | FormattedTranscriptContextItem
  | ResultSetContextItem
  | AnalysisResultContextItem;
