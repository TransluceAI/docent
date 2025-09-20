'use client';

import { Button } from '@/components/ui/button';
import { RotateCcw } from 'lucide-react';

interface ChatHeaderProps {
  title?: string;
  description?: string;
  onReset?: () => void;
  canReset?: boolean;
  children?: React.ReactNode;
}

export function ChatHeader({
  title = 'Chat',
  description = 'Ask questions about the transcript',
  onReset,
  canReset = true,
  children,
}: ChatHeaderProps) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex flex-col gap-1">
        <h4 className="font-semibold text-sm">{title}</h4>
        {description && (
          <span className="text-xs text-muted-foreground">{description}</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {children}
        {onReset && (
          <Button
            variant="outline"
            size="sm"
            onClick={onReset}
            disabled={!canReset}
            className="h-7 w-7 p-1.5 text-xs"
            title="Clear chat history"
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
