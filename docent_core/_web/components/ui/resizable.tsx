'use client';

import { DragHandleDots2Icon } from '@radix-ui/react-icons';
import * as ResizablePrimitive from 'react-resizable-panels';

import { cn } from '@/lib/utils';

const ResizablePanelGroup = ({
  className,
  ...props
}: React.ComponentProps<typeof ResizablePrimitive.PanelGroup>) => (
  <ResizablePrimitive.PanelGroup
    className={cn(
      'flex h-full w-full data-[panel-group-direction=vertical]:flex-col',
      className
    )}
    {...props}
  />
);

const ResizablePanel = ResizablePrimitive.Panel;

const ResizableHandle = ({
  withHandle,
  className,
  ...props
}: React.ComponentProps<typeof ResizablePrimitive.PanelResizeHandle> & {
  withHandle?: boolean;
}) => (
  <ResizablePrimitive.PanelResizeHandle
    {...props}
    aria-label={props['aria-label'] ?? 'Resize panels'}
    className={cn(
      'group relative flex w-2.5 shrink-0 touch-none select-none items-center justify-center rounded-full bg-transparent outline-none transition-colors duration-150 hover:bg-accent/70 focus-visible:bg-accent/70 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 data-[resize-handle-active]:bg-accent data-[panel-group-direction=vertical]:h-2.5 data-[panel-group-direction=vertical]:w-full [&[data-panel-group-direction=vertical]>div]:rotate-90',
      className
    )}
  >
    <div
      aria-hidden="true"
      className={cn(
        'pointer-events-none h-8 w-px rounded-full bg-border transition-colors duration-150 group-hover:bg-muted-foreground/60 group-focus-visible:bg-muted-foreground/60',
        withHandle &&
          'z-10 flex w-2.5 items-center justify-center border border-border bg-card/95 text-muted-foreground shadow-sm'
      )}
    >
      {withHandle && <DragHandleDots2Icon className="h-2.5 w-2.5" />}
    </div>
  </ResizablePrimitive.PanelResizeHandle>
);

export { ResizablePanelGroup, ResizablePanel, ResizableHandle };
