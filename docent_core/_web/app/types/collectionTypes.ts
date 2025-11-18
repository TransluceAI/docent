export interface Bins {
  [dimId: string]: {
    [filterId: string]: Judgment[] | string[];
  };
}

export interface Judgment {
  id: string;
  agent_run_id: string;
  filter_id: string;
  search_query?: string | null;
  search_result_idx?: number | null;
  matches: boolean;
  reason?: string | null;
}

export interface PrimitiveFilter {
  id: string;
  name: string | null;
  type: 'primitive';
  key_path: string[];
  value: any;
  op: string;
  supports_sql: boolean;
  disabled?: boolean;
}

export interface SearchResultPredicateFilter {
  id: string;
  name: string;
  type: 'search_result_predicate';
  predicate: string;
  search_query: string;
  supports_sql: boolean;
  disabled?: boolean;
}

export interface SearchResultExistsFilter {
  id: string;
  name: string;
  type: 'search_result_exists';
  search_query: string;
  supports_sql: boolean;
  disabled?: boolean;
}

export interface ComplexFilter {
  id: string;
  name: string | null;
  type: 'complex';
  filters: CollectionFilter[];
  op: 'and' | 'or' | 'not';
  supports_sql: boolean;
  disabled?: boolean;
}

export interface AgentRunIdFilter {
  id: string;
  name: string;
  type: 'agent_run_id';
  agent_run_ids: string[];
  supports_sql: boolean;
  disabled?: boolean;
}

export type ChartType = 'bar' | 'line' | 'table';

export interface ChartSpec {
  id: string;
  name: string;
  series_key: string | null;
  x_key?: string;
  y_key?: string;

  x_label?: string;
  y_label?: string;
  series_label?: string;
  runs_filter?: ComplexFilter | null;

  chart_type: ChartType;
}

type BaseDimension = {
  key: string;
  name: string;
};

export type ChartDimension =
  | (BaseDimension & { kind: 'run_metadata'; json_path: string })
  | (BaseDimension & {
      kind: 'judge_output';
      judge_id: string;
      judge_version: number;
      judge_name: string;
    })
  | (BaseDimension & { kind: 'aggregation' });

export type CollectionFilter =
  | PrimitiveFilter
  | SearchResultPredicateFilter
  | SearchResultExistsFilter
  | ComplexFilter
  | AgentRunIdFilter;

// Simple dimension representation - just a string key
export type Dimension = string;

export interface Collection {
  id: string;
  name?: string | null;
  description?: string | null;
  created_at: string;
  created_by?: string | null;
}

export interface BaseAgentRunMetadata {
  [key: string]: any;
}

// Metadata type for transcript metadata fields
export type MetadataType = 'str' | 'int' | 'float' | 'bool';
