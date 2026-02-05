import React, {
  useRef,
  useEffect,
  useImperativeHandle,
  forwardRef,
} from 'react';
import { ChevronUp, ChevronDown, X } from 'lucide-react';
import { cn } from '@/lib/utils';

interface TranscriptSearchBarProps {
  isOpen: boolean;
  onClose: () => void;
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  currentMatchIndex: number;
  totalMatches: number;
  onNavigateNext: () => void;
  onNavigatePrev: () => void;
  caseSensitive: boolean;
  onCaseSensitiveChange: (value: boolean) => void;
}

export interface TranscriptSearchBarHandle {
  focus: () => void;
}

export const TranscriptSearchBar = forwardRef<
  TranscriptSearchBarHandle,
  TranscriptSearchBarProps
>(function TranscriptSearchBar(
  {
    isOpen,
    onClose,
    searchQuery,
    onSearchQueryChange,
    currentMatchIndex,
    totalMatches,
    onNavigateNext,
    onNavigatePrev,
    caseSensitive,
    onCaseSensitiveChange,
  },
  ref
) {
  const inputRef = useRef<HTMLInputElement>(null);

  useImperativeHandle(ref, () => ({
    focus: () => {
      if (inputRef.current) {
        inputRef.current.focus();
        inputRef.current.select();
      }
    },
  }));

  // Auto-focus input when opened
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isOpen]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (e.shiftKey) {
        onNavigatePrev();
      } else {
        onNavigateNext();
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  if (!isOpen) return null;

  const matchCountText =
    totalMatches === 0
      ? searchQuery.length > 0
        ? 'No matches'
        : ''
      : `${currentMatchIndex + 1} of ${totalMatches}`;

  return (
    <div className="absolute top-2 right-2 z-20 flex items-center gap-0.5 bg-background border border-border rounded shadow-lg p-1">
      <input
        ref={inputRef}
        type="text"
        value={searchQuery}
        onChange={(e) => onSearchQueryChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Find..."
        className="w-36 px-1.5 py-0.5 text-xs bg-transparent border-none outline-none placeholder:text-muted-foreground"
      />

      {/* Match counter */}
      <span className="text-[10px] text-muted-foreground min-w-[50px] text-center">
        {matchCountText}
      </span>

      {/* Case sensitivity toggle */}
      <button
        onClick={() => onCaseSensitiveChange(!caseSensitive)}
        className={cn(
          'px-1 py-0.5 rounded text-[10px] font-medium transition-colors',
          caseSensitive
            ? 'bg-primary text-primary-foreground'
            : 'text-muted-foreground hover:text-primary hover:bg-muted'
        )}
        title="Case sensitive"
      >
        Aa
      </button>

      {/* Previous match */}
      <button
        onClick={onNavigatePrev}
        disabled={totalMatches === 0}
        className={cn(
          'p-0.5 rounded transition-colors',
          totalMatches === 0
            ? 'text-muted-foreground/50 cursor-not-allowed'
            : 'text-muted-foreground hover:text-primary hover:bg-muted'
        )}
        title="Previous match (Shift+Enter)"
      >
        <ChevronUp className="h-3.5 w-3.5" />
      </button>

      {/* Next match */}
      <button
        onClick={onNavigateNext}
        disabled={totalMatches === 0}
        className={cn(
          'p-0.5 rounded transition-colors',
          totalMatches === 0
            ? 'text-muted-foreground/50 cursor-not-allowed'
            : 'text-muted-foreground hover:text-primary hover:bg-muted'
        )}
        title="Next match (Enter)"
      >
        <ChevronDown className="h-3.5 w-3.5" />
      </button>

      {/* Close button */}
      <button
        onClick={onClose}
        className="p-0.5 rounded text-muted-foreground hover:text-primary hover:bg-muted transition-colors"
        title="Close (Escape)"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
});
