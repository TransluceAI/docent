'use client';

import { ComplexFilter } from '@/app/types/collectionTypes';
import { SaveFilterPopover } from './SaveFilterDialog';
import { SavedFiltersDropdown } from './SavedFiltersDropdown';
import { ActiveFilterBanner } from './ActiveFilterBanner';
import { useSavedFilters } from '@/hooks/use-saved-filters';

interface FilterActionsBarProps {
  collectionId: string;
  surfaceId: string;
  currentFilter: ComplexFilter | null | undefined;
  onApplyFilter: (filter: ComplexFilter) => void;
  onClearFilter?: () => void;
  children?: React.ReactNode;
}

export function FilterActionsBar({
  collectionId,
  surfaceId,
  currentFilter,
  onApplyFilter,
  onClearFilter,
  children,
}: FilterActionsBarProps) {
  const {
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
  } = useSavedFilters({
    collectionId,
    surfaceId,
    currentFilter,
    onApplyFilter,
  });

  return (
    <>
      <SavedFiltersDropdown
        collectionId={collectionId}
        activeFilterId={activeFilterId}
        onSelectFilter={handleSelectFilter}
        onFilterDeleted={handleFilterDeleted}
      />
      {activeFilter ? (
        <ActiveFilterBanner
          activeFilter={activeFilter}
          isDirty={isDirty}
          isUpdating={isUpdating}
          onClose={() => {
            handleDeselect();
            onClearFilter?.();
          }}
          onUnlink={handleDeselect}
          onDiscard={handleDiscard}
          onUpdate={handleUpdate}
          collectionId={collectionId}
          currentFilter={currentFilter ?? null}
          hasActiveConditions={hasActiveConditions}
          onSaveSuccess={handleSaveSuccess}
        >
          {children}
        </ActiveFilterBanner>
      ) : (
        <>
          {children}
          {currentFilter && (
            <SaveFilterPopover
              collectionId={collectionId}
              currentFilter={currentFilter}
              disabled={!hasActiveConditions}
              mode={saveMode}
              onSaveSuccess={handleSaveSuccess}
            />
          )}
        </>
      )}
    </>
  );
}
