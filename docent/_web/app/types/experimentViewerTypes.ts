import {
  AttributeWithCitations,
  FrameDimension,
  FrameFilter,
} from './frameTypes';

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

export interface StreamedAttribute {
  data_dict: Record<string, Record<string, AttributeWithCitations[]>>;
  num_agent_runs_done: number;
  num_agent_runs_total: number;
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
