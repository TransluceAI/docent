'use client';

import React, { forwardRef, useContext } from 'react';
import { X } from 'lucide-react';
import { motion } from 'framer-motion';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { SlidingPanelContext } from './SlidingPanelContext';

const PANEL_PEEK_WIDTH = 40; // Width of panel peek when stacked

interface SlidingPanelProps {
  id: string;
  title: string;
  renderHeader?: (api: {
    closeButton: React.ReactNode;
    title: string;
    isRoot: boolean;
  }) => React.ReactNode;
  isRoot?: boolean;
  isAlone?: boolean;
  index?: number; // Panel index for sticky positioning (0-based)
  onClose?: () => void;
  children: React.ReactNode;
  className?: string;
}

export const SlidingPanel = forwardRef<HTMLDivElement, SlidingPanelProps>(
  function SlidingPanel(
    {
      id,
      title,
      renderHeader,
      isRoot = false,
      isAlone = false,
      index = 0,
      onClose,
      children,
      className,
    },
    ref
  ) {
    const context = useContext(SlidingPanelContext);

    const handleClose = () => {
      if (onClose) {
        onClose();
      } else if (context) {
        context.closePanel(id);
      }
    };

    // Calculate sticky left offset based on panel index
    // Each panel sticks slightly further from the left to show peeks of previous panels
    const stickyLeft = index * PANEL_PEEK_WIDTH;

    const closeButton = !isRoot ? (
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0"
        onClick={(e) => {
          e.stopPropagation();
          handleClose();
        }}
      >
        <X className="h-4 w-4" />
      </Button>
    ) : null;

    return (
      <motion.div
        ref={ref}
        layout="position"
        transition={{ duration: 0.2, ease: 'easeOut' }}
        className={cn(
          'flex-shrink-0 h-full',
          isAlone ? 'w-full' : 'w-1/2 min-w-[400px]',
          'bg-card',
          !isRoot && 'border-l border-border',
          'flex flex-col overflow-hidden',
          'sticky', // Enable sticky positioning for layering effect
          !isAlone && 'shadow-[-4px_0_12px_-4px_rgba(0,0,0,0.15)]', // Shadow for depth
          className
        )}
        style={{
          left: stickyLeft,
          zIndex: index + 1, // Higher index panels stack on top
        }}
        data-panel-id={id}
      >
        {/* Panel Header */}
        {!isRoot && (
          <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-secondary/30">
            {renderHeader ? (
              renderHeader({ closeButton, title, isRoot })
            ) : (
              <>
                {closeButton}
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <h2 className="text-sm font-medium truncate min-w-0">
                    {title}
                  </h2>
                </div>
              </>
            )}
          </div>
        )}

        {/* Panel Content */}
        <div className="flex-1 overflow-auto min-h-0">{children}</div>
      </motion.div>
    );
  }
);
