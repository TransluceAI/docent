import { SearchResultWithCitations, MetadataType } from './collectionTypes';

// export interface PaginationState {
//   currentPage: number;
//   startIndex: number;
//   endIndex: number;
// }

export interface TranscriptMetadataField {
  name: string;
  type: MetadataType;
}

export interface Citation {
  start_idx: number;
  end_idx: number;
  transcript_idx: number | undefined;
  block_idx: number | undefined;
  metadata_key: string | undefined;
  start_pattern: string | undefined;
}

export interface StreamedSearchResult {
  data_dict: Record<string, Record<string, SearchResultWithCitations[]>>;
  num_agent_runs_done: number;
  num_agent_runs_total: number;
  num_search_hits: number;
}

export interface StreamedSearchResultClusterAssignment {
  search_result_cluster_id: string;
  search_result_id: string;
  cluster_id: string;
  centroid: string;
  decision: boolean;
  value: string;
}

export interface TaskStats {
  mean: number | null;
  ci: number | null;
  n: number;
}

export type OrganizationMethod = 'experiment' | 'sample';

export interface TranscriptDiffViewport {
  x: number;
  y: number;
  zoom: number;
  transcriptIds: [string, string] | null;
}

export interface AttributeFeedback {
  attribute: string;
  vote: 'up' | 'down';
}

export interface RegexSnippet {
  snippet: string;
  match_start: number;
  match_end: number;
}

export interface EvidenceWithCitation {
  evidence: string;
  citations: Citation[];
}

// export interface StreamedDiffs {
//   data_id_1: string | null;
//   data_id_2: string | null;
//   claim: string[] | null;
//   evidence: EvidenceWithCitation[] | null;
//   num_pairs_done: number;
//   num_pairs_total: number;
//   transcript_diff: TranscriptDiff;
// }
