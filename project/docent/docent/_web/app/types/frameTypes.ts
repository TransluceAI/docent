export interface Marginals {
  [dimId: string]: {
    [filterId: string]: Judgment[];
  };
}

export interface Judgment {
  id: string;
  data_id: string;
  attribute: string | null;
  attribute_idx: number | null;
  matches: boolean;
  reason: string | null;
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
  data_id: string;
  attribute: string;
  attribute_idx: number;
  value: string;
}

export type FilterLiteral =
  | 'primitive'
  | 'predicate'
  | 'complex'
  | 'datapoint_id';

export interface FrameFilter {
  id: string;
  name: string | null;
  type: FilterLiteral;
}

export interface DatapointIdFilter extends FrameFilter {
  type: 'datapoint_id';
  value: string;
}

export interface PrimitiveFilter extends FrameFilter {
  type: 'primitive';
  key_path: string[];
  value: any;
  op: '==' | '!=' | '<' | '<=' | '>' | '>=' | '~*';
}

export type MetadataType = 'str' | 'int' | 'float' | 'bool';

export interface FramePredicate extends FrameFilter {
  type: 'predicate';
  predicate: string;
  attribute: string;
  backend: string;
}

export interface ComplexFrameFilter extends FrameFilter {
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

export interface Judgment {
  data_id: string;
  matches: boolean;
}
