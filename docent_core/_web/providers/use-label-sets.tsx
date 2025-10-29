import { LabelSet, useGetLabelSetsQuery } from '@/app/api/labelApi';
import { createContext, useContext, useMemo, useEffect } from 'react';
import { useLocalStorage } from 'usehooks-ts';

interface LabelSetsContextValue {
  activeLabelSet: LabelSet | null;
  activeLabelSetId: string | null;
  activeLabelSetName: string | null;
  setActiveLabelSet: (labelSet: LabelSet | null) => void;
  clearLabelSets: () => void;
}

const LabelSetsContext = createContext<LabelSetsContextValue>({
  activeLabelSet: null,
  activeLabelSetId: null,
  activeLabelSetName: null,
  setActiveLabelSet: () => {},
  clearLabelSets: () => {},
});

export function useLabelSets() {
  const ctx = useContext(LabelSetsContext);
  if (!ctx) {
    throw new Error('useLabelSets must be used within a LabelSetsProvider');
  }
  return ctx;
}

export function LabelSetsProvider({
  children,
  rubricId,
  collectionId,
}: {
  children: React.ReactNode;
  rubricId: string;
  collectionId: string;
}) {
  const [labelSetsByRubric, setLabelSetsByRubric] = useLocalStorage<
    Record<string, LabelSet | null>
  >('activeLabelSetByRubric', {});

  // Fetch all available label sets to validate stored references
  const { data: availableLabelSets, isFetching } = useGetLabelSetsQuery({
    collectionId,
  });

  const activeLabelSet = useMemo(
    () => labelSetsByRubric[rubricId] || null,
    [labelSetsByRubric, rubricId]
  );

  // Validate and sync label set data with server
  useEffect(() => {
    if (!availableLabelSets || !activeLabelSet || isFetching) return;

    // Find the current version from the server
    const currentLabelSet = availableLabelSets.find(
      (ls) => ls.id === activeLabelSet.id
    );

    if (!currentLabelSet) {
      // Label set was deleted - clear it from storage
      setLabelSetsByRubric((prev) => {
        const { [rubricId]: _, ...rest } = prev;
        return rest;
      });
    } else if (
      currentLabelSet.name !== activeLabelSet.name ||
      currentLabelSet.description !== activeLabelSet.description
    ) {
      // Label set was updated - sync the new data
      setLabelSetsByRubric((prev) => ({
        ...prev,
        [rubricId]: currentLabelSet,
      }));
    }
  }, [
    availableLabelSets,
    activeLabelSet,
    rubricId,
    setLabelSetsByRubric,
    isFetching,
  ]);

  const setActiveLabelSet = (newLabelSet: LabelSet | null) => {
    setLabelSetsByRubric((prev) => ({
      ...prev,
      [rubricId]: newLabelSet,
    }));
  };

  const clearLabelSets = () => {
    setLabelSetsByRubric((prev) => {
      const { [rubricId]: _, ...rest } = prev;
      return rest;
    });
  };

  const contextValue: LabelSetsContextValue = {
    activeLabelSet,
    activeLabelSetId: activeLabelSet?.id || null,
    activeLabelSetName: activeLabelSet?.name || null,
    setActiveLabelSet,
    clearLabelSets,
  };

  return (
    <LabelSetsContext.Provider value={contextValue}>
      {children}
    </LabelSetsContext.Provider>
  );
}
