import { apiRestClient } from '@/app/services/apiService';
import { ComplexFilter } from '@/app/types/collectionTypes';

export type PythonSampleType = 'agent_runs' | 'dql' | 'rubric_results';
export type SampleFormat = 'python' | 'notebook';

interface BasePythonSampleRequest {
  type: PythonSampleType;
  api_key: string;
  server_url?: string;
  collection_id: string;
  format?: SampleFormat;
}

export interface AgentRunsSampleRequest extends BasePythonSampleRequest {
  type: 'agent_runs';
  columns: string[];
  sort_field?: string | null;
  sort_direction?: 'asc' | 'desc';
  base_filter?: ComplexFilter | null;
  limit?: number;
}

export interface DqlSampleRequest extends BasePythonSampleRequest {
  type: 'dql';
  dql_query: string;
  filename?: string;
  description?: string;
}

export interface RubricResultsSampleRequest extends BasePythonSampleRequest {
  type: 'rubric_results';
  rubric_id: string;
  rubric_version?: number | null;
  runs_filter?: ComplexFilter | null;
  limit?: number;
}

export type PythonSampleRequest =
  | AgentRunsSampleRequest
  | DqlSampleRequest
  | RubricResultsSampleRequest;

export interface PythonSampleResponse {
  filename: string;
  description: string;
  dql_query: string;
  content: string;
  format: SampleFormat;
}

export const fetchPythonSample = async (
  payload: PythonSampleRequest
): Promise<PythonSampleResponse> => {
  const response = await apiRestClient.post<PythonSampleResponse>(
    '/code-samples/python',
    payload
  );
  return response.data;
};

export const downloadPythonSample = async (
  payload: PythonSampleRequest
): Promise<PythonSampleResponse> => {
  const sample = await fetchPythonSample(payload);

  const mime =
    sample.format === 'notebook' ? 'application/x-ipynb+json' : 'text/x-python';
  const url = URL.createObjectURL(new Blob([sample.content], { type: mime }));
  const link = document.createElement('a');
  link.href = url;
  link.download = sample.filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 500);

  return sample;
};
