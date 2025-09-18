import { createSlice } from '@reduxjs/toolkit';
import { SchemaDefinition } from '@/app/types/schema';

export interface ModelOption {
  provider: string;
  model_name: string;
  reasoning_effort: 'low' | 'medium' | 'high' | null;
  context_window: number;
  uses_byok: boolean;
}

export interface JudgeRunLabel {
  id: string;
  agent_run_id: string;
  rubric_id: string;
  label: Record<string, any>;
}

export interface Rubric {
  id: string;
  version: number;
  rubric_text: string;
  judge_model: ModelOption;
  output_schema: SchemaDefinition;
}

export interface JudgeResult {
  id: string;
  agent_run_id: string;
  rubric_id: string;
  rubric_version: number;
  output: Record<string, any>;
}

export type JudgeResultWithCitations = JudgeResult & {
  readonly _brand: 'citations';
};

export interface RubricCentroid {
  id: string;
  collection_id: string;
  rubric_id: string;
  centroid: string;
}

export interface RubricState {}

const initialState: RubricState = {};

export const rubricSlice = createSlice({
  name: 'rubric',
  initialState,
  reducers: {},
});

export default rubricSlice.reducer;
