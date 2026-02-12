'use client';

import React, { useState } from 'react';
import { ComplexFilter, PrimitiveFilter } from '@/app/types/collectionTypes';
import { FilterControls } from './FilterControls';
import { FilterChips } from './FilterChips';
import { SavedFiltersDropdown } from './SavedFiltersDropdown';
import { SaveFilterPopover } from './SaveFilterDialog';
import { ActiveFilterBanner } from './ActiveFilterBanner';
import { useParams } from 'next/navigation';
import { useFilterFields } from '@/hooks/use-filter-fields';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import { useSavedFilters } from '@/hooks/use-saved-filters';

interface TranscriptFilterControlsProps {
  collectionId?: string;
  surfaceId?: string;
  metadataData?: Record<string, Record<string, unknown>>;
  baseFilter: ComplexFilter | null | undefined;
  onFiltersChange: (filters: ComplexFilter | null) => void;
}

export const TranscriptFilterControls = ({
  collectionId: collectionIdProp,
  surfaceId = 'agent-runs',
  metadataData = {},
  baseFilter,
  onFiltersChange,
}: TranscriptFilterControlsProps) => {
  const params = useParams();
  const collectionId = collectionIdProp ?? (params.collection_id as string);
  const scopedSurfaceId = `${collectionId}:${surfaceId}`;
  const hasWritePermission = useHasCollectionWritePermission();
  const { fields: agentRunMetadataFields } = useFilterFields({
    collectionId,
    context: { mode: 'agent_runs' },
  });

  const [editingFilter, setEditingFilter] = useState<PrimitiveFilter | null>(
    null
  );

  const handleFiltersChange = (filters: ComplexFilter | null) => {
    onFiltersChange(filters);
    setEditingFilter(null);
  };

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
    surfaceId: scopedSurfaceId,
    currentFilter: baseFilter,
    onApplyFilter: handleFiltersChange,
  });

  const filterChips = (
    <FilterChips
      filters={baseFilter ?? null}
      onFiltersChange={handleFiltersChange}
      onRequestEdit={setEditingFilter}
    />
  );

  const savedFiltersDropdown = hasWritePermission ? (
    <SavedFiltersDropdown
      collectionId={collectionId}
      activeFilterId={activeFilterId}
      onSelectFilter={handleSelectFilter}
      onFilterDeleted={handleFilterDeleted}
    />
  ) : null;

  return (
    <div className="space-y-1.5">
      <FilterControls
        filters={baseFilter ?? null}
        onFiltersChange={handleFiltersChange}
        metadataFields={agentRunMetadataFields ?? []}
        collectionId={collectionId!}
        metadataData={metadataData}
        initialFilter={editingFilter}
        leadingSlot={savedFiltersDropdown}
      />
      {activeFilter ? (
        <ActiveFilterBanner
          activeFilter={activeFilter}
          isDirty={isDirty}
          isUpdating={isUpdating}
          onClose={() => {
            handleDeselect();
            handleFiltersChange(null);
          }}
          onUnlink={handleDeselect}
          onDiscard={handleDiscard}
          onUpdate={handleUpdate}
          collectionId={collectionId}
          currentFilter={baseFilter ?? null}
          hasActiveConditions={hasActiveConditions}
          onSaveSuccess={handleSaveSuccess}
        >
          {filterChips}
        </ActiveFilterBanner>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          {filterChips}
          {hasWritePermission && baseFilter && (
            <SaveFilterPopover
              collectionId={collectionId}
              currentFilter={baseFilter}
              disabled={!hasActiveConditions}
              mode={saveMode}
              onSaveSuccess={handleSaveSuccess}
            />
          )}
        </div>
      )}
    </div>
  );
};
