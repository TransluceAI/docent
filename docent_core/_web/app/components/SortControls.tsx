'use client';

import React from 'react';
import { useSelector } from 'react-redux';
import { RootState } from '../store/store';
import { useGetAgentRunSortableFieldsQuery } from '../api/collectionApi';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

interface SortControlsProps {
  sortField: string | null;
  sortDirection: 'asc' | 'desc';
  onSortChange: (field: string | null, direction: 'asc' | 'desc') => void;
}

export const SortControls = ({
  sortField,
  sortDirection,
  onSortChange,
}: SortControlsProps) => {
  const collectionId = useSelector(
    (state: RootState) => state.collection.collectionId
  );

  const { data: sortableFieldsData } = useGetAgentRunSortableFieldsQuery(
    collectionId!,
    {
      skip: !collectionId,
    }
  );

  const sortableFields = sortableFieldsData?.fields || [];

  // Always show "No sorting" option, even when data is loading
  const allOptions = [
    { name: 'none', displayName: 'No sorting' },
    ...sortableFields.map((field) => ({
      name: field.name,
      displayName: field.name,
    })),
  ];

  const handleFieldChange = (field: string) => {
    if (field === 'none') {
      onSortChange(null, 'asc');
    } else {
      onSortChange(field, sortDirection);
    }
  };

  const handleDirectionChange = () => {
    if (sortField) {
      onSortChange(sortField, sortDirection === 'asc' ? 'desc' : 'asc');
    }
  };

  return (
    <div className="flex items-center justify-end gap-1.5">
      <ArrowUpDown className="h-4 w-4 text-muted-foreground" />
      <Select value={sortField || 'none'} onValueChange={handleFieldChange}>
        <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground w-48">
          <SelectValue placeholder="Select field" />
        </SelectTrigger>
        <SelectContent>
          {allOptions.map((option) => (
            <SelectItem
              key={option.name}
              value={option.name}
              className="font-mono text-muted-foreground text-xs"
            >
              {option.displayName || option.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {sortField && (
        <Button
          variant="outline"
          size="sm"
          onClick={handleDirectionChange}
          className="h-7 text-xs bg-background font-mono text-muted-foreground border-border hover:bg-muted-foreground/10 flex items-center gap-1 px-2 w-16"
        >
          {sortDirection === 'asc' ? 'asc' : 'desc'}
          {sortDirection === 'asc' ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )}
        </Button>
      )}
    </div>
  );
};
