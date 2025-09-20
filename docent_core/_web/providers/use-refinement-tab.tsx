import { createContext, useContext, useState } from 'react';

interface ActiveTabContextValue {
  activeTab: 'refine' | 'analyze' | 'label';
  setActiveTab: (tab: 'refine' | 'analyze' | 'label') => void;
  refinementJobId: string | null;
  setRefinementJobId: (jobId: string | null) => void;
}

const ActiveTabContext = createContext<ActiveTabContextValue>({
  activeTab: 'refine',
  setActiveTab: () => {},
  refinementJobId: null,
  setRefinementJobId: () => {},
});

export function useRefinementTab() {
  const ctx = useContext(ActiveTabContext);
  if (!ctx) {
    throw new Error(
      'useRefinementTab must be used within a RefinementTabProvider'
    );
  }
  return ctx;
}

export function RefinementTabProvider({
  children,
}: {
  children: React.ReactNode;
  collectionId: string;
  rubricId: string;
}) {
  const [activeTab, setActiveTab] = useState<'refine' | 'analyze' | 'label'>(
    'refine'
  );

  const [refinementJobId, setRefinementJobId] = useState<string | null>(null);

  const contextValue: ActiveTabContextValue = {
    activeTab,
    setActiveTab,
    refinementJobId,
    setRefinementJobId,
  };

  return (
    <ActiveTabContext.Provider value={contextValue}>
      {children}
    </ActiveTabContext.Provider>
  );
}
