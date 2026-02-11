'use client';

import { useState } from 'react';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useCreateFilterMutation } from '@/app/api/filterApi';
import { ComplexFilter } from '@/app/types/collectionTypes';
import { FilterListItem } from '@/app/types/filterTypes';
import { toast } from 'sonner';
import { Loader2, Save, Copy } from 'lucide-react';
import { getRtkQueryErrorMessage } from '@/lib/rtkQueryError';

interface SaveFilterPopoverProps {
  collectionId: string;
  currentFilter: ComplexFilter;
  disabled?: boolean;
  mode?: 'save' | 'save-as';
  onSaveSuccess?: (filter: FilterListItem) => void;
}

export function SaveFilterPopover({
  collectionId,
  currentFilter,
  disabled,
  mode = 'save',
  onSaveSuccess,
}: SaveFilterPopoverProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [createFilter, { isLoading }] = useCreateFilterMutation();

  const isSaveAs = mode === 'save-as';
  const label = isSaveAs ? 'Save as' : 'Save';
  const Icon = isSaveAs ? Copy : Save;

  const handleSave = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error('Please enter a name for this filter');
      return;
    }

    try {
      const result = await createFilter({
        collectionId,
        filter: currentFilter,
        name: trimmedName,
        description: description.trim() || null,
      }).unwrap();

      toast.success(`Filter "${trimmedName}" saved`);
      const filterListItem: FilterListItem = {
        id: result.id,
        name: result.name,
        description: result.description,
        filter: result.filter,
        created_at: result.created_at,
        created_by: result.created_by,
      };
      onSaveSuccess?.(filterListItem);
      handleOpenChange(false);
    } catch (err) {
      const parsed = getRtkQueryErrorMessage(err, 'Failed to save filter');
      toast.error(parsed.message);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && name.trim() && !isLoading) {
      e.preventDefault();
      handleSave();
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setName('');
      setDescription('');
    }
    setOpen(nextOpen);
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs gap-1"
          disabled={disabled}
          title={
            disabled
              ? 'Add filters to save them'
              : isSaveAs
                ? 'Save as a new filter'
                : 'Save current filters'
          }
        >
          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">{label}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-3 space-y-3">
        <p className="text-sm font-medium">
          {isSaveAs ? 'Save as New Filter' : 'Save Filter'}
        </p>
        <div className="space-y-2">
          <div>
            <Label
              htmlFor="filter-name"
              className="text-xs text-muted-foreground"
            >
              Name
            </Label>
            <Input
              id="filter-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g., High-scoring runs"
              className="text-sm mt-1 h-8"
              autoFocus
            />
          </div>
          <div>
            <Label
              htmlFor="filter-description"
              className="text-xs text-muted-foreground"
            >
              Description (optional)
            </Label>
            <Textarea
              id="filter-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what this filter captures..."
              className="text-sm resize-none mt-1"
              rows={2}
            />
          </div>
        </div>
        <Button
          size="sm"
          className="w-full h-8 text-xs"
          onClick={handleSave}
          disabled={isLoading || !name.trim()}
        >
          {isLoading ? (
            <>
              <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              Saving...
            </>
          ) : (
            label
          )}
        </Button>
      </PopoverContent>
    </Popover>
  );
}
