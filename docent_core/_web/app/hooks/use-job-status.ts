import { useEffect, useState } from 'react';
import {
  useGetClusteringStateQuery,
  useGetRubricRunStateQuery,
  RubricCentroid,
} from '../api/rubricApi';
import { JudgeResultWithCitations } from '../store/rubricSlice';
import { useRubricVersion } from '@/providers/use-rubric-version';

interface UseJobStatusProps {
  collectionId: string;
  rubricId: string;
}

interface UseJobStatusResponse {
  rubricJobId: string | null;
  judgeResults: JudgeResultWithCitations[];
  totalAgentRuns: number;
  currentAgentRuns: number;
  activeClusteringJobId?: string;
  clusteringJobId: string | null;
  centroids: RubricCentroid[];
  assignments: Record<string, string[]>;
  // Loading flags
  isResultsLoading: boolean;
  isClusteringLoading: boolean;
}

const useJobStatus = ({
  collectionId,
  rubricId,
}: UseJobStatusProps): UseJobStatusResponse => {
  // Rubric run state
  const { version } = useRubricVersion();

  // Maintain a local state + effect so we can start a job back up on page reload
  const [rubricJobId, setRubricJobId] = useState<string | null>(null);
  const { data: rubricRunState, isLoading: isRubricRunLoading } =
    useGetRubricRunStateQuery(
      {
        collectionId,
        rubricId,
        version,
      },
      {
        pollingInterval: rubricJobId !== null ? 1000 : 0,
      }
    );
  useEffect(() => {
    setRubricJobId(rubricRunState?.job_id ?? null);
  }, [rubricRunState?.job_id]);

  // Clustering job status
  const [clusteringJobId, setClusteringJobId] = useState<string | null>(null);
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
  }, [clusteringState?.job_id]);

  return {
    // Rubric run progress
    rubricJobId,
    totalAgentRuns: rubricRunState?.total_agent_runs ?? 0,
    currentAgentRuns: rubricRunState?.results.length ?? 0,

    // Rubric run results
    judgeResults: rubricRunState?.results ?? [],

    // Clustering job status
    clusteringJobId,

    // Clustering results
    centroids: clusteringState?.centroids ?? [],
    assignments: clusteringState?.assignments ?? {},

    // Loading flags
    isResultsLoading: isRubricRunLoading,
    isClusteringLoading,
  };
};

export default useJobStatus;
