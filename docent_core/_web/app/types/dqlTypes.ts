export interface DqlForeignKey {
  column: string;
  target_table: string;
  target_column: string;
}

export interface DqlColumnSchema {
  name: string;
  data_type: string | null;
  nullable: boolean;
  is_primary_key: boolean;
  foreign_keys: DqlForeignKey[];
  alias_for?: string | null;
}

export interface DqlTableSchema {
  name: string;
  aliases?: string[];
  columns: DqlColumnSchema[];
}

export interface DqlRubricSchema {
  id: string;
  version: number;
  name: string | null;
  output_fields: string[];
}

export interface DqlSchemaResponse {
  tables: DqlTableSchema[];
  rubrics?: DqlRubricSchema[];
}

export interface DqlColumnReference {
  table: string | null;
  column: string;
}

export interface DqlSelectedColumn {
  output_name: string;
  expression_sql: string;
  source_columns: DqlColumnReference[];
}

export interface DqlLinkHint {
  link_type: 'agent_run' | 'rubric';
  value_kind: 'agent_run_id' | 'transcript_id' | 'rubric_id';
  transcript_id_map?: Record<string, string> | null;
}

export interface DqlExecuteResponse {
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
  row_count: number;
  execution_time_ms: number;
  requested_limit: number | null;
  applied_limit: number;
  selected_columns: DqlSelectedColumn[];
  link_hints: Array<DqlLinkHint | null>;
}

export interface DqlExecutePayload {
  dql: string;
}

export interface DqlAutogenMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  query?: string;
}

export interface DqlGenerateRequest {
  messages: DqlAutogenMessage[];
  current_query: string | null;
  model: string | null;
}

export interface DqlGenerateResponse {
  dql: string;
  assistant_message: string;
  execution: DqlExecuteResponse | null;
  error: string | null;
  used_tables: string[];
}
