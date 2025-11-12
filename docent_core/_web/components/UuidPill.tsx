import { useState, useEffect, useRef, useMemo } from 'react';
import { toast } from '@/hooks/use-toast';
import { copyToClipboard } from '@/lib/utils';
import { Copy } from 'lucide-react';

export default function UuidPill({ uuid }: { uuid?: string }) {
  const [isOverflowing, setIsOverflowing] = useState(false);
  const textRef = useRef<HTMLSpanElement>(null);

  const shortCode = useMemo(() => {
    if (!uuid) return '';
    const hyphenIdx = uuid.indexOf('-');
    if (hyphenIdx > 0) {
      return uuid.slice(0, hyphenIdx);
    }
    if (uuid.length > 8) {
      return `${uuid.slice(0, 8)}...`;
    }
    return uuid;
  }, [uuid]);

  useEffect(() => {
    const checkOverflow = () => {
      const el = textRef.current;
      if (!el) return;
      // Use a tiny epsilon to avoid flicker from sub-pixel rounding
      const isOver = el.scrollWidth - el.clientWidth > 1;
      setIsOverflowing(isOver);
    };

    checkOverflow();

    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(checkOverflow);
      if (textRef.current) observer.observe(textRef.current);
      return () => observer.disconnect();
    }
  }, [uuid]);

  if (!uuid) return null;

  const onClick = async () => {
    const success = await copyToClipboard(uuid);
    if (success) {
      toast({
        title: 'Copied to clipboard',
        description: 'Full UUID copied to clipboard',
        variant: 'default',
      });
    } else {
      toast({
        title: 'Failed to copy',
        description: 'Could not copy to clipboard',
        variant: 'destructive',
      });
    }
  };

  return (
    <span
      className="inline-flex h-6 min-w-0 max-w-full items-center gap-x-1 rounded-md border border-border bg-muted py-0.5 pl-1 pr-0.5 text-xs font-mono text-muted-foreground transition-colors hover:bg-accent cursor-pointer"
      onClick={onClick}
      title={`Click to copy full ID (${uuid})`}
    >
      <Copy className="h-3 w-3 flex-shrink-0" />
      <span
        ref={textRef}
        className="min-w-0 overflow-hidden whitespace-nowrap flex-1"
        style={{
          maskImage: isOverflowing
            ? 'linear-gradient(to right, black calc(100% - 24px), transparent)'
            : 'none',
          WebkitMaskImage: isOverflowing
            ? 'linear-gradient(to right, black calc(100% - 24px), transparent)'
            : 'none',
        }}
      >
        {shortCode}
      </span>
    </span>
  );
}
