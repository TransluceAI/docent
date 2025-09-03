'use client';

import { CircleX, Pencil, Eraser } from 'lucide-react';
import {
  PrimitiveFilter,
  CollectionFilter,
  ComplexFilter,
} from '@/app/types/collectionTypes';

interface FilterChipsProps {
  filters: ComplexFilter | undefined | null;
  onRemoveFilter: (filterId: string) => void;
  onEditFilter: (filter: PrimitiveFilter) => void;
  onClearAllFilters: () => void;
  className?: string;
  disabled?: boolean;
}

export const FilterChips = ({
  filters,
  onRemoveFilter,
  onEditFilter,
  onClearAllFilters,
  className,
  disabled = false,
}: FilterChipsProps) => {
  const currentFilters = filters?.filters || [];

  if (currentFilters.length === 0) {
    return null;
  }

  return (
    <div className={`flex flex-wrap gap-1.5 ${className || ''}`}>
      {currentFilters.map((subFilter: CollectionFilter) => (
        <div
          key={subFilter.id}
          className="inline-flex items-center gap-x-1 text-[11px] bg-indigo-bg text-primary border border-indigo-border pl-1.5 pr-1 py-0.5 rounded-md"
        >
          {(() => {
            if (subFilter.type === 'primitive') {
              const filterCast = subFilter as PrimitiveFilter;
              return (
                <>
                  <span className="font-mono">
                    {filterCast.key_path.join('.')}
                  </span>
                  <span className="text-indigo-400 font-mono">
                    {filterCast.op || '=='}
                  </span>
                  <span className="font-mono">{String(filterCast.value)}</span>
                </>
              );
            } else {
              return `${subFilter.type} filter`;
            }
          })()}
          {subFilter.type === 'primitive' && (
            <button
              onClick={() => onEditFilter(subFilter as PrimitiveFilter)}
              className="p-0.5 text-primary hover:text-primary/50 transition-colors"
              title="Edit filter"
              disabled={disabled}
            >
              <Pencil size={10} />
            </button>
          )}
          <button
            onClick={() => onRemoveFilter(subFilter.id)}
            className="p-0.5 text-primary hover:text-primary/50 transition-colors"
            title="Remove filter"
            disabled={disabled}
          >
            <CircleX size={10} />
          </button>
        </div>
      ))}
      <button
        onClick={onClearAllFilters}
        className="inline-flex items-center gap-x-1 text-[11px] bg-red-bg text-primary border border-red-border px-1.5 py-0.5 rounded-md hover:bg-red-bg/50 transition-colors"
        disabled={disabled}
      >
        Clear All
        <Eraser size={10} />
      </button>
    </div>
  );
};
