import { useEffect, useState, useMemo } from 'react';
import {
  useGetClusteringStateQuery,
  useGetRubricRunStateQuery,
  RubricCentroid,
  AgentRunJudgeResults,
  JobStatus,
} from '../api/rubricApi';
import { useRubricVersion } from '@/providers/use-rubric-version';
import { ComplexFilter } from '../types/collectionTypes';

interface UseJobStatusProps {
  collectionId: string;
  rubricId: string;
  labelSetId: string | null;
  filter?: ComplexFilter | null;
}

interface UseJobStatusResponse {
  rubricJobId: string | null;
  rubricJobStatus: JobStatus | null;
  agentRunResults: AgentRunJudgeResults[];
  failureCount: number;
  totalResultsNeeded: number;
  currentResultsCount: number;
  activeClusteringJobId?: string;
  clusteringJobId: string | null;
  clusteringJobStatus: JobStatus | null;
  centroids: RubricCentroid[];
  assignments: Record<string, string[]>;
  // Loading flags
  isResultsLoading: boolean;
  isClusteringLoading: boolean;
}

const useJobStatus = ({
  collectionId,
  rubricId,
  labelSetId,
  filter = null,
}: UseJobStatusProps): UseJobStatusResponse => {
  // Rubric run state
  const { version } = useRubricVersion();

  // Maintain a local state + effect so we can start a job back up on page reload
  const [rubricJobId, setRubricJobId] = useState<string | null>(null);
  const [rubricJobStatus, setRubricJobStatus] = useState<JobStatus | null>(
    null
  );
  const { data: rubricRunState, isLoading: isRubricRunLoading } =
    useGetRubricRunStateQuery(
      {
        collectionId,
        rubricId,
        version,
        labelSetId,
        filter,
        includeFailures: true,
      },
      {
        pollingInterval: rubricJobId !== null ? 1000 : 0,
      }
    );
  useEffect(() => {
    setRubricJobId(rubricRunState?.job_id ?? null);
    setRubricJobStatus(rubricRunState?.job_status ?? null);
  }, [rubricRunState?.job_id, rubricRunState?.job_status]);

  // Count failures and filter results
  const { agentRunResults, failureCount } = useMemo(() => {
    const results = rubricRunState?.results ?? [];
    const count = results.reduce(
      (acc, run) =>
        acc +
        (run.results?.filter((r) => r.result_type === 'FAILURE').length ?? 0),
      0
    );
    return { agentRunResults: results, failureCount: count };
  }, [rubricRunState?.results]);

  // Clustering job status
  const [clusteringJobId, setClusteringJobId] = useState<string | null>(null);
  const [clusteringJobStatus, setClusteringJobStatus] =
    useState<JobStatus | null>(null);
  const { data: clusteringState, isLoading: isClusteringLoading } =
    useGetClusteringStateQuery(
      {
        collectionId,
        rubricId,
      },
      {
        pollingInterval: clusteringJobId !== null ? 1000 : 0,
      }
    );
  useEffect(() => {
    setClusteringJobId(clusteringState?.job_id ?? null);
    setClusteringJobStatus(clusteringState?.job_status ?? null);
  }, [clusteringState?.job_id, clusteringState?.job_status]);

  return {
    // Rubric run progress
    rubricJobId,
    rubricJobStatus,
    totalResultsNeeded: rubricRunState?.total_results_needed ?? 0,
    currentResultsCount: rubricRunState?.current_results_count ?? 0,

    // Rubric run results
    agentRunResults,
    failureCount,

    // Clustering job status
    clusteringJobId,
    clusteringJobStatus,

    // Clustering results
    centroids: clusteringState?.centroids ?? [],
    assignments: clusteringState?.assignments ?? {},

    // Loading flags
    isResultsLoading: isRubricRunLoading,
    isClusteringLoading,
  };
};

export default useJobStatus;
