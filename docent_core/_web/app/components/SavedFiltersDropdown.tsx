'use client';

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import {
  useListFiltersQuery,
  useDeleteFilterMutation,
} from '@/app/api/filterApi';
import {
  ComplexFilter,
  CollectionFilter,
  PrimitiveFilter,
} from '@/app/types/collectionTypes';
import { FilterListItem } from '@/app/types/filterTypes';
import { Bookmark, ChevronDown, Trash2, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { getRtkQueryErrorMessage } from '@/lib/rtkQueryError';
import { formatFilterFieldLabel } from '../utils/formatMetadataField';

function collectPrimitives(filter: CollectionFilter): PrimitiveFilter[] {
  if (filter.type === 'primitive') {
    return [filter];
  }
  if (filter.type === 'complex') {
    return filter.filters.flatMap(collectPrimitives);
  }
  return [];
}

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

function formatRelativeDate(dateStr: string): string {
  const utcStr = dateStr.endsWith('Z') ? dateStr : `${dateStr}Z`;
  const diffSeconds = Math.round(
    (new Date(utcStr).getTime() - Date.now()) / 1000
  );
  const absDiff = Math.abs(diffSeconds);

  if (absDiff < 60) return rtf.format(0, 'second');
  if (absDiff < 3600) return rtf.format(-Math.round(absDiff / 60), 'minute');
  if (absDiff < 86400) return rtf.format(-Math.round(absDiff / 3600), 'hour');
  if (absDiff < 2592000) return rtf.format(-Math.round(absDiff / 86400), 'day');
  if (absDiff < 31536000)
    return rtf.format(-Math.round(absDiff / 2592000), 'month');
  return rtf.format(-Math.round(absDiff / 31536000), 'year');
}

const MAX_TOOLTIP_VALUE_LENGTH = 40;

function truncateValue(value: unknown): string {
  const str = String(value);
  if (str.length <= MAX_TOOLTIP_VALUE_LENGTH) return str;
  return `${str.slice(0, MAX_TOOLTIP_VALUE_LENGTH)}...`;
}

function buildFilterTooltip(filter: FilterListItem): string {
  const primitives = collectPrimitives(filter.filter);
  if (primitives.length === 0) return '';
  return primitives
    .map(
      (p) =>
        `\u2022 ${formatFilterFieldLabel(p.key_path.join('.'))} ${p.op} ${truncateValue(p.value)}`
    )
    .join('\n');
}

function FilterPreview({ filter }: { filter: FilterListItem }) {
  const count = collectPrimitives(filter.filter).length;

  return (
    <div className="mt-0.5 space-y-0.5">
      {filter.description && (
        <div className="text-xs text-muted-foreground truncate">
          {filter.description}
        </div>
      )}
      <div className="text-[10px] text-muted-foreground">
        {count} {count === 1 ? 'condition' : 'conditions'} &middot;{' '}
        {formatRelativeDate(filter.created_at)}
      </div>
    </div>
  );
}

interface SavedFiltersDropdownProps {
  collectionId: string;
  onApplyFilter: (filter: ComplexFilter) => void;
}

export function SavedFiltersDropdown({
  collectionId,
  onApplyFilter,
}: SavedFiltersDropdownProps) {
  const { data: filters, isLoading } = useListFiltersQuery(collectionId);
  const [deleteFilter, { isLoading: isDeleting }] = useDeleteFilterMutation();

  const handleApplyFilter = (filter: FilterListItem) => {
    onApplyFilter(filter.filter);
  };

  const handleDeleteFilter = async (
    e: React.MouseEvent,
    filterId: string,
    filterName: string | null
  ) => {
    e.stopPropagation();
    try {
      await deleteFilter({ collectionId, filterId }).unwrap();
      toast.success(`Filter "${filterName || 'Untitled'}" deleted`);
    } catch (err) {
      const parsed = getRtkQueryErrorMessage(err, 'Failed to delete filter');
      toast.error(parsed.message);
    }
  };

  const hasFilters = filters && filters.length > 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs gap-1"
          disabled={isLoading}
        >
          <Bookmark className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">Saved</span>
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="w-96 max-h-[28rem] overflow-y-auto"
      >
        {isLoading ? (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : !hasFilters ? (
          <div className="py-3 px-2 text-xs text-muted-foreground text-center">
            No saved filters yet.
            <br />
            Use &quot;Save&quot; to create one.
          </div>
        ) : (
          filters.map((filter) => (
            <DropdownMenuItem
              key={filter.id}
              className="flex items-center justify-between group cursor-pointer"
              onClick={() => handleApplyFilter(filter)}
              disabled={isDeleting}
              title={buildFilterTooltip(filter)}
            >
              <div className="flex-1 min-w-0 pr-2">
                <div className="text-sm truncate">
                  {filter.name || 'Untitled Filter'}
                </div>
                <FilterPreview filter={filter} />
              </div>
              <button
                onClick={(e) => handleDeleteFilter(e, filter.id, filter.name)}
                className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-bg rounded transition-opacity flex-shrink-0"
                title="Delete filter"
              >
                <Trash2 className="h-3.5 w-3.5 text-red-text" />
              </button>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
