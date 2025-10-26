'use client';

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import Editor, { type Monaco, type OnMount } from '@monaco-editor/react';
import type * as monacoEditor from 'monaco-editor';
import { Check, Copy, Maximize2, Play } from 'lucide-react';
import { useTheme } from 'next-themes';

import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  useExecuteDqlQueryMutation,
  useGetDqlSchemaQuery,
  useGetAgentRunMetadataFieldsQuery,
} from '@/app/api/collectionApi';
import { DqlExecuteResponse } from '@/app/types/dqlTypes';
import { registerDqlCompletionProvider } from '@/app/utils/dqlCompletions';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { TableContainer } from './TableContainer';
import { copyToClipboard } from '@/lib/utils';

interface DQLEditorProps {
  collectionId?: string;
  initialQuery?: string;
  onQueryChange?: (query: string) => void;
  initialResult?: DqlExecuteResponse | null;
  onResultChange?: (result: DqlExecuteResponse | null) => void;
  initialErrorMessage?: string | null;
  onErrorMessageChange?: (message: string | null) => void;
}

export const DEFAULT_DQL_QUERY =
  'SELECT id, name, created_at FROM agent_runs ORDER BY created_at DESC LIMIT 20';
const NORMALIZED_DEFAULT_QUERY = DEFAULT_DQL_QUERY.replace(/\s+/g, ' ').trim();

const normalizeQueryValue = (value: string) =>
  value.replace(/\s+/g, ' ').trim();

const isFallbackQueryValue = (value: string | null | undefined) => {
  if (!value) {
    return true;
  }
  const normalized = normalizeQueryValue(value);
  return normalized.length === 0 || normalized === NORMALIZED_DEFAULT_QUERY;
};

// Keeps result tables readable by preventing any single column from dominating the viewport.
const MAX_RESULT_COLUMN_WIDTH_PX = 300;

const formatCellValue = (value: unknown): string => {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string') {
    return value;
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (Array.isArray(value)) {
    return JSON.stringify(value);
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
};

const extractErrorMessage = (error: unknown): string => {
  if (!error) {
    return 'Unknown error';
  }
  if (typeof error === 'string') {
    return error;
  }
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === 'object') {
    const data = (error as { data?: unknown }).data;
    if (data && typeof data === 'object' && 'detail' in data && data.detail) {
      return String((data as { detail?: unknown }).detail);
    }
    if ('status' in error) {
      const status = (error as { status?: unknown }).status;
      return `Request failed${status ? ` with status ${status}` : ''}`;
    }
  }
  return String(error);
};

interface TruncatableCellValueProps {
  text: string;
  label: string;
  maxWidth: number;
}

const TruncatableCellValue = ({
  text,
  label,
  maxWidth,
}: TruncatableCellValueProps) => {
  const contentRef = useRef<HTMLSpanElement | null>(null);
  const [isTruncated, setIsTruncated] = useState(false);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const copyResetTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (
        copyResetTimeoutRef.current !== null &&
        typeof window !== 'undefined'
      ) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  useLayoutEffect(() => {
    const node = contentRef.current;
    if (!node) {
      setIsTruncated(false);
      return;
    }

    const checkOverflow = () => {
      const clientWidth = node.clientWidth;
      const scrollWidth = node.scrollWidth;
      const hasOverflow = clientWidth > 0 && scrollWidth - clientWidth > 1;
      setIsTruncated((prev) => {
        if (prev === hasOverflow) {
          return prev;
        }
        return hasOverflow;
      });
    };

    checkOverflow();

    let animationFrame: number | null = null;
    if (typeof window !== 'undefined') {
      animationFrame = window.requestAnimationFrame(checkOverflow);
    }

    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        checkOverflow();
      });
      observer.observe(node);
    }

    return () => {
      if (animationFrame !== null && typeof window !== 'undefined') {
        window.cancelAnimationFrame(animationFrame);
      }
      observer?.disconnect();
    };
  }, [text]);

  const handleCopy = useCallback(async () => {
    const success = await copyToClipboard(text);
    if (!success) {
      return;
    }
    setCopied(true);
    if (copyResetTimeoutRef.current !== null && typeof window !== 'undefined') {
      window.clearTimeout(copyResetTimeoutRef.current);
    }
    if (typeof window !== 'undefined') {
      copyResetTimeoutRef.current = window.setTimeout(() => {
        setCopied(false);
        copyResetTimeoutRef.current = null;
      }, 2000);
    }
  }, [text]);

  return (
    <div className="flex items-start gap-1 max-w-full" style={{ maxWidth }}>
      <span ref={contentRef} className="flex-1 min-w-0 truncate" title={text}>
        {text}
      </span>
      {isTruncated && (
        <Dialog
          open={isDialogOpen}
          onOpenChange={(nextOpen) => {
            setIsDialogOpen(nextOpen);
            if (!nextOpen) {
              setCopied(false);
              if (
                copyResetTimeoutRef.current !== null &&
                typeof window !== 'undefined'
              ) {
                window.clearTimeout(copyResetTimeoutRef.current);
                copyResetTimeoutRef.current = null;
              }
            }
          }}
        >
          <DialogTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-5 w-5 flex-shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="View full cell value"
            >
              <Maximize2 className="h-3.5 w-3.5" />
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-3xl">
            <DialogHeader className="flex flex-row items-start justify-between gap-3 pr-10">
              <DialogTitle className="text-base font-semibold break-words">
                {label}
              </DialogTitle>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  void handleCopy();
                }}
                className="h-7 gap-2 text-xs"
                aria-label="Copy cell value"
              >
                {copied ? (
                  <>
                    <Check className="h-3.5 w-3.5" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    Copy
                  </>
                )}
              </Button>
            </DialogHeader>
            <div className="max-h-[60vh] overflow-auto rounded border bg-muted/40 p-3 font-mono text-xs whitespace-pre-wrap break-words">
              {text || <span className="text-muted-foreground">(empty)</span>}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
};

const DQLEditor = ({
  collectionId,
  initialQuery,
  onQueryChange,
  initialResult,
  onResultChange,
  initialErrorMessage,
  onErrorMessageChange,
}: DQLEditorProps) => {
  const [query, setQuery] = useState<string>(initialQuery ?? DEFAULT_DQL_QUERY);
  const [hasUserEditedQuery, setHasUserEditedQuery] = useState<boolean>(
    initialQuery !== undefined && !isFallbackQueryValue(initialQuery)
  );
  const [result, setResult] = useState<DqlExecuteResponse | null>(
    initialResult ?? null
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(
    initialErrorMessage ?? null
  );
  const { resolvedTheme } = useTheme();
  const [isSchemaVisible, setIsSchemaVisible] = useState(false);
  const latestRequestIdRef = useRef(0);

  useEffect(() => {
    if (initialQuery === undefined) {
      setQuery(DEFAULT_DQL_QUERY);
      setHasUserEditedQuery(false);
      return;
    }
    if (initialQuery !== query) {
      setQuery(initialQuery);
    }
    setHasUserEditedQuery(
      initialQuery !== undefined && !isFallbackQueryValue(initialQuery)
    );
  }, [initialQuery, query]);

  useEffect(() => {
    if (collectionId === undefined) {
      return;
    }
    if (initialQuery === undefined) {
      setHasUserEditedQuery(false);
    }
  }, [collectionId, initialQuery]);

  useEffect(() => {
    if (initialResult === undefined) {
      return;
    }
    if (initialResult !== result) {
      setResult(initialResult);
    }
  }, [initialResult, result]);

  useEffect(() => {
    if (initialErrorMessage === undefined) {
      return;
    }
    if (initialErrorMessage !== errorMessage) {
      setErrorMessage(initialErrorMessage);
    }
  }, [initialErrorMessage, errorMessage]);

  const {
    data: schemaData,
    isLoading: isSchemaLoading,
    isError: schemaError,
  } = useGetDqlSchemaQuery(collectionId ?? '', {
    skip: !collectionId,
  });
  const { data: metadataFieldsData } = useGetAgentRunMetadataFieldsQuery(
    collectionId ?? '',
    { skip: !collectionId }
  );

  const metadataFields = useMemo(
    () => metadataFieldsData?.fields ?? [],
    [metadataFieldsData]
  );

  const monacoInstanceRef = useRef<Monaco | null>(null);
  const completionDisposableRef = useRef<monacoEditor.IDisposable | null>(null);
  const [isEditorReady, setEditorReady] = useState(false);

  const editorOptions = useMemo(
    () => ({
      minimap: { enabled: false },
      wordWrap: 'on' as const,
      tabCompletion: 'on' as const,
      renderWhitespace: 'selection' as const,
      quickSuggestions: true,
      suggestSelection: 'first' as const,
      scrollBeyondLastLine: false,
      automaticLayout: true,
      ariaLabel: 'Docent Query Language editor',
    }),
    []
  );

  const agentRunsTable = useMemo(
    () =>
      schemaData?.tables.find(
        (table) => table.name.toLowerCase() === 'agent_runs'
      ) ?? null,
    [schemaData]
  );

  const agentRunsDefaultQuery = useMemo(() => {
    if (!agentRunsTable) {
      return null;
    }

    const columns = agentRunsTable.columns
      .filter((column) => !column.alias_for)
      .filter((column) => column.name.toLowerCase() !== 'text_for_search')
      .map((column) => column.name)
      .filter((name) => name && name.trim().length > 0);

    if (columns.length === 0) {
      return null;
    }

    const columnList = columns.join(',\n  ');
    const hasCreatedAt = columns.some(
      (name) => name.toLowerCase() === 'created_at'
    );
    const orderClause = hasCreatedAt ? '\nORDER BY created_at DESC' : '';

    return `SELECT\n  ${columnList}\nFROM agent_runs${orderClause}\nLIMIT 20`;
  }, [agentRunsTable]);

  useEffect(() => {
    if (!agentRunsDefaultQuery) {
      return;
    }

    if (query === agentRunsDefaultQuery) {
      return;
    }

    if (
      !hasUserEditedQuery &&
      isFallbackQueryValue(query) &&
      query.trim().length > 0
    ) {
      setQuery(agentRunsDefaultQuery);
      onQueryChange?.(agentRunsDefaultQuery);
    }
  }, [agentRunsDefaultQuery, hasUserEditedQuery, onQueryChange, query]);

  useEffect(() => {
    setIsSchemaVisible(false);
  }, [collectionId]);

  const [executeDqlQuery, { isLoading: isExecuting }] =
    useExecuteDqlQueryMutation();

  const handleRunQuery = useCallback(
    async (overrideQuery?: string) => {
      const nextQuery = overrideQuery ?? query;
      const effectiveQuery = nextQuery.trim();

      if (!collectionId || !effectiveQuery) {
        const message = 'Enter a query before running.';
        setErrorMessage(message);
        onErrorMessageChange?.(message);
        setResult(null);
        onResultChange?.(null);
        return;
      }

      const requestId = latestRequestIdRef.current + 1;
      latestRequestIdRef.current = requestId;

      if (overrideQuery !== undefined) {
        setQuery(nextQuery);
        onQueryChange?.(nextQuery);
      }

      setErrorMessage(null);
      onErrorMessageChange?.(null);
      setResult(null);
      onResultChange?.(null);
      try {
        const response = await executeDqlQuery({
          collectionId,
          dql: effectiveQuery,
        }).unwrap();
        if (latestRequestIdRef.current === requestId) {
          setResult(response);
          onResultChange?.(response);
        }
      } catch (err) {
        if (latestRequestIdRef.current === requestId) {
          setResult(null);
          onResultChange?.(null);
          const message = extractErrorMessage(err);
          setErrorMessage(message);
          onErrorMessageChange?.(message);
        }
      }
    },
    [
      collectionId,
      executeDqlQuery,
      onErrorMessageChange,
      onQueryChange,
      onResultChange,
      query,
    ]
  );

  const displayColumns = useMemo(() => {
    if (!result) {
      return [];
    }

    const fallbackColumnName = (column: string | undefined, index: number) => {
      if (column && column.trim().length > 0) {
        return column;
      }
      return `column_${index + 1}`;
    };

    if (
      result.selected_columns &&
      result.selected_columns.length === result.columns.length
    ) {
      return result.selected_columns.map((selected, index) => {
        const outputName = selected.output_name?.trim();
        if (outputName) {
          return outputName;
        }
        const expressionSql = selected.expression_sql?.trim();
        if (expressionSql) {
          return expressionSql;
        }
        return fallbackColumnName(result.columns[index], index);
      });
    }

    return result.columns.map(fallbackColumnName);
  }, [result]);

  const handleEditorChange = useCallback(
    (value?: string) => {
      const nextValue = value ?? '';
      setQuery(nextValue);
      onQueryChange?.(nextValue);
      setHasUserEditedQuery(true);
    },
    [onQueryChange]
  );

  const handleEditorMount = useCallback<OnMount>(
    (editor, monaco) => {
      if (typeof window !== 'undefined') {
        console.debug('[DQL editor] Monaco mounted');
      }
      monacoInstanceRef.current = monaco;
      monaco.editor.setTheme(resolvedTheme === 'dark' ? 'vs-dark' : 'vs-light');
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
        const latestValue = editor.getValue();
        void handleRunQuery(latestValue ?? undefined);
      });
      editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => {
        const latestValue = editor.getValue();
        void handleRunQuery(latestValue ?? undefined);
      });
      setEditorReady(true);
    },
    [handleRunQuery, resolvedTheme]
  );

  useEffect(() => {
    return () => {
      completionDisposableRef.current?.dispose();
      completionDisposableRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!isEditorReady || !monacoInstanceRef.current) {
      return;
    }
    completionDisposableRef.current?.dispose();
    const disposable = registerDqlCompletionProvider(
      monacoInstanceRef.current,
      schemaData,
      metadataFields
    );
    completionDisposableRef.current = disposable;

    return () => {
      disposable.dispose();
      if (completionDisposableRef.current === disposable) {
        completionDisposableRef.current = null;
      }
    };
  }, [isEditorReady, schemaData, metadataFields]);

  useEffect(() => {
    if (!isEditorReady || !monacoInstanceRef.current) {
      return;
    }
    const themeName = resolvedTheme === 'dark' ? 'vs-dark' : 'vs-light';
    monacoInstanceRef.current.editor.setTheme(themeName);
  }, [isEditorReady, resolvedTheme]);

  const schemaTables = useMemo(
    () => (schemaData ? schemaData.tables : []),
    [schemaData]
  );

  return (
    <div className="flex flex-col lg:flex-row gap-3 h-full min-h-0 overflow-hidden">
      <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
        <div className="flex flex-col gap-2 flex-shrink-0">
          <div className="flex items-center justify-between">
            <Label>Docent Query Language</Label>
            <a
              href="https://docs.transluce.org/concepts/docent_query_language/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary hover:underline"
            >
              Documentation
            </a>
          </div>
          <div className="border rounded-md">
            <Editor
              height="240px"
              language="sql"
              value={query}
              onChange={handleEditorChange}
              onMount={handleEditorMount}
              options={editorOptions}
              theme={resolvedTheme === 'dark' ? 'vs-dark' : 'vs-light'}
            />
          </div>
        </div>
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2 sm:gap-3 flex-shrink-0">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full sm:w-auto"
            onClick={() => setIsSchemaVisible((prev) => !prev)}
          >
            {isSchemaVisible ? 'Hide Schema Explorer' : 'Show Schema Explorer'}
          </Button>
          <Button
            onClick={() => {
              void handleRunQuery();
            }}
            disabled={!collectionId || isExecuting}
            className="w-full sm:w-auto sm:self-end"
          >
            <Play className="h-4 w-4 mr-2" />
            {isExecuting ? 'Running…' : 'Run Query'}
          </Button>
        </div>

        {errorMessage && (
          <div className="border border-red-border bg-red-bg/20 text-red-text rounded-md p-3 text-sm">
            {errorMessage}
          </div>
        )}
        <div className="flex-1 min-h-0 flex flex-col gap-3 overflow-hidden">
          {result && (
            <>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>{result.row_count} rows</span>
                <span>·</span>
                <span>{result.execution_time_ms.toFixed(1)} ms</span>
                {result.truncated && (
                  <>
                    <span>·</span>
                    <Badge variant="outline">Truncated</Badge>
                  </>
                )}
                <span>·</span>
                <span>Limit applied: {result.applied_limit}</span>
              </div>
              <TableContainer>
                <Table className="min-w-full table-auto">
                  <TableHeader className="sticky top-0 z-20 bg-secondary">
                    <TableRow className="text-xs">
                      {displayColumns.map((column, index) => (
                        <TableHead
                          key={`${column}-${index}`}
                          className="text-xs font-medium"
                          style={{ maxWidth: MAX_RESULT_COLUMN_WIDTH_PX }}
                        >
                          <span
                            className="block truncate"
                            title={column}
                            style={{ maxWidth: MAX_RESULT_COLUMN_WIDTH_PX }}
                          >
                            {column}
                          </span>
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.rows.map((row, rowIndex) => (
                      <TableRow key={rowIndex} className="text-xs h-10">
                        {result.columns.map((column, columnIndex) => {
                          const cellValue = formatCellValue(row[columnIndex]);
                          const columnLabel =
                            displayColumns[columnIndex] ??
                            result.columns[columnIndex] ??
                            `Column ${columnIndex + 1}`;
                          return (
                            <TableCell
                              key={`${column}-${columnIndex}`}
                              className="py-1.5"
                              style={{ maxWidth: MAX_RESULT_COLUMN_WIDTH_PX }}
                            >
                              <TruncatableCellValue
                                text={cellValue}
                                label={columnLabel}
                                maxWidth={MAX_RESULT_COLUMN_WIDTH_PX}
                              />
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    ))}
                    {result.rows.length === 0 && (
                      <TableRow className="h-10">
                        <TableCell
                          colSpan={displayColumns.length || 1}
                          className="text-center text-muted-foreground text-sm"
                        >
                          Query returned no rows.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </>
          )}

          {!result && !errorMessage && (
            <div className="border border-dashed rounded-md p-6 text-sm text-muted-foreground">
              Run a query to see results here. Need a starting point? Try
              selecting from <code>agent_runs</code> or joining to{' '}
              <code>judge_results</code>.
            </div>
          )}
        </div>
      </div>

      {isSchemaVisible && (
        <div className="lg:w-72 border rounded-md p-3 space-y-3 bg-muted/20 flex-shrink-0 flex flex-col overflow-hidden">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold">Schema Explorer</div>
              <div className="text-xs text-muted-foreground">
                Tables available in DQL
              </div>
            </div>
            {isSchemaLoading && (
              <span className="text-xs text-muted-foreground">Loading…</span>
            )}
            {schemaError && !isSchemaLoading && (
              <span className="text-xs text-red-text">Failed to load</span>
            )}
          </div>
          <ScrollArea className="flex-1 min-h-0">
            <div className="space-y-3 pr-2">
              {schemaTables.map((table) => (
                <div key={table.name} className="space-y-2">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <span>{table.name}</span>
                    {table.aliases && table.aliases.length > 0 && (
                      <span className="text-xs text-muted-foreground">
                        alias: {table.aliases.join(', ')}
                      </span>
                    )}
                  </div>
                  <div className="pl-2 text-xs space-y-1 text-muted-foreground">
                    {table.columns.map((column) => (
                      <div
                        key={`${table.name}-${column.name}`}
                        className="flex justify-between gap-2"
                      >
                        <span>{column.name}</span>
                        <span>{column.data_type ?? ''}</span>
                      </div>
                    ))}
                    {table.columns.length === 0 && (
                      <div className="text-muted-foreground/70">
                        No columns available.
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {schemaTables.length === 0 && !isSchemaLoading && (
                <div className="text-xs text-muted-foreground">
                  No schema information available.
                </div>
              )}
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  );
};

export default DQLEditor;
