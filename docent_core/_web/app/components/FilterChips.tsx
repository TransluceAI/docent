'use client';

import { useCallback } from 'react';
import { CircleX, Pencil, Eraser, Eye, EyeOff } from 'lucide-react';
import {
  PrimitiveFilter,
  CollectionFilter,
  ComplexFilter,
} from '@/app/types/collectionTypes';
import { cn } from '@/lib/utils';
import { formatFilterFieldLabel } from '../utils/formatMetadataField';

export const toggleFilterDisabledState = (
  filterGroup: ComplexFilter | null,
  filterId: string
): ComplexFilter | null => {
  if (!filterGroup) {
    return null;
  }

  let changed = false;
  const updatedFilters = filterGroup.filters.map((filterItem) => {
    if (filterItem.id !== filterId) {
      return filterItem;
    }

    changed = true;
    return {
      ...filterItem,
      disabled: !(filterItem.disabled ?? false),
    };
  });

  if (!changed) {
    return filterGroup;
  }

  return {
    ...filterGroup,
    filters: updatedFilters,
  };
};

interface FilterChipsProps {
  filters: ComplexFilter | undefined | null;
  onFiltersChange: (filters: ComplexFilter | null) => void;
  onRequestEdit?: (filter: PrimitiveFilter) => void;
  allowToggle?: boolean;
  className?: string;
  readOnly?: boolean;
}

export const FilterChips = ({
  filters,
  onFiltersChange,
  onRequestEdit,
  allowToggle = true,
  className,
  readOnly = false,
}: FilterChipsProps) => {
  const handleRemove = useCallback(
    (filterId: string) => {
      if (!filters) return;
      const updated = filters.filters.filter((f) => f.id !== filterId);
      onFiltersChange(
        updated.length === 0 ? null : { ...filters, filters: updated }
      );
    },
    [filters, onFiltersChange]
  );

  const handleEdit = useCallback(
    (filter: PrimitiveFilter) => {
      handleRemove(filter.id);
      onRequestEdit?.(filter);
    },
    [handleRemove, onRequestEdit]
  );

  const handleClearAll = useCallback(() => {
    onFiltersChange(null);
  }, [onFiltersChange]);

  const handleToggle = useCallback(
    (filterId: string) => {
      const updated = toggleFilterDisabledState(filters ?? null, filterId);
      if (updated && updated !== filters) {
        onFiltersChange(updated);
      }
    },
    [filters, onFiltersChange]
  );
  const currentFilters = filters?.filters || [];

  if (currentFilters.length === 0) {
    return null;
  }

  return (
    <div className={cn('flex flex-wrap gap-1.5 min-w-0', className)}>
      {currentFilters.map((subFilter: CollectionFilter) => {
        const isDisabled = subFilter.disabled === true;
        return (
          <div
            key={subFilter.id}
            className={cn(
              'inline-flex items-center gap-x-1 text-[11px] border pl-1.5 pr-1 py-0.5 rounded-md transition-colors min-w-0 max-w-full overflow-hidden',
              isDisabled
                ? 'bg-muted text-muted-foreground border-dashed border-muted-foreground/50'
                : 'bg-indigo-bg text-primary border-indigo-border hover:bg-indigo-bg/80 hover:border-indigo-border/80'
            )}
          >
            {(() => {
              if (subFilter.type === 'primitive') {
                const filterCast = subFilter as PrimitiveFilter;
                const displayKey = formatFilterFieldLabel(
                  filterCast.key_path.join('.')
                );
                const displayValue = String(filterCast.value);
                return (
                  <>
                    <span
                      className="font-mono max-w-[160px] truncate"
                      title={displayKey}
                    >
                      {displayKey}
                    </span>
                    <span
                      className={cn(
                        'font-mono inline-block flex-shrink-0',
                        isDisabled
                          ? 'text-muted-foreground/70'
                          : 'text-indigo-400'
                      )}
                      title={filterCast.op || '=='}
                    >
                      {filterCast.op || '=='}
                    </span>
                    <span
                      className="font-mono max-w-[260px] truncate"
                      title={displayValue}
                    >
                      {displayValue}
                    </span>
                  </>
                );
              } else {
                return `${subFilter.type} filter`;
              }
            })()}
            {allowToggle && !readOnly && (
              <button
                onClick={() => handleToggle(subFilter.id)}
                className="flex-shrink-0 p-0.5 text-current hover:text-current/80 hover:bg-foreground/10 rounded-sm transition-colors"
                title={isDisabled ? 'Enable filter' : 'Disable filter'}
              >
                {isDisabled ? <Eye size={10} /> : <EyeOff size={10} />}
              </button>
            )}
            {subFilter.type === 'primitive' && onRequestEdit && !readOnly && (
              <button
                onClick={() => handleEdit(subFilter as PrimitiveFilter)}
                className="flex-shrink-0 p-0.5 text-current hover:text-current/80 hover:bg-foreground/10 rounded-sm transition-colors"
                title="Edit filter"
              >
                <Pencil size={10} />
              </button>
            )}
            {!readOnly && (
              <button
                onClick={() => handleRemove(subFilter.id)}
                className="flex-shrink-0 p-0.5 text-current hover:text-current/80 hover:bg-foreground/10 rounded-sm transition-colors"
                title="Remove filter"
              >
                <CircleX size={10} />
              </button>
            )}
          </div>
        );
      })}
      {currentFilters.length > 1 && !readOnly && (
        <button
          onClick={handleClearAll}
          className="inline-flex items-center gap-x-1 text-[11px] bg-red-bg text-primary border border-red-border px-1.5 py-0.5 rounded-md hover:bg-red-bg/50 transition-colors"
        >
          Clear All
          <Eraser size={10} />
        </button>
      )}
    </div>
  );
};
