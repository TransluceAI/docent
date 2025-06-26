import { Citation } from './experimentViewerTypes';

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
}

export interface SearchResultPredicateFilter {
  id: string;
  name: string;
  type: 'search_result_predicate';
  predicate: string;
  search_query: string;
  supports_sql: boolean;
}

export interface SearchResultExistsFilter {
  id: string;
  name: string;
  type: 'search_result_exists';
  search_query: string;
  supports_sql: boolean;
}

export interface ComplexFilter {
  id: string;
  name: string | null;
  type: 'complex';
  filters: FrameFilter[];
  op: 'and' | 'or' | 'not';
  supports_sql: boolean;
}

export interface AgentRunIdFilter {
  id: string;
  name: string;
  type: 'agent_run_id';
  agent_run_ids: string[];
  supports_sql: boolean;
}

export type FrameFilter =
  | PrimitiveFilter
  | SearchResultPredicateFilter
  | SearchResultExistsFilter
  | ComplexFilter
  | AgentRunIdFilter;

// Simple dimension representation - just a string key
export type Dimension = string;

// For backward compatibility, we'll keep FrameDimension as a simple interface
// but it's now just a wrapper around a string
export interface FrameDimension {
  id: string; // This is now the metadata key
  name: string | null; // This is now the metadata key
  search_query?: string | null; // For search query dimensions
  metadata_key?: string | null; // For metadata dimensions
  maintain_mece?: boolean | null; // For metadata dimensions
  loading_clusters: boolean; // Loading state
  loading_bins: boolean; // Loading state
  bins?: FrameFilter[] | null; // Optional field for when bins are fetched separately
}

export interface FrameGrid {
  id: string;
  name?: string | null;
  description?: string | null;
  created_at: string;
  created_by?: string | null;
}

export interface AgentRunMetadataField {
  key: string;
  type: 'string' | 'number' | 'boolean';
  description?: string;
}

export interface BaseAgentRunMetadata {
  [key: string]: any;
}

export interface SearchResult {
  id: string;
  fg_id: string;
  agent_run_id: string;
  search_query: string;
  search_result_idx?: number | null;
  value?: string | null;
}

export interface SearchResultWithCitations extends SearchResult {
  citations: Citation[] | null;
}

export interface SearchQuery {
  id: string;
  fg_id: string;
  search_query: string;
  created_at: string;
}

// Metadata type for transcript metadata fields
export type MetadataType = 'str' | 'int' | 'float' | 'bool';

export interface View {
  id: string;
  fg_id: string;
  name?: string | null;
  is_default: boolean;
  base_filter_id?: string | null;
  inner_bin_key?: string | null;
  outer_bin_key?: string | null;
}

export interface Job {
  id: string;
  type: string;
  created_at: string;
  job_json: any;
  status: 'pending' | 'running' | 'canceled' | 'completed';
}

export interface User {
  id: string;
  email: string;
  created_at: string;
  is_anonymous: boolean;
  organization_ids?: string[];
}

export interface Organization {
  id: string;
  name: string;
  description?: string | null;
}

export interface Session {
  id: string;
  user_id: string;
  created_at: string;
  expires_at: string;
  is_active: boolean;
}

export interface AccessControlEntry {
  id: string;
  user_id?: string | null;
  organization_id?: string | null;
  is_public: boolean;
  fg_id?: string | null;
  view_id?: string | null;
  permission: string;
}

export interface FrameState {
  frameGridId?: string;
  dimensionsMap?: Record<string, FrameDimension>;
  filtersMap?: Record<string, FrameFilter>;
  baseFilter?: ComplexFilter;
  inner_bin_key?: string | null;
  outer_bin_key?: string | null;
}
