import { useState, useEffect } from 'react';
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
  activeRubricJobId?: string;
  shouldPollRubricRunState: boolean;
  judgeResults: JudgeResultWithCitations[];
  totalAgentRuns: number;
  currentAgentRuns: number;
  activeClusteringJobId?: string;
  shouldPollClusteringState: boolean;
  centroids: RubricCentroid[];
  assignments: Record<string, string[]>;
}

const useJobStatus = ({
  collectionId,
  rubricId,
}: UseJobStatusProps): UseJobStatusResponse => {
  // Rubric run state
  const { version } = useRubricVersion();
  const [shouldPollRubricRunState, setShouldPollRubricRunState] =
    useState(false);
  const { data: rubricRunState } = useGetRubricRunStateQuery(
    {
      collectionId,
      rubricId,
      version,
    },
    {
      pollingInterval: shouldPollRubricRunState ? 1000 : 0,
    }
  );
  useEffect(() => {
    setShouldPollRubricRunState(rubricRunState?.job_id !== null);
  }, [rubricRunState?.job_id]);

  const activeRubricJobId = rubricRunState?.job_id ?? undefined;

  // Clustering job status
  const [shouldPollClusteringState, setShouldPollClusteringState] =
    useState(false);
  const { data: clusteringState } = useGetClusteringStateQuery(
    {
      collectionId,
      rubricId,
    },
    {
      pollingInterval: shouldPollClusteringState ? 1000 : 0,
    }
  );
  useEffect(() => {
    setShouldPollClusteringState(clusteringState?.job_id !== null);
  }, [clusteringState?.job_id]);

  const activeClusteringJobId = clusteringState?.job_id ?? undefined;

  return {
    // Rubric run progress
    activeRubricJobId,
    shouldPollRubricRunState,
    totalAgentRuns: rubricRunState?.total_agent_runs ?? 0,
    currentAgentRuns: rubricRunState?.results.length ?? 0,

    // Rubric run results
    judgeResults: rubricRunState?.results ?? [],

    // Clustering job status
    activeClusteringJobId,
    shouldPollClusteringState,

    // Clustering results
    centroids: clusteringState?.centroids ?? [],
    assignments: clusteringState?.assignments ?? {},
  };
};

export default useJobStatus;
