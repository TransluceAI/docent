import React, { useEffect, useMemo, useState } from 'react';
import { BASE_URL } from '@/app/constants';
import { SegmentedText } from '@/lib/SegmentedText';
import { Check, ChevronDown, ChevronUp, Clock, Copy, Cpu } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { useDebounce } from '@/hooks/use-debounce';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

type OtelSearchType = 'fuzzy' | 'exact' | 'regex';

type SpanEvent = {
  name?: string;
  timestamp?: string;
  attributes?: Record<string, unknown>;
};

type SpanLink = {
  trace_id?: string;
  span_id?: string;
  attributes?: Record<string, unknown>;
};

type SpanPayload = {
  trace_id?: string;
  span_id?: string;
  parent_span_id?: string;
  operation_name?: string;
  start_time?: string;
  end_time?: string;
  duration_ms?: number;
  kind?: number;
  status?: { code?: string | number; message?: string };
  scope?: { name?: string; version?: string };
  attributes?: Record<string, unknown>;
  resource_attributes?: Record<string, unknown>;
  events?: SpanEvent[];
  links?: SpanLink[];
} & Record<string, unknown>;

type MessageTelemetryResponse = {
  telemetry_accumulation_id: string;
  telemetry_log_id?: string | null;
  raw_span_id?: string | null;
  first_seen_span_start_time?: string | null;
  span: SpanPayload;
};

type Props = {
  collectionId: string;
  transcriptId: string;
  messageId: string;
};

const formatLocalDateTime = (iso: string | undefined): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
};

const formatTelemetryValue = (value: unknown): string => {
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

const recordToEntries = (record: Record<string, unknown> | undefined) => {
  if (!record) return [];
  return Object.entries(record)
    .map(([key, value]) => ({ key, value }))
    .sort((a, b) => a.key.localeCompare(b.key));
};

const spanTopLevelEntries = (span: Record<string, unknown>) => {
  const excluded = new Set([
    'attributes',
    'resource_attributes',
    'events',
    'links',
  ]);
  const entries: Array<{ key: string; value: unknown }> = [];
  for (const [key, value] of Object.entries(span)) {
    if (excluded.has(key)) continue;
    entries.push({ key, value });
  }
  return entries.sort((a, b) => a.key.localeCompare(b.key));
};

export function MessageTelemetryDialog({
  collectionId,
  transcriptId,
  messageId,
}: Props) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [payload, setPayload] = useState<MessageTelemetryResponse | null>(null);
  const [activeTab, setActiveTab] = useState<
    'details' | 'events' | 'links' | 'raw'
  >('details');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchType, setSearchType] = useState<OtelSearchType>('exact');
  const [eventOpen, setEventOpen] = useState<Record<number, boolean>>({});
  const [detailsOpen, setDetailsOpen] = useState<{
    spanAttributes: boolean;
    resourceAttributes: boolean;
    topLevel: boolean;
  }>({ spanAttributes: true, resourceAttributes: true, topLevel: true });
  const [rawCopied, setRawCopied] = useState(false);

  const debouncedSearchQuery = useDebounce(searchQuery, 100);
  const trimmedQuery = debouncedSearchQuery.trim();

  const rawJsonText = useMemo(() => {
    if (!payload) return '';
    return JSON.stringify(payload, null, 2);
  }, [payload]);

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
    } catch (err) {
      return {
        activeRegex: null,
        regexError:
          err instanceof Error ? err.message : 'Invalid regular expression',
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
    if (!trimmedQuery) return true;
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
    return key.includes(trimmedQuery) || valueText.includes(trimmedQuery);
  };

  const fetchTelemetry = async () => {
    setOpen(true);
    setLoading(true);
    setError(null);
    setPayload(null);
    setActiveTab('details');
    setSearchQuery('');
    setSearchType('exact');
    setEventOpen({});
    setDetailsOpen({
      spanAttributes: true,
      resourceAttributes: true,
      topLevel: true,
    });
    setRawCopied(false);

    try {
      const res = await fetch(
        `${BASE_URL}/rest/telemetry/${collectionId}/transcripts/${transcriptId}/messages/${messageId}/otel`,
        { method: 'GET', credentials: 'include' }
      );
      if (!res.ok) {
        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          const body = (await res.json()) as { detail?: unknown };
          throw new Error(
            typeof body?.detail === 'string'
              ? body.detail
              : `Request failed (${res.status})`
          );
        }
        const text = await res.text();
        throw new Error(text || `Request failed (${res.status})`);
      }
      const json = (await res.json()) as MessageTelemetryResponse;
      setPayload(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!payload) return;
    const events = payload.span.events ?? [];
    const initial: Record<number, boolean> = {};
    for (let i = 0; i < events.length; i++) {
      initial[i] = true;
    }
    setEventOpen(initial);
  }, [payload?.telemetry_accumulation_id]);

  const CopyValueButton = ({ valueText }: { valueText: string }) => {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
      const success = await copyToClipboard(valueText);
      if (!success) return;
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    };

    return (
      <button
        onClick={(e) => {
          e.stopPropagation();
          void handleCopy();
        }}
        className="ml-2 p-1 rounded hover:bg-muted transition-colors opacity-0 group-hover:opacity-100"
        title="Copy value"
      >
        {copied ? (
          <Check className="h-3 w-3 text-green-text" />
        ) : (
          <Copy className="h-3 w-3 text-muted-foreground hover:text-primary" />
        )}
      </button>
    );
  };

  const KeyValueTable = ({
    title,
    entries,
  }: {
    title?: string;
    entries: Array<{ key: string; value: unknown }>;
  }) => {
    const filtered = entries
      .map((e) => {
        const valueText = formatTelemetryValue(e.value);
        if (!entryMatchesQuery(e.key, valueText)) return null;
        return {
          key: e.key,
          valueText,
          keyIntervals: getSearchIntervals(e.key),
          valueIntervals: getSearchIntervals(valueText),
        };
      })
      .filter(
        (
          entry
        ): entry is {
          key: string;
          valueText: string;
          keyIntervals: { start: number; end: number; citationId: string }[];
          valueIntervals: { start: number; end: number; citationId: string }[];
        } => Boolean(entry)
      );

    if (filtered.length === 0) {
      return (
        <div className="text-xs text-muted-foreground">
          {title ? `${title}: ` : ''}
          No matching entries.
        </div>
      );
    }
    return (
      <div className="space-y-2">
        {title ? (
          <div className="text-xs font-medium text-muted-foreground">
            {title}
          </div>
        ) : null}
        <div className="rounded-md border border-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-64">Key</TableHead>
                <TableHead>Value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((e) => (
                <TableRow key={e.key} className="group">
                  <TableCell className="align-top font-mono text-xs break-all">
                    {e.keyIntervals.length > 0 ? (
                      <SegmentedText text={e.key} intervals={e.keyIntervals} />
                    ) : (
                      e.key
                    )}
                  </TableCell>
                  <TableCell className="align-top font-mono text-xs whitespace-pre-wrap [overflow-wrap:anywhere]">
                    <div className="flex items-start justify-between gap-2">
                      <span className="min-w-0 flex-1">
                        {e.valueIntervals.length > 0 ? (
                          <SegmentedText
                            text={e.valueText}
                            intervals={e.valueIntervals}
                          />
                        ) : (
                          e.valueText
                        )}
                      </span>
                      <CopyValueButton valueText={e.valueText} />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    );
  };

  const SpanSummary = ({ span }: { span: SpanPayload }) => {
    const durationMs =
      typeof span.duration_ms === 'number' ? span.duration_ms : null;
    const durationLabel =
      typeof durationMs === 'number' ? `${Math.round(durationMs)}ms` : '—';

    const durationTone =
      typeof durationMs === 'number'
        ? durationMs < 500
          ? 'good'
          : durationMs < 2000
            ? 'warn'
            : 'bad'
        : 'neutral';

    const durationBadgeClass =
      durationTone === 'good'
        ? 'bg-green-500/15 text-green-700 dark:text-green-300 border-green-500/30'
        : durationTone === 'warn'
          ? 'bg-yellow-500/15 text-yellow-800 dark:text-yellow-300 border-yellow-500/30'
          : durationTone === 'bad'
            ? 'bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30'
            : 'bg-muted text-muted-foreground border-border';

    const getModelName = (s: SpanPayload): string | null => {
      const attrs = s.attributes ?? {};
      const candidateKeys = [
        'gen_ai.response.model',
        'gen_ai.request.model',
        'llm.model',
        'model',
        'model_name',
        'openai.model',
        'anthropic.model',
        'ai.model',
      ];
      for (const key of candidateKeys) {
        const value = attrs[key];
        if (typeof value === 'string' && value.trim()) {
          return value.trim();
        }
      }
      return null;
    };

    const modelName = getModelName(span);

    const statusCodeRaw = span.status?.code;
    const statusCode =
      typeof statusCodeRaw === 'string'
        ? statusCodeRaw
        : typeof statusCodeRaw === 'number'
          ? String(statusCodeRaw)
          : 'STATUS_CODE_UNSET';
    const statusMessage =
      typeof span.status?.message === 'string' && span.status.message
        ? span.status.message
        : undefined;

    const statusTone =
      statusCode === 'STATUS_CODE_OK' || statusCode === '0'
        ? 'good'
        : statusCode === 'STATUS_CODE_ERROR' || statusCode === '2'
          ? 'bad'
          : 'neutral';

    const statusBadgeClass =
      statusTone === 'good'
        ? 'bg-green-500/15 text-green-700 dark:text-green-300 border-green-500/30'
        : statusTone === 'bad'
          ? 'bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30'
          : 'bg-muted text-muted-foreground border-border';

    const startLocal = formatLocalDateTime(span.start_time);
    const endLocal = formatLocalDateTime(span.end_time);

    const serviceName =
      (span.resource_attributes?.['service.name'] as string | undefined) ??
      undefined;

    return (
      <div className="space-y-2">
        <TooltipProvider>
          <div className="flex flex-wrap gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge
                  variant="outline"
                  className={`px-2 py-1 text-xs ${statusBadgeClass}`}
                  title={statusMessage ?? undefined}
                >
                  {statusCode}
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <div className="max-w-[420px] text-xs">
                  {statusMessage ?? 'No status message.'}
                </div>
              </TooltipContent>
            </Tooltip>
            <Badge
              variant="outline"
              className={`gap-1.5 px-2 py-1 text-xs ${durationBadgeClass}`}
            >
              <Clock className="h-3 w-3" />
              <span className="font-medium">{durationLabel}</span>
              <span className="opacity-70">duration</span>
            </Badge>
            <Badge
              variant="outline"
              className="gap-1.5 px-2 py-1 text-xs bg-muted/40 text-foreground border-border"
              title={modelName ?? undefined}
            >
              <Cpu className="h-3 w-3" />
              <span className="font-medium truncate max-w-[240px]">
                {modelName ?? 'Unknown model'}
              </span>
            </Badge>
          </div>
        </TooltipProvider>

        <div className="text-xs text-muted-foreground flex flex-wrap gap-x-4 gap-y-1">
          {serviceName ? <span>service: {serviceName}</span> : null}
          {startLocal ? <span>start: {startLocal}</span> : null}
          {endLocal ? <span>end: {endLocal}</span> : null}
        </div>
      </div>
    );
  };

  const DetailsSection = ({
    title,
    open,
    onOpenChange,
    children,
  }: {
    title: string;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    children: React.ReactNode;
  }) => {
    return (
      <Collapsible open={open} onOpenChange={onOpenChange}>
        <div className="rounded-md border border-border">
          <div className="flex items-center justify-between gap-2 p-2">
            <div className="text-xs font-medium text-muted-foreground">
              {title}
            </div>
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                title={open ? 'Collapse' : 'Expand'}
              >
                {open ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </Button>
            </CollapsibleTrigger>
          </div>
          <CollapsibleContent className="px-2 pb-2">
            {children}
          </CollapsibleContent>
        </div>
      </Collapsible>
    );
  };

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="h-6 px-2 text-xs"
        onClick={(e) => {
          e.stopPropagation();
          void fetchTelemetry();
        }}
        title="Show OpenTelemetry data for this message"
      >
        Telemetry
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-3xl h-[80vh] max-h-[80vh] overflow-hidden !flex !flex-col !top-6 sm:!top-10 !translate-y-0">
          <DialogHeader>
            <DialogTitle>
              {payload?.span?.operation_name ?? 'Telemetry'}
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 min-h-0 overflow-hidden flex flex-col gap-3">
            {loading ? (
              <div className="text-xs text-muted-foreground">Loading…</div>
            ) : error ? (
              <div className="text-xs text-destructive whitespace-pre-wrap [overflow-wrap:anywhere]">
                {error}
              </div>
            ) : payload ? (
              <>
                <SpanSummary span={payload.span} />

                <Tabs
                  value={activeTab}
                  onValueChange={(v) =>
                    setActiveTab(v as 'details' | 'events' | 'links' | 'raw')
                  }
                  className="w-full flex-1 min-h-0 flex flex-col"
                >
                  <TabsList className="shrink-0">
                    <TabsTrigger value="details">Details</TabsTrigger>
                    <TabsTrigger value="events">Events</TabsTrigger>
                    <TabsTrigger value="links">Links</TabsTrigger>
                    <TabsTrigger value="raw">Raw</TabsTrigger>
                  </TabsList>

                  {activeTab !== 'raw' && (
                    <div className="mt-2 flex flex-wrap items-center gap-2 shrink-0">
                      <Input
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search…"
                        className="h-8 text-xs bg-background flex-1 min-w-[180px] max-w-sm hover:bg-secondary hover:text-primary focus-visible:ring-0 focus-visible:border-ring"
                        aria-invalid={regexError ? true : undefined}
                      />
                      <Select
                        value={searchType}
                        onValueChange={(v) =>
                          setSearchType(v as OtelSearchType)
                        }
                      >
                        <SelectTrigger className="h-8 w-[120px] text-xs bg-background flex-shrink-0 hover:bg-secondary hover:text-primary focus:ring-0 focus-visible:ring-0 focus-visible:border-ring focus-visible:shadow-[0_0_0_1px_hsl(var(--ring))]">
                          <SelectValue placeholder="Exact" />
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
                  )}

                  <div className="mt-3 flex-1 min-h-0 flex flex-col">
                    <TabsContent
                      value="details"
                      className="mt-0 flex-1 min-h-0 overflow-hidden"
                    >
                      <ScrollArea className="h-full">
                        <div className="space-y-3 pb-6">
                          <DetailsSection
                            title="Span attributes"
                            open={detailsOpen.spanAttributes}
                            onOpenChange={(next) =>
                              setDetailsOpen((prev) => ({
                                ...prev,
                                spanAttributes: next,
                              }))
                            }
                          >
                            <KeyValueTable
                              entries={recordToEntries(payload.span.attributes)}
                            />
                          </DetailsSection>

                          <DetailsSection
                            title="Resource attributes"
                            open={detailsOpen.resourceAttributes}
                            onOpenChange={(next) =>
                              setDetailsOpen((prev) => ({
                                ...prev,
                                resourceAttributes: next,
                              }))
                            }
                          >
                            <KeyValueTable
                              entries={recordToEntries(
                                payload.span.resource_attributes
                              )}
                            />
                          </DetailsSection>

                          <DetailsSection
                            title="Top-level span fields"
                            open={detailsOpen.topLevel}
                            onOpenChange={(next) =>
                              setDetailsOpen((prev) => ({
                                ...prev,
                                topLevel: next,
                              }))
                            }
                          >
                            <KeyValueTable
                              entries={spanTopLevelEntries(
                                payload.span as unknown as Record<
                                  string,
                                  unknown
                                >
                              )}
                            />
                          </DetailsSection>
                        </div>
                      </ScrollArea>
                    </TabsContent>

                    <TabsContent
                      value="events"
                      className="mt-0 flex-1 min-h-0 overflow-hidden"
                    >
                      <ScrollArea className="h-full">
                        <div className="space-y-2 pb-6">
                          {(payload.span.events ?? []).length === 0 ? (
                            <div className="text-xs text-muted-foreground">
                              No events.
                            </div>
                          ) : (
                            (payload.span.events ?? []).map((ev, idx) => (
                              <Collapsible
                                key={idx}
                                open={eventOpen[idx] ?? true}
                                onOpenChange={(next) =>
                                  setEventOpen((prev) => ({
                                    ...prev,
                                    [idx]: next,
                                  }))
                                }
                              >
                                <div className="rounded-md border border-border p-2">
                                  <div className="flex items-center justify-between gap-2">
                                    <div className="min-w-0 flex-1 flex items-center gap-2">
                                      <div className="min-w-0 flex-1 text-xs font-medium text-muted-foreground truncate">
                                        {ev.name || '(unnamed event)'}
                                      </div>
                                      {ev.timestamp ? (
                                        <div className="shrink-0 text-xs text-muted-foreground">
                                          {formatLocalDateTime(ev.timestamp) ??
                                            ev.timestamp}
                                        </div>
                                      ) : null}
                                    </div>
                                    <div className="shrink-0">
                                      <CollapsibleTrigger asChild>
                                        <Button
                                          variant="ghost"
                                          size="sm"
                                          className="h-6 w-6 p-0"
                                          title={
                                            (eventOpen[idx] ?? true)
                                              ? 'Collapse'
                                              : 'Expand'
                                          }
                                        >
                                          {(eventOpen[idx] ?? true) ? (
                                            <ChevronUp className="h-4 w-4" />
                                          ) : (
                                            <ChevronDown className="h-4 w-4" />
                                          )}
                                        </Button>
                                      </CollapsibleTrigger>
                                    </div>
                                  </div>
                                  <CollapsibleContent className="mt-2">
                                    <KeyValueTable
                                      entries={recordToEntries(ev.attributes)}
                                    />
                                  </CollapsibleContent>
                                </div>
                              </Collapsible>
                            ))
                          )}
                        </div>
                      </ScrollArea>
                    </TabsContent>

                    <TabsContent
                      value="links"
                      className="mt-0 flex-1 min-h-0 overflow-hidden"
                    >
                      <ScrollArea className="h-full">
                        <div className="space-y-2 pb-6">
                          {(payload.span.links ?? []).length === 0 ? (
                            <div className="text-xs text-muted-foreground">
                              No links.
                            </div>
                          ) : (
                            (payload.span.links ?? []).map((lnk, idx) => (
                              <div
                                key={idx}
                                className="rounded-md border border-border p-2 space-y-2"
                              >
                                <div className="text-xs text-muted-foreground">
                                  {lnk.trace_id ? (
                                    <div className="truncate">
                                      trace_id: {lnk.trace_id}
                                    </div>
                                  ) : null}
                                  {lnk.span_id ? (
                                    <div className="truncate">
                                      span_id: {lnk.span_id}
                                    </div>
                                  ) : null}
                                </div>
                                <KeyValueTable
                                  title="Link attributes"
                                  entries={recordToEntries(lnk.attributes)}
                                />
                              </div>
                            ))
                          )}
                        </div>
                      </ScrollArea>
                    </TabsContent>

                    <TabsContent
                      value="raw"
                      className="mt-0 flex-1 min-h-0 overflow-hidden"
                    >
                      <ScrollArea className="h-full">
                        <div className="pb-3 flex justify-end">
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 px-2 text-xs"
                            onClick={() => {
                              void (async () => {
                                const success =
                                  await copyToClipboard(rawJsonText);
                                if (!success) return;
                                setRawCopied(true);
                                setTimeout(() => setRawCopied(false), 2000);
                              })();
                            }}
                            disabled={!rawJsonText}
                          >
                            {rawCopied ? (
                              <>
                                <Check className="h-3 w-3 mr-1" />
                                Copied
                              </>
                            ) : (
                              <>
                                <Copy className="h-3 w-3 mr-1" />
                                Copy
                              </>
                            )}
                          </Button>
                        </div>
                        <pre className="text-xs whitespace-pre-wrap [overflow-wrap:anywhere] font-mono pb-6">
                          {rawJsonText}
                        </pre>
                      </ScrollArea>
                    </TabsContent>
                  </div>
                </Tabs>
              </>
            ) : (
              <div className="text-xs text-muted-foreground">No data.</div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
