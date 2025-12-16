import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Copy, Check, MessageSquarePlus } from 'lucide-react';

import { BaseMetadata } from '@/app/types/transcriptTypes';
import { CitationTargetTextRange } from '@/app/types/citationTypes';
import { computeIntervalsForJsonPattern } from '@/lib/citationMatch';
import { SegmentedText } from '@/lib/SegmentedText';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useDebounce } from '@/hooks/use-debounce';

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

type SearchType = 'fuzzy' | 'exact' | 'regex';

const findSubstringMatches = (
  text: string,
  query: string,
  caseInsensitive: boolean
) => {
  if (!query) return [];
  const haystack = caseInsensitive ? text.toLowerCase() : text;
  const needle = caseInsensitive ? query.toLowerCase() : query;
  const matches: { start: number; end: number }[] = [];
  let start = haystack.indexOf(needle);
  while (start !== -1) {
    matches.push({ start, end: start + needle.length });
    start = haystack.indexOf(needle, start + needle.length || start + 1);
  }
  return matches;
};

const findSubsequenceMatches = (
  text: string,
  query: string,
  caseInsensitive: boolean
) => {
  if (!query) return [];
  const haystack = caseInsensitive ? text.toLowerCase() : text;
  const needle = caseInsensitive ? query.toLowerCase() : query;
  const intervals: { start: number; end: number }[] = [];

  let searchFrom = 0;
  for (const ch of needle) {
    const idx = haystack.indexOf(ch, searchFrom);
    if (idx === -1) {
      return [];
    }
    intervals.push({ start: idx, end: idx + 1 });
    searchFrom = idx + 1;
  }

  return intervals;
};

const findRegexMatches = (text: string, regex: RegExp) => {
  const matches: { start: number; end: number }[] = [];
  const globalRegex = new RegExp(
    regex.source,
    regex.flags.includes('g') ? regex.flags : `${regex.flags}g`
  );
  let m: RegExpExecArray | null;
  while ((m = globalRegex.exec(text)) !== null) {
    if (m[0].length === 0) {
      globalRegex.lastIndex++;
      continue;
    }
    matches.push({ start: m.index, end: m.index + m[0].length });
    if (matches.length >= 200) break;
  }
  return matches;
};

export function MetadataBlock({
  metadata,
  citedKey,
  textRange,
  showSearchControls = false,
  onAddComment,
}: {
  metadata: BaseMetadata;
  citedKey?: string;
  textRange?: CitationTargetTextRange;
  showSearchControls?: boolean;
  onAddComment?: (key: string) => void;
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchType, setSearchType] = useState<SearchType>('exact');

  // Debounce search query to avoid overwhelming CPU with expensive operations
  const debouncedSearchQuery = useDebounce(searchQuery, 100);
  const trimmedQuery = debouncedSearchQuery.trim();

  const { activeRegex, regexError } = useMemo(() => {
    if (searchType !== 'regex' || !trimmedQuery) {
      return {
        activeRegex: null as RegExp | null,
        regexError: null as string | null,
      };
    }
    try {
      return {
        activeRegex: new RegExp(trimmedQuery, 'gi'),
        regexError: null,
      };
    } catch (error) {
      return {
        activeRegex: null,
        regexError:
          error instanceof Error ? error.message : 'Invalid regular expression',
      };
    }
  }, [searchType, trimmedQuery]);

  const getSearchIntervals = (text: string) => {
    if (!trimmedQuery) return [];
    if (searchType === 'regex') {
      if (!activeRegex) return [];
      return findRegexMatches(text, activeRegex).map((m) => ({
        start: m.start,
        end: m.end,
        citationId: 'search',
      }));
    }
    if (searchType === 'fuzzy') {
      const matches = findSubsequenceMatches(text, trimmedQuery, true);
      return matches.map((m) => ({
        start: m.start,
        end: m.end,
        citationId: 'search',
      }));
    }
    const matches = findSubstringMatches(text, trimmedQuery, false);
    return matches.map((m) => ({
      start: m.start,
      end: m.end,
      citationId: 'search',
    }));
  };

  const entryMatchesQuery = (key: string, valueText: string) => {
    if (!trimmedQuery) {
      return true;
    }
    if (searchType === 'regex') {
      if (!activeRegex) return false;
      const matcher = new RegExp(activeRegex.source, activeRegex.flags);
      return matcher.test(key) || matcher.test(valueText);
    }
    if (searchType === 'fuzzy') {
      return (
        findSubsequenceMatches(key, trimmedQuery, true).length > 0 ||
        findSubsequenceMatches(valueText, trimmedQuery, true).length > 0
      );
    }
    // exact
    return key.includes(trimmedQuery) || valueText.includes(trimmedQuery);
  };

  const entries = useMemo(() => Object.entries(metadata), [metadata]);

  const filteredEntries = useMemo(
    () =>
      entries
        .map(([key, value]) => {
          const valueText = formatMetadataValue(value);
          if (!entryMatchesQuery(key, valueText)) {
            return null;
          }
          const keyIntervals = getSearchIntervals(key);
          const searchIntervals = getSearchIntervals(valueText);

          const citationIntervals =
            citedKey === key && textRange?.start_pattern
              ? computeIntervalsForJsonPattern(
                  valueText,
                  textRange.start_pattern
                )
              : [];

          return {
            key,
            value,
            valueText,
            keyIntervals,
            valueIntervals: [...citationIntervals, ...searchIntervals],
          };
        })
        .filter(
          (
            entry
          ): entry is {
            key: string;
            value: any;
            valueText: string;
            keyIntervals: { start: number; end: number; citationId: string }[];
            valueIntervals: {
              start: number;
              end: number;
              citationId: string;
            }[];
          } => Boolean(entry)
        ),
    [entries, entryMatchesQuery, getSearchIntervals, citedKey, textRange]
  );

  const shouldHighlightRow = (key: string) => {
    return citedKey ? key === citedKey : false;
  };

  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const previousMetadataRef = useRef<BaseMetadata | null>(null);

  const focusSearchInput = useCallback(() => {
    const node = searchInputRef.current;
    if (!node) return;
    requestAnimationFrame(() => {
      node.focus({ preventScroll: true });
    });
  }, []);

  useEffect(() => {
    focusSearchInput();
  }, [focusSearchInput]);

  useEffect(() => {
    if (metadata === previousMetadataRef.current) {
      return;
    }
    previousMetadataRef.current = metadata;
    focusSearchInput();
  }, [metadata, focusSearchInput]);

  return (
    <div className="space-y-3 metadata">
      {showSearchControls ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search metadata..."
            className="h-7 text-xs bg-background flex-1 min-w-[180px] max-w-sm hover:bg-secondary hover:text-primary focus-visible:ring-0 focus-visible:border-ring"
            aria-invalid={regexError ? true : undefined}
            ref={searchInputRef}
          />
          <Select
            value={searchType}
            onValueChange={(v) => setSearchType(v as SearchType)}
          >
            <SelectTrigger className="h-7 w-[120px] text-xs bg-background flex-shrink-0 hover:bg-secondary hover:text-primary focus:ring-0 focus-visible:ring-0 focus-visible:border-ring focus-visible:shadow-[0_0_0_1px_hsl(var(--ring))]">
              <SelectValue placeholder="Fuzzy" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="exact" className="text-xs">
                Exact
              </SelectItem>
              <SelectItem value="fuzzy" className="text-xs">
                Fuzzy
              </SelectItem>
              <SelectItem value="regex" className="text-xs">
                Regex
              </SelectItem>
            </SelectContent>
          </Select>
          {regexError && (
            <span className="text-xs text-destructive font-mono">
              {regexError}
            </span>
          )}
        </div>
      ) : null}

      <div className="bg-secondary rounded-lg border border-border overflow-hidden">
        {filteredEntries.length === 0 ? (
          <div className="text-center py-6 text-xs text-muted-foreground">
            {trimmedQuery
              ? 'No metadata matches this search.'
              : 'No metadata available.'}
          </div>
        ) : (
          <div className="divide-y divide-border">
            {filteredEntries.map(
              ({ key, value, valueText, keyIntervals, valueIntervals }) => {
                const isHighlightedRow = shouldHighlightRow(key);
                const rowClass = isHighlightedRow
                  ? 'group flex items-center p-2 bg-yellow-100 dark:bg-yellow-900/30 transition-colors'
                  : 'group flex items-center p-2 hover:bg-muted transition-colors';
                return (
                  <div
                    key={key}
                    className={rowClass}
                    data-highlighted={isHighlightedRow ? 'true' : undefined}
                  >
                    <div className="w-1/3 min-w-0 font-medium text-sm text-primary break-all pr-4 flex items-center gap-2">
                      {keyIntervals.length > 0 ? (
                        <SegmentedText text={key} intervals={keyIntervals} />
                      ) : (
                        key
                      )}
                    </div>
                    <div className="w-2/3 min-w-0 text-sm text-muted-foreground break-all whitespace-pre-wrap font-mono text-xs flex items-center justify-between">
                      <span className="flex-1">
                        {valueIntervals.length > 0 ? (
                          <SegmentedText
                            text={valueText}
                            intervals={valueIntervals}
                          />
                        ) : (
                          valueText
                        )}
                      </span>
                      {onAddComment && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onAddComment(key);
                          }}
                          className="p-1 rounded text-muted-foreground hover:text-primary transition-colors opacity-0 group-hover:opacity-100"
                          title="Add comment to metadata field"
                        >
                          <MessageSquarePlus className="h-3 w-3" />
                        </button>
                      )}
                      <CopyButton value={value} />
                    </div>
                  </div>
                );
              }
            )}
          </div>
        )}
      </div>
    </div>
  );
}
