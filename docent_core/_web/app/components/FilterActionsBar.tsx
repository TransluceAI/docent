'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Save } from 'lucide-react';
import { ComplexFilter } from '@/app/types/collectionTypes';
import { SaveFilterDialog } from './SaveFilterDialog';
import { SavedFiltersDropdown } from './SavedFiltersDropdown';

interface FilterActionsBarProps {
  collectionId: string;
  currentFilter: ComplexFilter | null | undefined;
  onApplyFilter: (filter: ComplexFilter) => void;
}

export function FilterActionsBar({
  collectionId,
  currentFilter,
  onApplyFilter,
}: FilterActionsBarProps) {
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  const hasActiveFilter =
    currentFilter && currentFilter.filters && currentFilter.filters.length > 0;

  return (
    <div className="flex items-center gap-1.5">
      <SavedFiltersDropdown
        collectionId={collectionId}
        onApplyFilter={onApplyFilter}
      />
      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs gap-1"
        disabled={!hasActiveFilter}
        onClick={() => setSaveDialogOpen(true)}
        title={
          hasActiveFilter ? 'Save current filters' : 'Add filters to save them'
        }
      >
        <Save className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-muted-foreground">Save</span>
      </Button>

      {currentFilter && (
        <SaveFilterDialog
          open={saveDialogOpen}
          onOpenChange={setSaveDialogOpen}
          collectionId={collectionId}
          currentFilter={currentFilter}
        />
      )}
    </div>
  );
}
