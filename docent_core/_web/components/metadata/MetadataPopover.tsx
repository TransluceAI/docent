import * as React from 'react';
import { FileText } from 'lucide-react';

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { BaseMetadata } from '@/app/types/transcriptTypes';

function isEmptyObject(obj: Record<string, any>) {
  return !obj || Object.keys(obj).length === 0;
}

type RootProps = {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
};

function Root({ open, onOpenChange, children }: RootProps) {
  const isControlled = typeof open !== 'undefined';
  const [internalOpen, setInternalOpen] = React.useState(false);
  const effectiveOpen = isControlled ? !!open : internalOpen;

  const handleOpenChange = (next: boolean) => {
    if (!isControlled) setInternalOpen(next);
    onOpenChange?.(next);
  };

  return (
    <Popover open={effectiveOpen} onOpenChange={handleOpenChange}>
      {children}
    </Popover>
  );
}

function Trigger({ children }: { children: React.ReactNode }) {
  return <PopoverTrigger asChild>{children}</PopoverTrigger>;
}

function DefaultTrigger({
  className,
  disabled,
}: {
  className?: string;
  disabled?: boolean;
}) {
  const classes = cn(
    'text-xs flex items-center gap-1 h-6 px-1 py-0.5 shadow-none',
    'data-[state=open]:bg-indigo-bg data-[state=open]:border-indigo-border data-[state=open]:text-primary',
    className
  );
  return (
    <PopoverTrigger asChild>
      <Button
        size="sm"
        variant="outline"
        className={classes}
        disabled={disabled}
      >
        <FileText className="h-3 w-3" />
        <span>Metadata</span>
      </Button>
    </PopoverTrigger>
  );
}

type ContentProps = {
  children: React.ReactNode;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  title?: string;
  titleRight?: React.ReactNode;
};

function Content({
  children,
  side = 'right',
  align = 'start',
  title,
  titleRight,
}: ContentProps) {
  const scrollContainerRef = React.useRef<HTMLDivElement>(null);

  const scrollToHighlight = React.useCallback(() => {
    const containerEl = scrollContainerRef.current;
    if (!containerEl) return;
    // Prefer any highlighted spans first
    const highlightedSpans = containerEl.querySelectorAll(
      '[data-citation-ids]'
    );
    if (highlightedSpans.length > 0) {
      (highlightedSpans[0] as HTMLElement).scrollIntoView({
        behavior: 'instant',
        block: 'start',
      });
      return;
    }
    // Fallback: highlighted row marker
    const highlightedRow = containerEl.querySelector(
      '[data-highlighted="true"]'
    ) as HTMLElement | null;
    if (highlightedRow) {
      highlightedRow.scrollIntoView({ behavior: 'instant', block: 'start' });
    }
  }, []);

  // Auto-scroll when the popover opens
  return (
    <PopoverContent
      side={side}
      align={align}
      className="w-[520px] max-w-[85vw] p-3"
      onOpenAutoFocus={() => {
        // Ensure layout is settled before scrolling
        requestAnimationFrame(scrollToHighlight);
      }}
    >
      {title && (
        <div className="flex items-center gap-2 mb-2">
          <div className="flex items-center space-x-2">
            <div className="text-sm font-medium text-primary">{title}</div>
          </div>
          {titleRight ? (
            <div className="flex items-center">{titleRight}</div>
          ) : null}
        </div>
      )}
      <div
        ref={scrollContainerRef}
        className="max-h-[60vh] overflow-auto custom-scrollbar"
      >
        {children}
      </div>
    </PopoverContent>
  );
}

type BodyProps = {
  metadata: BaseMetadata;
  emptyText?: string;
  children: (metadata: BaseMetadata) => React.ReactNode;
};

function Body({
  metadata,
  emptyText = 'No metadata available',
  children,
}: BodyProps) {
  if (isEmptyObject(metadata)) {
    return (
      <div className="text-center py-8 text-muted-foreground text-xs">
        {emptyText}
      </div>
    );
  }
  return <div className="space-y-3">{children(metadata)}</div>;
}

export const MetadataPopover = {
  Root,
  Trigger,
  DefaultTrigger,
  Content,
  Body,
};
