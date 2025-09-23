'use client';
import { createContext, useCallback, useContext, useState } from 'react';
import { SchemaDefinition } from '@/app/types/schema';
import {
  JudgeRunLabel,
  JudgeResultWithCitations,
} from '@/app/store/rubricSlice';
import { useGetRubricQuery } from '@/app/api/rubricApi';

export type Operator = '==' | '!=' | '<' | '<=' | '>' | '>=' | 'contains';

export type JudgeFilter = {
  path: string;
  op: Operator;
  value: any;
};

interface ResultFilterControlsContextValue {
  schema: SchemaDefinition | undefined;
  options: string[];
  filters: JudgeFilter[];
  setFilters: (filters: JudgeFilter[]) => void;
  labeled: boolean;
  setLabeled: (labeled: boolean) => void;
  applyFilters: (
    results: JudgeResultWithCitations[],
    labels?: JudgeRunLabel[]
  ) => JudgeResultWithCitations[];
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
  const [labeled, setLabeled] = useState<boolean>(false);

  // Only support one level of nesting for now
  const options: string[] = Object.keys(schema?.properties ?? {});

  const compareValues = (
    itemValue: string | number,
    filterValue: string | number,
    op: Operator
  ): boolean => {
    const itemType = typeof itemValue;
    const filterType = typeof filterValue;

    // Use a string bc discriminant is matched by reference in JS switch statements
    const typeKey = `${itemType}-${filterType}`;
    switch (typeKey) {
      case 'number-number':
        if (op === '==') return itemValue === filterValue;
        if (op === '!=') return itemValue !== filterValue;
        if (op === '<') return itemValue < filterValue;
        if (op === '<=') return itemValue <= filterValue;
        if (op === '>') return itemValue > filterValue;
        if (op === '>=') return itemValue >= filterValue;
        break;
      case 'string-string':
        if (op === '==') return itemValue === filterValue;
        if (op === '!=') return itemValue !== filterValue;
        if (op === 'contains')
          return (itemValue as string)
            .toLowerCase()
            .includes((filterValue as string).toLowerCase());
        break;
      default:
        return false;
    }
    return false;
  };

  const _applyFilters = useCallback(
    (result: JudgeResultWithCitations) => {
      return filters.every((filter) => {
        // If the value is a citation, we want to use the text
        let value = result.output[filter.path];
        if (value.text) value = value.text;

        return compareValues(value, filter.value, filter.op);
      });
    },
    [filters]
  );

  const applyFilters = useCallback(
    // This assumes that there's a unique label and result per agent_run_id
    (results: JudgeResultWithCitations[], labels?: JudgeRunLabel[]) => {
      if (labeled) {
        const labeledResults = results.filter((result) => {
          const label = labels?.find(
            (l) => l.agent_run_id === result.agent_run_id
          );
          return label !== undefined;
        });
        return labeledResults.filter((result) => _applyFilters(result));
      }

      const newResults = results.filter((result) => _applyFilters(result));
      return newResults;
    },
    [_applyFilters, labeled]
  );

  const getValidOps = (key: string): Operator[] => {
    const property = schema?.properties[key];

    if (!property) return [];

    if (property.type === 'string' && 'enum' in property) {
      return ['==', '!='];
    }

    if (property.type === 'integer') {
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
    labeled,
    setLabeled,
    applyFilters,
    getValidOps,
  };

  return (
    <ResultFilterControlsContext.Provider value={valueForProvider}>
      {children}
    </ResultFilterControlsContext.Provider>
  );
}
