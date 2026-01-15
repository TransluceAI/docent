'use client';

import { X, Eye, EyeOff } from 'lucide-react';
import { cn, formatTokenCount } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';
import { SerializedContextItem } from './types';
import { getContextItemLabel, makeSyntheticCitation } from './utils';

export interface ContextItemCardProps {
  item: SerializedContextItem;
  onItemClick: (item: SerializedContextItem) => void;
  isSelected?: boolean;
  tokenEstimate?: number;
  onRemove?: () => void;
  isRemoving?: boolean;
  onToggleVisible?: () => void;
  resultSetNames?: Map<string, string | null>;
}

export function ContextItemCard({
  item,
  onItemClick,
  isSelected = false,
  tokenEstimate,
  onRemove,
  isRemoving,
  onToggleVisible,
  resultSetNames,
}: ContextItemCardProps) {
  const { badge, title, subtitle } = getContextItemLabel(item, resultSetNames);
  const isClickable = makeSyntheticCitation(item) !== undefined;

  return (
    <div className="flex items-start gap-2">
      <button
        type="button"
        className={cn(
          'flex flex-1 items-center gap-2 rounded-md border px-3 py-2 text-left transition-colors',
          isSelected
            ? 'border-indigo-border bg-indigo-muted text-primary'
            : isClickable
              ? 'border-border bg-background text-muted-foreground hover:bg-indigo-muted/40 hover:text-primary cursor-pointer'
              : 'border-border bg-background text-muted-foreground cursor-default',
          !item.visible && 'opacity-50'
        )}
        onClick={() => onItemClick(item)}
        disabled={!isClickable}
      >
        <div className="flex flex-1 flex-col">
          <div className="flex flex-row items-center gap-2">
            <span className="font-medium text-sm">{title}</span>
            <span className="rounded-full bg-indigo-muted px-2 py-0.5 text-[10px] uppercase text-indigo-text">
              {badge}
            </span>
          </div>
          {(tokenEstimate !== undefined || subtitle) && (
            <div className="mt-1 text-xs text-muted-foreground">
              {tokenEstimate !== undefined && (
                <span>{formatTokenCount(tokenEstimate)} tokens</span>
              )}
              {tokenEstimate !== undefined && subtitle && <span> | </span>}
              {subtitle && <span>{subtitle}</span>}
            </div>
          )}
        </div>
        {onToggleVisible && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleVisible();
                }}
              >
                {item.visible ? (
                  <Eye className="h-4 w-4" />
                ) : (
                  <EyeOff className="h-4 w-4" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>{item.visible ? 'Hide from context' : 'Show in context'}</p>
            </TooltipContent>
          </Tooltip>
        )}
        {onRemove && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={(e) => {
                  e.stopPropagation();
                  onRemove();
                }}
                disabled={isRemoving}
              >
                <X className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>Remove from context</p>
            </TooltipContent>
          </Tooltip>
        )}
      </button>
    </div>
  );
}
