'use client';

import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useCreateFilterMutation } from '@/app/api/filterApi';
import { ComplexFilter } from '@/app/types/collectionTypes';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { getRtkQueryErrorMessage } from '@/lib/rtkQueryError';

interface SaveFilterDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  collectionId: string;
  currentFilter: ComplexFilter;
  onSaveSuccess?: (filterId: string) => void;
}

export function SaveFilterDialog({
  open,
  onOpenChange,
  collectionId,
  currentFilter,
  onSaveSuccess,
}: SaveFilterDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [createFilter, { isLoading }] = useCreateFilterMutation();

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

      toast.success('Filter saved');
      onSaveSuccess?.(result.id);
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
    onOpenChange(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>Save Filter</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
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
              className="text-sm mt-1"
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
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={isLoading || !name.trim()}>
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Saving...
              </>
            ) : (
              'Save'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
