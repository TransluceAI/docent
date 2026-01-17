export interface DataTableState {
  schemaVisible?: boolean;
}

export interface DataTable {
  id: string;
  collection_id: string;
  name: string;
  dql: string;
  state: DataTableState | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}
