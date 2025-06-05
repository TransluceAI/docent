import { createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { apiRestClient } from '../services/apiService';

import { setToastNotification } from './toastSlice';

export const fetchJobs = createAsyncThunk('frame/fetchJobs', async (_, { dispatch }) => {
  try {
    const response = await apiRestClient.get('/search_jobs');
    dispatch(setJobs(response.data));
    return response.data;
  } catch (error) {
    dispatch(
      setToastNotification({
        title: 'Error fetching search jobs',
        description: 'Please try again in a moment',
        variant: 'destructive',
      }),
    );
    throw error;
  }
});

export interface Job {
  id: string;
  type: string;
  created_at: string;
  status: string;
  job_json: { query_id: string };
}

export interface Query {
  id: string;
  fg_id: string;
  search_query: string;
}

export interface JobsState {
  jobs: [Job, Query][];
}

const initialState: JobsState = {
  jobs: [],
};

export const jobsSlice = createSlice({
  name: 'jobs',
  initialState,
  reducers: {
    setJobs: (state, action: PayloadAction<[Job, Query][]>) => {
      state.jobs = action.payload;
    },
  },
});

export const { setJobs } = jobsSlice.actions;

export default jobsSlice.reducer;
