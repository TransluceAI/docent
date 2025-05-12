import { FrameDimension, FrameFilter, Judgment } from './frameTypes';

export type MetadataType = 'str' | 'int' | 'float' | 'bool';

export interface TranscriptMetadataField {
  name: string;
  type: MetadataType;
}

export interface Citation {
  start_idx: number;
  end_idx: number;
  block_idx: number;
  transcript_idx: number | null;
  action_unit_idx: number | null;
}

export interface AttributeWithCitation {
  attribute: string;
  citations: Citation[];
}

export interface StreamedAttribute {
  datapoint_id: string | null;
  attribute: string | null;
  attributes: AttributeWithCitation[] | null;
  num_datapoints_done: number;
  num_datapoints_total: number;
}

export interface TaskStats {
  [scoreKey: string]: {
    mean: number | null;
    ci: number | null;
    n: number;
  };
}

export interface MarginalizationResult {
  marginals: Record<string, any>;
  dim_ids_to_filter_ids: Record<string, string[]>;
  dims_dict: Record<string, FrameDimension>;
  filters_dict: Record<string, FrameFilter>;
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

export interface StreamedDiffs {
  data_id_1: string | null;
  data_id_2: string | null;
  claim: string[] | null;
  evidence: EvidenceWithCitation[] | null;
  reverse_evidence: EvidenceWithCitation[] | null;
  num_pairs_done: number;
  num_pairs_total: number;
}