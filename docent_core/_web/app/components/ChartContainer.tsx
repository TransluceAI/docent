import { cn } from '@/lib/utils';
import React from 'react';

interface ChartContainerProps {
  children: React.ReactNode;
  /** Minimum height in pixels for the inner chart area. If undefined, no min-height is applied */
  minHeight?: number;
  /** Enable horizontal scrolling – primarily for wide tables */
  xScroll?: boolean;
  /** Additional class names for the outer container */
  className?: string;
}

/**
 * This component does two main things:
 * 1. Applies scrolling when content exceeds available space
 * 2. Optionally gives charts a minimum height (needed for ResponsiveBar and ResponsiveLine which can shrink arbitrarily)
 *
 * @param minHeight - When provided, the container becomes flex-1 and enforces a minimum height.
 *                   When undefined, the container shrinks to content size (used for tables).
 * @param xScroll - Enables horizontal scrolling with custom scrollbar styling (for wide tables).
 * @param className - Additional CSS classes for the outer container.
 */
export default function ChartContainer({
  children,
  minHeight,
  xScroll = false,
  className = '',
}: ChartContainerProps) {
  return (
    <div
      className={cn(
        minHeight !== undefined ? 'flex-1 overflow-y-auto' : 'overflow-y-auto',
        xScroll && 'overflow-x-auto custom-scrollbar',
        className
      )}
    >
      <div
        className={cn('w-full', minHeight !== undefined && 'h-full')}
        style={minHeight !== undefined ? { minHeight } : undefined}
      >
        {children}
      </div>
    </div>
  );
}
