import type { TypedUseSelectorHook } from 'react-redux';
import { useDispatch, useSelector } from 'react-redux';

import type { RootState, AppDispatch } from './store';
import { createSelector } from '@reduxjs/toolkit';

// Use throughout your app instead of plain `useDispatch` and `useSelector`
export const useAppDispatch = () => useDispatch<AppDispatch>();
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;

type SelectorFunction<T> = (state: RootState) => T;

type SelectorReturnTypes<T extends SelectorFunction<any>[]> = {
  [K in keyof T]: T[K] extends SelectorFunction<infer R> ? R : never;
};

export function createAppSelector<T extends ((state: RootState) => any)[], R>(
  selectors: [...T],
  outputSelector: (...args: { [K in keyof T]: ReturnType<T[K]> }) => R
): (state: RootState) => R {
  return createSelector(...selectors, outputSelector) as unknown as (
    state: RootState
  ) => R;
}

/*
Usage example
createAppSelector([(state) => state.diff.transcriptDiffsByKey, (state) => state.diff.diffsReport], (diffs, diffsReport) => {
    if (!diffsReport) {
        return [];
    }
    return Object.values(diffs).filter(diff => diff.diffs_report_id === diffsReport.id);
})
*/
