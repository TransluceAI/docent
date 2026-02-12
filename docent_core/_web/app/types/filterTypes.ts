import { CollectionFilter, ComplexFilter } from './collectionTypes';

export interface StoredFilter {
  id: string;
  collection_id: string;
  name: string | null;
  description: string | null;
  filter: ComplexFilter;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export type FilterListItem = Omit<StoredFilter, 'collection_id'>;

export interface CreateFilterRequest {
  filter: CollectionFilter;
  name?: string | null;
  description?: string | null;
}

export interface UpdateFilterRequest {
  filter?: CollectionFilter | null;
  name?: string | null;
  description?: string | null;
}
