'use client';

import { useMemo, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { SingleCombobox } from './Combobox';
import {
  useListFiltersQuery,
  useCreateFilterMutation,
} from '@/app/api/filterApi';
import { useGetCollectionsQuery } from '@/app/api/collectionApi';
import { useGetCollectionsPermissionsQuery } from '@/lib/permissions/collabSlice';
import { PERMISSION_LEVELS } from '@/lib/permissions/types';
import { FilterListItem } from '@/app/types/filterTypes';
import { toast } from 'sonner';
import { getRtkQueryErrorMessage } from '@/lib/rtkQueryError';
import { Copy, Loader2 } from 'lucide-react';

interface CopyFiltersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  collectionId: string;
}

export function CopyFiltersDialog({
  open,
  onOpenChange,
  collectionId,
}: CopyFiltersDialogProps) {
  const { data: filters } = useListFiltersQuery(collectionId);
  const { data: collections } = useGetCollectionsQuery(undefined, {
    skip: !open,
  });

  const otherCollectionIds = useMemo(
    () =>
      (collections ?? []).filter((c) => c.id !== collectionId).map((c) => c.id),
    [collections, collectionId]
  );

  const { data: permissionsData } = useGetCollectionsPermissionsQuery(
    otherCollectionIds,
    { skip: !open || otherCollectionIds.length === 0 }
  );

  const writableCollectionOptions = useMemo(() => {
    if (!collections || !permissionsData) return [];
    const perms = permissionsData.collection_permissions;
    return collections
      .filter((c) => {
        if (c.id === collectionId) return false;
        const level = perms[c.id];
        if (!level) return false;
        return PERMISSION_LEVELS[level] >= PERMISSION_LEVELS.write;
      })
      .map((c) => ({
        value: c.id,
        label: c.name ?? c.id,
      }));
  }, [collections, permissionsData, collectionId]);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [targetCollectionId, setTargetCollectionId] = useState<string | null>(
    null
  );
  const [isCopying, setIsCopying] = useState(false);
  const [createFilter] = useCreateFilterMutation();

  const allSelected =
    filters !== undefined &&
    filters.length > 0 &&
    selectedIds.size === filters.length;

  const toggleAll = () => {
    if (!filters) return;
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filters.map((f) => f.id)));
    }
  };

  const toggleFilter = (filterId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(filterId)) {
        next.delete(filterId);
      } else {
        next.add(filterId);
      }
      return next;
    });
  };

  const canCopy = selectedIds.size > 0 && targetCollectionId !== null;

  const handleCopy = async () => {
    if (!filters || !targetCollectionId) return;

    const selected = filters.filter((f) => selectedIds.has(f.id));
    setIsCopying(true);

    const results = await Promise.allSettled(
      selected.map((f) =>
        createFilter({
          collectionId: targetCollectionId,
          filter: f.filter,
          name: f.name,
          description: f.description,
        }).unwrap()
      )
    );

    const succeeded = results.filter((r) => r.status === 'fulfilled').length;
    const failed = results.filter((r) => r.status === 'rejected');

    if (failed.length === 0) {
      toast.success(
        `Copied ${succeeded} ${succeeded === 1 ? 'filter' : 'filters'}`
      );
      onOpenChange(false);
      setSelectedIds(new Set());
      setTargetCollectionId(null);
    } else if (succeeded > 0) {
      toast.warning(
        `Copied ${succeeded} ${succeeded === 1 ? 'filter' : 'filters'}, ${failed.length} failed`
      );
    } else {
      const firstError = failed[0];
      const parsed = getRtkQueryErrorMessage(
        firstError.status === 'rejected' ? firstError.reason : null,
        'Failed to copy filters'
      );
      toast.error(parsed.message);
    }

    setIsCopying(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setSelectedIds(new Set());
      setTargetCollectionId(null);
    }
    onOpenChange(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Copy Filters</DialogTitle>
          <DialogDescription>
            Copy saved filters to another collection.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <FilterSelectionTable
            filters={filters ?? []}
            selectedIds={selectedIds}
            allSelected={allSelected}
            onToggleAll={toggleAll}
            onToggleFilter={toggleFilter}
          />

          <div>
            <div className="text-xs text-muted-foreground mb-1">
              Target collection
            </div>
            <SingleCombobox
              value={targetCollectionId}
              onChange={setTargetCollectionId}
              options={writableCollectionOptions}
              placeholder="Select collection"
              searchPlaceholder="Search collections..."
              emptyMessage="No writable collections found."
              triggerClassName="w-full justify-between text-xs"
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            onClick={handleCopy}
            disabled={!canCopy || isCopying}
            size="sm"
          >
            {isCopying ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
            ) : (
              <Copy className="h-3.5 w-3.5 mr-1.5" />
            )}
            Copy{selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FilterSelectionTable({
  filters,
  selectedIds,
  allSelected,
  onToggleAll,
  onToggleFilter,
}: {
  filters: FilterListItem[];
  selectedIds: Set<string>;
  allSelected: boolean;
  onToggleAll: () => void;
  onToggleFilter: (id: string) => void;
}) {
  return (
    <div className="border rounded-md max-h-60 overflow-y-auto">
      <div className="flex items-center gap-2 px-3 py-2 border-b bg-secondary/50 sticky top-0">
        <Checkbox
          checked={allSelected}
          onCheckedChange={onToggleAll}
          aria-label="Select all filters"
        />
        <span className="text-xs text-muted-foreground font-medium">
          {filters.length} {filters.length === 1 ? 'filter' : 'filters'}
        </span>
      </div>
      {filters.map((filter) => (
        <label
          key={filter.id}
          className="flex items-center gap-2 px-3 py-2 hover:bg-secondary/30 cursor-pointer"
        >
          <Checkbox
            checked={selectedIds.has(filter.id)}
            onCheckedChange={() => onToggleFilter(filter.id)}
          />
          <div className="flex-1 min-w-0">
            <div className="text-sm truncate">
              {filter.name || 'Untitled Filter'}
            </div>
            {filter.description && (
              <div className="text-xs text-muted-foreground truncate">
                {filter.description}
              </div>
            )}
          </div>
        </label>
      ))}
    </div>
  );
}
