// Citation types matching backend's InlineCitation and CitationTarget structure

export interface CitationTargetTextRange {
  // The start index of the target item within the text.
  target_start_idx?: number;
  target_end_idx?: number;
  start_pattern: string | null;
  end_pattern: string | null;
}

export interface AnalysisResultItem {
  item_type: 'analysis_result';
  result_set_id: string;
  result_id: string;
  collection_id: string;
}

export type ResolvedCitationItem =
  | AgentRunMetadataItem
  | TranscriptMetadataItem
  | TranscriptBlockMetadataItem
  | TranscriptBlockContentItem
  | AnalysisResultItem;

export interface AgentRunMetadataItem {
  item_type: 'agent_run_metadata';
  agent_run_id: string;
  collection_id: string;
  metadata_key: string;
}

export interface TranscriptMetadataItem {
  item_type: 'transcript_metadata';
  agent_run_id: string;
  collection_id: string;
  transcript_id: string;
  metadata_key: string;
}

export interface TranscriptBlockMetadataItem {
  item_type: 'block_metadata';
  agent_run_id: string;
  collection_id: string;
  transcript_id: string;
  block_idx: number;
  metadata_key: string;
}

export interface TranscriptBlockContentItem {
  item_type: 'block_content';
  agent_run_id: string;
  collection_id: string;
  transcript_id: string;
  block_idx: number;
  content_idx?: number;
}

export interface CitationTarget {
  item: ResolvedCitationItem;
  text_range: CitationTargetTextRange | null;
}

export interface InlineCitation {
  start_idx: number;
  end_idx: number;
  target: CitationTarget;
}
