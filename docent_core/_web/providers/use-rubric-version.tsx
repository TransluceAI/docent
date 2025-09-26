'use client';
import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from 'react';
import {
  useGetLatestRubricVersionQuery,
  useGetResultByIdQuery,
} from '@/app/api/rubricApi';
import { useParams, useRouter } from 'next/navigation';
import { skipToken } from '@reduxjs/toolkit/query';

interface RubricVersionContextValue {
  version: number | null;
  setVersion: (version: number | null) => void;
  latestVersion: number | null;
  refetchLatestVersion: () => void;
}

const RubricVersionContext = createContext<RubricVersionContextValue | null>(
  null
);

export function useRubricVersion(): RubricVersionContextValue {
  const ctx = useContext(RubricVersionContext);
  if (!ctx)
    throw new Error(
      'RubricVersion components must be used within a RubricVersionProvider'
    );
  return ctx;
}

interface RubricVersionProviderProps {
  rubricId: string;
  collectionId: string;
  children: React.ReactNode;
}

export function RubricVersionProvider({
  rubricId,
  collectionId,
  children,
}: RubricVersionProviderProps) {
  const { result_id: resultId, agent_run_id: agentRunId } = useParams<{
    result_id?: string;
    agent_run_id?: string;
  }>();
  const router = useRouter();

  // Get the judge result if we're on a result page
  const { data: judgeResult } = useGetResultByIdQuery(
    resultId
      ? {
          collectionId,
          resultId,
        }
      : skipToken
  );

  // If we're not on a result page, get the latest version of the rubric
  const { data: latestVersion, refetch } = useGetLatestRubricVersionQuery({
    rubricId,
    collectionId,
  });

  const [version, setVersion] = useState<number | null>(null);

  const refetchLatestVersion = useCallback(async () => {
    const { data: version } = await refetch();
    setVersion(version ?? null);
  }, [refetch]);

  const updateIfLatestHasChagned = useCallback(async () => {
    const before = latestVersion;
    const { data: after } = await refetch();
    if (before !== after && after) {
      setVersion(after);
    }
  }, [latestVersion, refetch]);

  // Browsers will throttle SSE connections when the tab is not in focus, so we need to
  // refetch the latest version if it was incremented while the tab was not in focus.
  useEffect(() => {
    const handleVisibilityChange = () => {
      // On refocus, refetch the latest version and update if different
      if (!document.hidden) {
        updateIfLatestHasChagned();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [updateIfLatestHasChagned]);

  useEffect(() => {
    // Skip if we don't have any versions
    if (!judgeResult && !latestVersion) return;

    // Resolve the version based on the result id
    const resolvedVersion = resultId
      ? judgeResult?.rubric_version
      : latestVersion;

    // Set the version if it's not already set
    if (version === null) {
      setVersion(resolvedVersion ?? null);
    }
  }, [judgeResult, latestVersion]);

  const valueForProvider: RubricVersionContextValue = {
    version,
    setVersion,
    latestVersion: latestVersion ?? null,
    refetchLatestVersion,
  };

  return (
    <RubricVersionContext.Provider value={valueForProvider}>
      {children}
    </RubricVersionContext.Provider>
  );
}
