'use client';
import { createContext, useContext, useState, useEffect } from 'react';
import { useGetLatestRubricVersionQuery } from '@/app/api/rubricApi';

interface RubricVersionContextValue {
  version: number | null;
  setVersion: (version: number | null) => void;
  latestVersion: number | null;
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
  const { data: latestVersion } = useGetLatestRubricVersionQuery({
    rubricId,
    collectionId,
  });

  const [version, setVersion] = useState<number | null>(null);

  useEffect(() => {
    if (version === null) {
      setVersion(latestVersion ?? null);
    }
  }, [latestVersion]);

  const valueForProvider: RubricVersionContextValue = {
    version,
    setVersion,
    latestVersion: latestVersion ?? null,
  };

  return (
    <RubricVersionContext.Provider value={valueForProvider}>
      {children}
    </RubricVersionContext.Provider>
  );
}
