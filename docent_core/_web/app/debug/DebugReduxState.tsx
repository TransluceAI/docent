'use client';

import { useSelector } from 'react-redux';
import { RootState } from '../store/store';
import { cn } from '@/lib/utils';
import { useState, useEffect } from 'react';

interface DebugReduxStateProps {
  sliceName: keyof RootState;
  className?: string;
}

const DebugReduxState: React.FC<DebugReduxStateProps> = ({
  sliceName,
  className,
}) => {
  const state = useSelector((state: RootState) => state[sliceName]);
  const [expandedObjects, setExpandedObjects] = useState<Set<string>>(() => {
    // Default behavior: expand root and first level
    const initialExpanded = new Set<string>();
    initialExpanded.add('root');
    if (typeof state === 'object' && state !== null) {
      Object.keys(state).forEach((key) => {
        initialExpanded.add(`root-${key}`);
      });
    }
    return initialExpanded;
  });

  // Load from localStorage after component mounts
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storageKey = `debug-redux-expanded-${sliceName}`;
      const stored = localStorage.getItem(storageKey);
      if (stored) {
        try {
          setExpandedObjects(new Set(JSON.parse(stored)));
        } catch (e) {
          console.warn('Failed to parse stored expanded state:', e);
        }
      }
    }
  }, [sliceName]);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Save to localStorage whenever expandedObjects changes
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storageKey = `debug-redux-expanded-${sliceName}`;
      localStorage.setItem(
        storageKey,
        JSON.stringify(Array.from(expandedObjects))
      );
    }
  }, [expandedObjects, sliceName]);

  // Helper function to copy value to clipboard
  const copyToClipboard = (value: any, key: string) => {
    const stringValue =
      typeof value === 'object'
        ? JSON.stringify(value, null, 2)
        : String(value);
    navigator.clipboard.writeText(stringValue);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  // Helper function to toggle object expansion
  const toggleExpand = (key: string) => {
    setExpandedObjects((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  // Format a value based on its type
  const formatValue = (
    value: any,
    depth = 0,
    maxDepth = 1,
    key = ''
  ): React.ReactNode => {
    if (value === null)
      return <span className="text-muted-foreground">null</span>;
    if (value === undefined)
      return <span className="text-muted-foreground">undefined</span>;

    const valueKey = `${key}-value`;
    const isCopied = copiedKey === valueKey;

    switch (typeof value) {
      case 'string':
        return (
          <span
            className={cn(
              'text-green-text cursor-pointer hover:opacity-80',
              isCopied && 'opacity-50'
            )}
            onClick={() => copyToClipboard(value, valueKey)}
          >
            {value}
            {isCopied && (
              <span className="ml-1 text-xs text-muted-foreground">
                (copied!)
              </span>
            )}
          </span>
        );
      case 'number':
        return (
          <span
            className={cn(
              'text-foreground cursor-pointer hover:opacity-80',
              isCopied && 'opacity-50'
            )}
            onClick={() => copyToClipboard(value, valueKey)}
          >
            {value}
            {isCopied && (
              <span className="ml-1 text-xs text-muted-foreground">
                (copied!)
              </span>
            )}
          </span>
        );
      case 'boolean':
        return (
          <span
            className={cn(
              'text-purple-text cursor-pointer hover:opacity-80',
              isCopied && 'opacity-50'
            )}
            onClick={() => copyToClipboard(value, valueKey)}
          >
            {value.toString()}
            {isCopied && (
              <span className="ml-1 text-xs text-muted-foreground">
                (copied!)
              </span>
            )}
          </span>
        );
      case 'function':
        return <span className="text-muted-foreground">Function</span>;
      case 'object': {
        const objectKey = key || `root-${depth}`;
        const isExpanded = expandedObjects.has(objectKey);

        if (Array.isArray(value)) {
          if (value.length === 0)
            return <span className="text-muted-foreground">[]</span>;

          return (
            <span>
              <button
                onClick={() => toggleExpand(objectKey)}
                className="mr-1 text-muted-foreground hover:text-foreground"
              >
                {isExpanded ? '  ▼' : '  ▶'}
              </button>
              {isExpanded ? (
                <>
                  [
                  {value.map((item, i) => (
                    <span key={i} className="ml-1 block">
                      {formatValue(
                        item,
                        depth + 1,
                        maxDepth,
                        `${objectKey}-${i}`
                      )}
                      {i < value.length - 1 && ','}
                    </span>
                  ))}
                  ]
                </>
              ) : (
                <span
                  className={cn(
                    'text-muted-foreground cursor-pointer hover:opacity-80',
                    isCopied && 'opacity-50'
                  )}
                  onClick={() => copyToClipboard(value, valueKey)}
                >
                  [...]
                  {isCopied && (
                    <span className="ml-1 text-xs text-muted-foreground">
                      (copied!)
                    </span>
                  )}
                </span>
              )}
            </span>
          );
        }

        // Regular object
        const entries = Object.entries(value);
        if (entries.length === 0)
          return <span className="text-muted-foreground">{'{}'}</span>;

        return (
          <span>
            <button
              onClick={() => toggleExpand(objectKey)}
              className="mr-1 text-muted-foreground hover:text-foreground"
            >
              {isExpanded ? '  ▼' : '  ▶'}
            </button>
            {isExpanded ? (
              <>
                {'{'}
                {entries.map(([k, v], i) => (
                  <span key={k} className="ml-1 block">
                    <span className="text-yellow-text">{k}</span>:{' '}
                    {formatValue(v, depth + 1, maxDepth, `${objectKey}-${k}`)}
                    {i < entries.length - 1 && ','}
                  </span>
                ))}
                {'}'}
              </>
            ) : (
              <span
                className={cn(
                  'text-muted-foreground cursor-pointer hover:opacity-80',
                  isCopied && 'opacity-50'
                )}
                onClick={() => copyToClipboard(value, valueKey)}
              >
                {'{...}'}
                {isCopied && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    (copied!)
                  </span>
                )}
              </span>
            )}
          </span>
        );
      }
      default:
        return String(value);
    }
  };

  return (
    <div
      className={cn(
        'rounded-lg border bg-card p-2 shadow-sm bg-yellow-500/10 font-mono',
        className
      )}
    >
      <h3 className="mb-2 font-semibold text-sm">Debug: {sliceName}</h3>
      <div className="space-y-1 text-xs">
        {formatValue(state, 0, 1, 'root')}
      </div>
    </div>
  );
};

export default DebugReduxState;
