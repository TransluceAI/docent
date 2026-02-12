'use client';

import { useCallback, useEffect, useRef } from 'react';
import { ComplexFilter } from '@/app/types/collectionTypes';
import { FilterListItem } from '@/app/types/filterTypes';
import {
  useUpdateFilterMutation,
  useListFiltersQuery,
} from '@/app/api/filterApi';
import { toast } from 'sonner';
import { getRtkQueryErrorMessage } from '@/lib/rtkQueryError';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  setActiveFilterId,
  clearActiveFilterId,
} from '@/app/store/savedFilterSlice';

function filtersEqual(a: ComplexFilter, b: ComplexFilter): boolean {
  return (
    a.op === b.op && JSON.stringify(a.filters) === JSON.stringify(b.filters)
  );
}

interface UseSavedFiltersOptions {
  collectionId: string;
  surfaceId: string;
  currentFilter: ComplexFilter | null | undefined;
  onApplyFilter: (filter: ComplexFilter) => void;
}

export function useSavedFilters({
  collectionId,
  surfaceId,
  currentFilter,
  onApplyFilter,
}: UseSavedFiltersOptions) {
  const dispatch = useAppDispatch();
  const activeFilterId = useAppSelector(
    (state) => state.savedFilter.activeFilterIds[surfaceId] ?? null
  );
  const { data: filters } = useListFiltersQuery(collectionId);
  const activeFilter = activeFilterId
    ? (filters?.find((f) => f.id === activeFilterId) ?? null)
    : null;

  const [updateFilter, { isLoading: isUpdating }] = useUpdateFilterMutation();

  // Tracks whether we've applied a filter whose prop update may be async.
  // Prevents the clear-on-empty guard from racing with the prop update.
  const pendingApplyRef = useRef(false);

  // Distinguishes "empty because we just navigated here" (restore the saved
  // filter) from "empty because the user cleared all conditions".
  const everHadConditionsRef = useRef(false);

  const hasActiveConditions =
    currentFilter != null &&
    currentFilter.filters != null &&
    currentFilter.filters.length > 0;

  if (hasActiveConditions && pendingApplyRef.current) {
    pendingApplyRef.current = false;
  }
  if (hasActiveConditions) {
    everHadConditionsRef.current = true;
  }

  useEffect(() => {
    if (
      hasActiveConditions ||
      activeFilterId === null ||
      pendingApplyRef.current
    ) {
      return;
    }

    if (!everHadConditionsRef.current && activeFilter) {
      // Mounted with a previously-active saved filter — restore its conditions
      pendingApplyRef.current = true;
      onApplyFilter(activeFilter.filter);
    }
  }, [
    hasActiveConditions,
    activeFilterId,
    activeFilter,
    dispatch,
    surfaceId,
    onApplyFilter,
  ]);

  const isDirty =
    activeFilter != null &&
    (currentFilter == null
      ? activeFilter.filter.filters.length > 0
      : !filtersEqual(currentFilter, activeFilter.filter));

  const handleSelectFilter = useCallback(
    (filter: FilterListItem) => {
      if (isDirty) {
        const confirmed = window.confirm(
          'You have unsaved changes to the current filter. Discard them?'
        );
        if (!confirmed) return;
      }
      dispatch(setActiveFilterId({ surfaceId, filterId: filter.id }));
      pendingApplyRef.current = true;
      onApplyFilter(filter.filter);
    },
    [isDirty, onApplyFilter, dispatch, surfaceId]
  );

  const handleFilterDeleted = useCallback(
    (filterId: string) => {
      if (activeFilterId === filterId) {
        dispatch(clearActiveFilterId(surfaceId));
      }
    },
    [activeFilterId, dispatch, surfaceId]
  );

  const handleDeselect = useCallback(() => {
    dispatch(clearActiveFilterId(surfaceId));
  }, [dispatch, surfaceId]);

  const handleSaveSuccess = useCallback(
    (filter: FilterListItem) => {
      dispatch(setActiveFilterId({ surfaceId, filterId: filter.id }));
    },
    [dispatch, surfaceId]
  );

  const handleDiscard = useCallback(() => {
    if (!activeFilter) return;
    onApplyFilter(activeFilter.filter);
  }, [activeFilter, onApplyFilter]);

  const handleUpdate = async () => {
    if (!activeFilter || !currentFilter) return;

    try {
      await updateFilter({
        collectionId,
        filterId: activeFilter.id,
        filter: currentFilter,
      }).unwrap();
      toast.success(`Filter "${activeFilter.name || 'Untitled'}" updated`);
    } catch (err) {
      const parsed = getRtkQueryErrorMessage(err, 'Failed to update filter');
      toast.error(parsed.message);
    }
  };

  const saveMode: 'save' | 'save-as' =
    activeFilter != null ? 'save-as' : 'save';

  return {
    activeFilterId,
    activeFilter,
    isDirty,
    isUpdating,
    hasActiveConditions,
    saveMode,
    handleSelectFilter,
    handleFilterDeleted,
    handleDeselect,
    handleSaveSuccess,
    handleUpdate,
    handleDiscard,
  };
}
