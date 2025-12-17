import { useState, useEffect, useRef, useMemo } from 'react';
import { toast } from 'sonner';
import { copyToClipboard } from '@/lib/utils';
import { Copy } from 'lucide-react';

export default function UuidPill({
  uuid,
  stopPropagation = false,
}: {
  uuid?: string;
  stopPropagation?: boolean;
}) {
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

  const onClick = async (e: React.MouseEvent) => {
    if (stopPropagation) {
      e.stopPropagation();
    }
    const success = await copyToClipboard(uuid);
    if (success) {
      toast.success('Full UUID copied to clipboard');
    } else {
      toast.error('Could not copy to clipboard');
    }
  };

  return (
    <span
      className="inline-flex h-6 min-w-0 max-w-full items-center gap-x-1 rounded-md border border-border bg-muted py-0.5 pl-1 pr-0.5 text-xs font-mono text-foreground/70 transition-colors hover:bg-primary/5 cursor-pointer"
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
