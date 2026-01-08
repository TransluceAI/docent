'use client';

import { LabelSet, useGetLabelSetsQuery } from '@/app/api/labelApi';
import {
  createContext,
  useContext,
  useMemo,
  useEffect,
  useCallback,
} from 'react';
import { useLocalStorage } from 'usehooks-ts';

interface LabelSetsContextValue {
  getLabelSet: (objectKey: string) => LabelSet | null;
  setLabelSet: (objectKey: string, labelSet: LabelSet | null) => void;
}

const LabelSetsContext = createContext<LabelSetsContextValue>({
  getLabelSet: () => null,
  setLabelSet: () => {},
});

export function useLabelSets(objectKey: string) {
  const ctx = useContext(LabelSetsContext);
  if (!ctx) {
    throw new Error('useLabelSets must be used within a LabelSetsProvider');
  }

  const { getLabelSet, setLabelSet: setLabelSetFn } = ctx;

  const activeLabelSet = useMemo(() => {
    return getLabelSet(objectKey);
  }, [objectKey, getLabelSet]);

  const setLabelSet = useCallback(
    (labelSet: LabelSet | null) => {
      setLabelSetFn(objectKey, labelSet);
    },
    [objectKey, setLabelSetFn]
  );

  return { activeLabelSet, setLabelSet };
}

export function LabelSetsProvider({
  children,
  collectionId,
}: {
  children: React.ReactNode;
  collectionId: string;
}) {
  const [labelSetsByKey, setLabelSetsByKey] = useLocalStorage<
    Record<string, LabelSet | null>
  >(`labelSets-${collectionId}`, {}, { initializeWithValue: false });

  // Fetch the available label sets from the API
  const { data: availableLabelSets, isFetching } = useGetLabelSetsQuery({
    collectionId,
  });

  // Create a map from label set id to label set
  const labelIdToRemoteLabelSet = useMemo(() => {
    return availableLabelSets?.reduce(
      (acc, labelSet) => {
        acc[labelSet.id] = labelSet;
        return acc;
      },
      {} as Record<string, LabelSet>
    );
  }, [availableLabelSets]);

  const getLabelSet = useMemo(() => {
    return (objectKey: string) => {
      return labelSetsByKey[objectKey];
    };
  }, [labelSetsByKey]);

  // Function to set the active label set for a given object key
  const setLabelSet = useCallback(
    (objectKey: string, labelSet: LabelSet | null) => {
      setLabelSetsByKey((prev) => ({
        ...prev,
        [objectKey]: labelSet,
      }));
    },
    [setLabelSetsByKey]
  );

  // Make sure local label sets are in sync when the remote label sets change
  useEffect(() => {
    if (!labelIdToRemoteLabelSet || isFetching) return;

    const updates: Record<string, LabelSet | null> = {};
    let hasUpdates = false;

    Object.entries(labelSetsByKey).forEach(([key, labelSet]) => {
      if (!labelSet) return;

      const remoteLabelSet = labelIdToRemoteLabelSet[labelSet.id];

      // Clear deleted label sets
      if (!remoteLabelSet) {
        updates[key] = null;
        hasUpdates = true;
        return;
      }

      // Sync updated label sets
      if (
        remoteLabelSet.name !== labelSet.name ||
        remoteLabelSet.description !== labelSet.description
      ) {
        updates[key] = remoteLabelSet;
        hasUpdates = true;
      }
    });

    if (hasUpdates) {
      setLabelSetsByKey((prev) => ({ ...prev, ...updates }));
    }
  }, [labelIdToRemoteLabelSet]);

  const contextValue: LabelSetsContextValue = {
    getLabelSet,
    setLabelSet,
  };

  return (
    <LabelSetsContext.Provider value={contextValue}>
      {children}
    </LabelSetsContext.Provider>
  );
}
