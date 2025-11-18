import { MetadataType } from './collectionTypes';

export interface TranscriptMetadataField {
  name: string;
  type: MetadataType;
}

export interface TaskStats {
  mean: number | null;
  ci: number | null;
  n: number;
}
