// Citation types matching backend's InlineCitation and CitationTarget structure

export interface CitationTargetTextRange {
  start_pattern: string | null;
  end_pattern: string | null;
}

export type ResolvedCitationItem =
  | AgentRunMetadataItem
  | TranscriptMetadataItem
  | TranscriptBlockMetadataItem
  | TranscriptBlockContentItem;

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
