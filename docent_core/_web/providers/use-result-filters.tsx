'use client';
import { createContext, useContext, useState } from 'react';
import { SchemaDefinition } from '@/app/types/schema';
import { useGetRubricQuery } from '@/app/api/rubricApi';

export type Operator = '==' | '!=' | '<' | '<=' | '>' | '>=' | 'contains';

export type JudgeFilter = {
  path: string;
  op: Operator;
  value: any;
};

export type ViewMode =
  | 'all'
  | 'labeled_disagreement'
  | 'missing_labels'
  | 'incomplete_labels';

interface ResultFilterControlsContextValue {
  schema: SchemaDefinition | undefined;
  options: string[];
  filters: JudgeFilter[];
  setFilters: (filters: JudgeFilter[]) => void;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  getValidOps: (key: string) => Operator[];
}

const ResultFilterControlsContext =
  createContext<ResultFilterControlsContextValue | null>(null);

export function useResultFilterControls(): ResultFilterControlsContextValue {
  const ctx = useContext(ResultFilterControlsContext);
  if (!ctx)
    throw new Error(
      'ResultFilterControls components must be used within a ResultFilterControlsProvider'
    );
  return ctx;
}

interface ResultFilterControlsProviderProps {
  rubricId: string;
  collectionId: string;
  children: React.ReactNode;
}

export function ResultFilterControlsProvider({
  rubricId,
  collectionId,
  children,
}: ResultFilterControlsProviderProps) {
  const { data: rubric } = useGetRubricQuery({
    rubricId,
    collectionId,
  });

  const schema = rubric?.output_schema as SchemaDefinition | undefined;

  const [filters, setFilters] = useState<JudgeFilter[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>('all');

  // Only support one level of nesting for now
  const options: string[] = Object.keys(schema?.properties ?? {});

  const getValidOps = (key: string): Operator[] => {
    const property = schema?.properties[key];

    if (!property) return [];

    if (property.type === 'string' && 'enum' in property) {
      return ['==', '!='];
    }

    if (property.type === 'integer' || property.type === 'number') {
      return ['==', '!=', '<', '<=', '>', '>='];
    }

    if (property.type === 'string' && 'citations' in property) {
      return ['==', '!=', 'contains'];
    }

    if (property.type === 'boolean') {
      return ['==', '!='];
    }

    return [];
  };

  const valueForProvider: ResultFilterControlsContextValue = {
    schema,
    options,
    filters,
    setFilters,
    viewMode,
    setViewMode,
    getValidOps,
  };

  return (
    <ResultFilterControlsContext.Provider value={valueForProvider}>
      {children}
    </ResultFilterControlsContext.Provider>
  );
}
