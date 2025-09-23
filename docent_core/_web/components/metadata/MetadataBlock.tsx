import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';

import { BaseMetadata } from '@/app/types/transcriptTypes';
import { computeIntervalsForJsonPattern } from '@/lib/citationMatch';
import { SegmentedText } from '@/lib/SegmentedText';

export const formatMetadataValue = (value: any): string => {
  if (value === null || value === undefined) return 'N/A';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
};

const copyToClipboard = async (text: string): Promise<boolean> => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
};

const CopyButton: React.FC<{ value: any }> = ({ value }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const textToCopy = formatMetadataValue(value);
    const success = await copyToClipboard(textToCopy);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="ml-2 p-1 rounded hover:bg-muted transition-colors"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="h-3 w-3 text-green-text" />
      ) : (
        <Copy className="h-3 w-3 text-muted-foreground hover:text-primary" />
      )}
    </button>
  );
};

export function MetadataBlock({
  metadata,
  citedKey,
  citedTextRange,
}: {
  metadata: BaseMetadata;
  citedKey?: string;
  citedTextRange?: string;
}) {
  const shouldHighlightRow = (key: string) => {
    return citedKey ? key === citedKey : false;
  };

  const getHighlightedValue = (value: any, shouldHighlight: boolean) => {
    const formattedValue = formatMetadataValue(value);
    if (!shouldHighlight || !citedTextRange) {
      return <span>{formattedValue}</span>;
    }
    const intervals = computeIntervalsForJsonPattern(
      formattedValue,
      citedTextRange
    );
    return <SegmentedText text={formattedValue} intervals={intervals} />;
  };

  return (
    <div className="bg-secondary rounded-lg border border-border overflow-hidden">
      <div className="divide-y divide-border">
        {Object.entries(metadata).map(([key, value]) => {
          const isHighlightedRow = shouldHighlightRow(key);
          const rowClass = isHighlightedRow
            ? 'flex items-center p-2 bg-yellow-100 dark:bg-yellow-900/30 transition-colors'
            : 'flex items-center p-2 hover:bg-muted transition-colors';
          return (
            <div
              key={key}
              className={rowClass}
              data-highlighted={isHighlightedRow ? 'true' : undefined}
            >
              <div className="w-1/3 font-medium text-sm text-primary break-words pr-4">
                {key}
              </div>
              <div className="w-2/3 text-sm text-muted-foreground break-words whitespace-pre-wrap font-mono text-xs flex items-center justify-between">
                <span className="flex-1">
                  {getHighlightedValue(value, isHighlightedRow)}
                </span>
                <CopyButton value={value} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
