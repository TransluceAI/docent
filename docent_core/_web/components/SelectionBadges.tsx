'use client';

import React from 'react';
import { Badge } from './ui/badge';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { TextSelectionItem } from '@/providers/use-text-selection';
import { toast } from '@/hooks/use-toast';

interface SelectionBadgesProps {
  selections: TextSelectionItem[];
  onRemove: (index: number) => void;
  onNavigate?: (item: TextSelectionItem) => void;
  className?: string;
}

export default function SelectionBadges({
  selections,
  onRemove,
  onNavigate,
  className,
}: SelectionBadgesProps) {
  if (!selections || selections.length === 0) return null;

  return (
    <div className={cn('flex flex-wrap gap-2 items-center', className)}>
      {selections.map((item, idx) => {
        const { text, transcriptIdx, blockIdx } = item;
        const meta =
          transcriptIdx != null && blockIdx != null
            ? `T${transcriptIdx}·B${blockIdx}`
            : undefined;
        return (
          <Badge
            key={idx}
            variant="secondary"
            className={cn(
              'group h-6 pl-1.5 pr-1 bg-background border shadow-sm inline-flex items-center gap-1',
              onNavigate ? 'cursor-pointer hover:bg-muted/70' : ''
            )}
            onClick={(e) => {
              if (!onNavigate) return;
              // avoid clicking the X
              const target = e.target as HTMLElement;
              if (target.closest('button')) return;
              e.preventDefault();
              onNavigate(item);
            }}
            title={meta ? `${meta} • ${text}` : text}
          >
            {meta && (
              <span className="text-[10px] text-muted-foreground mr-1">
                {meta}
              </span>
            )}
            <span className="max-w-24 truncate inline-block align-middle text-xs font-normal">
              {text}
            </span>
            <button
              type="button"
              aria-label="Remove selection"
              className="rounded p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                // Clear any active selection to avoid re-adding via mouseup listeners elsewhere
                try {
                  window.getSelection()?.removeAllRanges();
                } catch {
                  toast({
                    title: 'Error',
                    description: 'Failed to remove selection',
                    variant: 'destructive',
                  });
                }
                onRemove(idx);
              }}
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </Badge>
        );
      })}
    </div>
  );
}
