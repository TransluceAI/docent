import { createSlice } from '@reduxjs/toolkit';
import { ChatMessage } from '@/app/types/transcriptTypes';

export interface RefinementAgentSession {
  id: string;
  rubric_id: string;
  rubric_version: number;
  messages: ChatMessage[];
  n_summaries: number;
  // Optional error from backend refinement agent
  error_message?: string;
}

interface RefinementState {}

const initialState: RefinementState = {};

const refinementSlice = createSlice({
  name: 'refinement',
  initialState,
  reducers: {},
  extraReducers: (builder) => {},
});

// export const {} = refinementSlice.actions;
export default refinementSlice.reducer;
