import { LabelSet } from '@/app/api/labelApi';
import { createContext, useContext, useMemo } from 'react';
import { useLocalStorage } from 'usehooks-ts';

interface LabelSetsContextValue {
  labelSets: LabelSet[];
  setLabelSets: (labelSets: LabelSet[]) => void;
  clearLabelSets: () => void;
}

const LabelSetsContext = createContext<LabelSetsContextValue>({
  labelSets: [],
  setLabelSets: () => {},
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
}: {
  children: React.ReactNode;
  rubricId: string;
}) {
  const [labelSetsByRubric, setLabelSetsByRubric] = useLocalStorage<
    Record<string, LabelSet[]>
  >('labelSetsByRubric', {});

  const labelSets = useMemo(
    () => labelSetsByRubric[rubricId] || [],
    [labelSetsByRubric, rubricId]
  );

  const setLabelSets = (newLabelSets: LabelSet[]) => {
    setLabelSetsByRubric((prev) => ({
      ...prev,
      [rubricId]: newLabelSets,
    }));
  };

  const clearLabelSets = () => {
    setLabelSetsByRubric((prev) => {
      const { [rubricId]: _, ...rest } = prev;
      return rest;
    });
  };

  const contextValue: LabelSetsContextValue = {
    labelSets,
    setLabelSets,
    clearLabelSets,
  };

  return (
    <LabelSetsContext.Provider value={contextValue}>
      {children}
    </LabelSetsContext.Provider>
  );
}
