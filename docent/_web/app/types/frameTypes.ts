import { Citation } from './experimentViewerTypes';

export interface Marginals {
  [dimId: string]: {
    [filterId: string]: Judgment[];
  };
}

export interface Judgment {
  id: string;
  agent_run_id: string;
  filter_id: string;
  attribute?: string | null;
  attribute_idx?: number | null;
  matches: boolean;
  reason?: string | null;
}

export interface FrameGrid {
  id: string;
  name: string | null;
  description: string | null;
  base_filter_id: string | null;
  sample_dim_id: string | null;
  experiment_dim_id: string | null;
  created_at: string;
}

export interface Attribute {
  id: string;
  agent_run_id: string;
  attribute: string;
  attribute_idx?: number | null;
  value?: string | null;
}

export interface AttributeWithCitations extends Attribute {
  citations: Citation[] | null;
}

export type FilterLiteral =
  | 'primitive'
  | 'predicate'
  | 'complex'
  | 'agent_run_id';

export interface FrameFilter {
  id: string;
  name: string | null;
  type: FilterLiteral;
}

export interface AgentRunIdFilter extends FrameFilter {
  type: 'agent_run_id';
  value: string;
}

export interface PrimitiveFilter extends FrameFilter {
  type: 'primitive';
  key_path: string[];
  value: any;
  op: '==' | '!=' | '<' | '<=' | '>' | '>=' | '~*';
}

export type MetadataType = 'str' | 'int' | 'float' | 'bool';

export interface PredicateFilter extends FrameFilter {
  type: 'predicate';
  predicate: string;
  attribute: string;
  backend: string;
}

export interface ComplexFilter extends FrameFilter {
  type: 'complex';
  filters: FrameFilter[];
  op: 'and' | 'or';
}

export interface FrameDimension {
  id: string;
  name: string | null;
  bins: FrameFilter[] | null;
  attribute: string | null;
  metadata_key: string | null;
  backend: string;
  loading_clusters: boolean | null;
  loading_marginals: boolean | null;
}

export interface RegexSnippet {
  snippet: string;
  match_start: number;
  match_end: number;
}
