'use client';

import { useCallback, useEffect, useRef } from 'react';
import { ComplexFilter } from '@/app/types/collectionTypes';
import { FilterListItem } from '@/app/types/filterTypes';
import { SaveFilterPopover } from './SaveFilterDialog';
import { SavedFiltersDropdown } from './SavedFiltersDropdown';
import {
  useUpdateFilterMutation,
  useListFiltersQuery,
} from '@/app/api/filterApi';
import { Button } from '@/components/ui/button';
import { Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { getRtkQueryErrorMessage } from '@/lib/rtkQueryError';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  setActiveFilterId,
  clearActiveFilterId,
} from '@/app/store/savedFilterSlice';

interface FilterActionsBarProps {
  collectionId: string;
  currentFilter: ComplexFilter | null | undefined;
  onApplyFilter: (filter: ComplexFilter) => void;
}

function filtersEqual(a: ComplexFilter, b: ComplexFilter): boolean {
  return (
    a.op === b.op && JSON.stringify(a.filters) === JSON.stringify(b.filters)
  );
}

export function FilterActionsBar({
  collectionId,
  currentFilter,
  onApplyFilter,
}: FilterActionsBarProps) {
  const dispatch = useAppDispatch();
  const activeFilterId = useAppSelector(
    (state) => state.savedFilter.activeFilterIds[collectionId] ?? null
  );
  const { data: filters } = useListFiltersQuery(collectionId);
  const activeFilter = activeFilterId
    ? (filters?.find((f) => f.id === activeFilterId) ?? null)
    : null;

  const [updateFilter, { isLoading: isUpdating }] = useUpdateFilterMutation();

  // Tracks whether we've applied a filter whose prop update may be async.
  // Prevents the clear-on-empty guard from racing with the prop update.
  const pendingApplyRef = useRef(false);

  const hasActiveConditions =
    currentFilter != null &&
    currentFilter.filters != null &&
    currentFilter.filters.length > 0;

  if (hasActiveConditions && pendingApplyRef.current) {
    pendingApplyRef.current = false;
  }

  useEffect(() => {
    if (
      !hasActiveConditions &&
      activeFilterId !== null &&
      !pendingApplyRef.current
    ) {
      dispatch(clearActiveFilterId(collectionId));
    }
  }, [hasActiveConditions, activeFilterId, dispatch, collectionId]);

  const isDirty =
    activeFilter != null &&
    currentFilter != null &&
    !filtersEqual(currentFilter, activeFilter.filter);

  const handleSelectFilter = useCallback(
    (filter: FilterListItem) => {
      if (isDirty) {
        const confirmed = window.confirm(
          'You have unsaved changes to the current filter. Discard them?'
        );
        if (!confirmed) return;
      }
      dispatch(setActiveFilterId({ collectionId, filterId: filter.id }));
      pendingApplyRef.current = true;
      onApplyFilter(filter.filter);
    },
    [isDirty, onApplyFilter, dispatch, collectionId]
  );

  const handleFilterDeleted = useCallback(
    (filterId: string) => {
      if (activeFilterId === filterId) {
        dispatch(clearActiveFilterId(collectionId));
      }
    },
    [activeFilterId, dispatch, collectionId]
  );

  const handleDeselect = useCallback(() => {
    dispatch(clearActiveFilterId(collectionId));
  }, [dispatch, collectionId]);

  const handleSaveSuccess = useCallback(
    (filter: FilterListItem) => {
      dispatch(setActiveFilterId({ collectionId, filterId: filter.id }));
    },
    [dispatch, collectionId]
  );

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

  const saveMode = activeFilter != null ? 'save-as' : 'save';

  return (
    <div className="flex flex-wrap items-center gap-1.5 min-w-0">
      <SavedFiltersDropdown
        collectionId={collectionId}
        activeFilterId={activeFilterId}
        isDirty={isDirty}
        onSelectFilter={handleSelectFilter}
        onDeselect={handleDeselect}
        onFilterDeleted={handleFilterDeleted}
      />
      {isDirty && (
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs gap-1"
          onClick={handleUpdate}
          disabled={isUpdating}
          title="Update the saved filter with current conditions"
        >
          {isUpdating ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground" />
          )}
          <span className="text-muted-foreground">Update</span>
        </Button>
      )}
      {currentFilter && (
        <SaveFilterPopover
          collectionId={collectionId}
          currentFilter={currentFilter}
          disabled={!hasActiveConditions}
          mode={saveMode}
          onSaveSuccess={handleSaveSuccess}
        />
      )}
    </div>
  );
}
