import type * as monacoEditor from 'monaco-editor';

/**
 * NOTE: We are experimenting with an ANTLR-based completion engine.
 * See app/dql/README.md for the spike. The functions below still use
 * heuristic-based suggestions until the parser is wired in.
 */

import { DqlSchemaResponse, DqlTableSchema } from '@/app/types/dqlTypes';
import { TranscriptMetadataField } from '@/app/types/experimentViewerTypes';
import { formatFilterFieldLabel } from '@/app/utils/formatMetadataField';

const SQL_KEYWORDS = [
  'SELECT',
  'FROM',
  'WHERE',
  'AND',
  'OR',
  'NOT',
  'ORDER BY',
  'GROUP BY',
  'HAVING',
  'JOIN',
  'LEFT JOIN',
  'RIGHT JOIN',
  'OUTER JOIN',
  'INNER JOIN',
  'INNER',
  'ON',
  'LIMIT',
  'OFFSET',
  'DISTINCT',
  'EXISTS',
  'IN',
  'BETWEEN',
  'ILIKE',
  'LIKE',
  'IS NULL',
  'IS NOT NULL',
  'CASE',
  'WHEN',
  'THEN',
  'ELSE',
  'END',
  'AS',
  'ASC',
  'DESC',
  'NULLS FIRST',
  'NULLS LAST',
  'LEFT',
  'RIGHT',
  'OUTER',
  'JOIN',
];

const SQL_KEYWORD_SET = new Set(
  SQL_KEYWORDS.map((keyword) => keyword.toUpperCase())
);

const KEYWORDS_BY_CLAUSE: Record<string, string[]> = {
  DEFAULT: SQL_KEYWORDS,
  NONE: ['SELECT'],
  SELECT: ['DISTINCT', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'AS'],
  FROM: [
    'JOIN',
    'LEFT JOIN',
    'RIGHT JOIN',
    'OUTER JOIN',
    'INNER JOIN',
    'WHERE',
  ],
  WHERE: [
    'AND',
    'OR',
    'NOT',
    'BETWEEN',
    'IN',
    'LIKE',
    'ILIKE',
    'IS NULL',
    'IS NOT NULL',
  ],
  'GROUP BY': ['HAVING'],
  HAVING: ['AND', 'OR', 'NOT', 'BETWEEN', 'IN'],
  'ORDER BY': ['ASC', 'DESC', 'NULLS FIRST', 'NULLS LAST'],
  JOIN: ['ON'],
  ON: ['AND', 'OR', 'NOT'],
};

const KEYWORD_GUARDS: Record<string, (sql: string) => boolean> = {
  WHERE: (sql) => /\b(FROM|JOIN)\b/i.test(sql),
  'GROUP BY': (sql) => /\bFROM\b/i.test(sql),
  HAVING: (sql) => /\bGROUP\s+BY\b/i.test(sql),
  'ORDER BY': (sql) => /\bFROM\b/i.test(sql),
  LIMIT: (sql) => /\bFROM\b/i.test(sql),
  OFFSET: (sql) => /\bFROM\b/i.test(sql),
};

const TABLE_PATTERN =
  /\b(from|join)\s+([A-Za-z_][\w]*)(?:\s+(?:as\s+)?([A-Za-z_][\w]*))?/gi;

type MetadataSegmentInfo = {
  segment: string;
  isLeaf: boolean;
  field?: TranscriptMetadataField;
};

type MetadataSegmentMap = Map<string, Map<string, MetadataSegmentInfo>>;

export type DqlCompletionSuggestion = {
  label: string;
  insertText: string;
  kind: 'keyword' | 'table' | 'column' | 'metadata';
  detail?: string;
  documentation?: string;
  filterText?: string;
  priority?: number;
  replaceBefore?: number;
};

const normalize = (value: string) => value.toLowerCase();

const detectActiveClause = (sql: string): string | null => {
  const upper = sql.toUpperCase();
  const clauseLocations: Array<{ index: number; clause: string }> = [];

  Object.entries({
    SELECT: /\bSELECT\b/g,
    FROM: /\bFROM\b/g,
    WHERE: /\bWHERE\b/g,
    'GROUP BY': /\bGROUP\s+BY\b/g,
    HAVING: /\bHAVING\b/g,
    'ORDER BY': /\bORDER\s+BY\b/g,
    JOIN: /\bJOIN\b/g,
    ON: /\bON\b/g,
  }).forEach(([clause, regex]) => {
    regex.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(upper)) !== null) {
      clauseLocations.push({ index: match.index, clause });
    }
  });

  if (clauseLocations.length === 0) {
    return null;
  }

  clauseLocations.sort((a, b) => a.index - b.index);
  return clauseLocations[clauseLocations.length - 1].clause;
};

const getContextKeywords = (clause: string | null): string[] => {
  if (!clause) {
    return KEYWORDS_BY_CLAUSE.NONE;
  }

  return KEYWORDS_BY_CLAUSE[clause] ?? SQL_KEYWORDS;
};

const buildMetadataSegmentMap = (
  metadataFieldEntries: Array<[string, TranscriptMetadataField]>
): MetadataSegmentMap => {
  const segmentMap: MetadataSegmentMap = new Map();

  metadataFieldEntries.forEach(([fieldPath, field]) => {
    const segments = fieldPath.split('.').filter(Boolean);
    const resolvedSegments =
      segments[0]?.toLowerCase() === 'metadata' ? segments.slice(1) : segments;

    if (resolvedSegments.length === 0) {
      return;
    }

    let parentKey = '';
    resolvedSegments.forEach((segment, index) => {
      const children =
        segmentMap.get(parentKey) ?? new Map<string, MetadataSegmentInfo>();
      const existing = children.get(segment) ?? {
        segment,
        isLeaf: false,
        field: undefined,
      };

      if (index === resolvedSegments.length - 1) {
        existing.isLeaf = true;
        existing.field = field;
      }

      children.set(segment, existing);
      segmentMap.set(parentKey, children);
      parentKey = parentKey ? `${parentKey}.${segment}` : segment;
    });
  });

  return segmentMap;
};

const buildAliasMap = (
  sql: string,
  tablesByLowerName: Map<string, DqlTableSchema>
): Map<string, DqlTableSchema> => {
  const aliasMap = new Map<string, DqlTableSchema>();

  let match: RegExpExecArray | null;
  while ((match = TABLE_PATTERN.exec(sql)) !== null) {
    const tableToken = match[2];
    const aliasToken = match[3];
    const table = tablesByLowerName.get(tableToken.toLowerCase());
    if (!table) {
      continue;
    }

    aliasMap.set(table.name.toLowerCase(), table);
    aliasMap.set(tableToken.toLowerCase(), table);
    if (aliasToken) {
      const normalizedAlias = aliasToken.toLowerCase();
      if (!SQL_KEYWORD_SET.has(aliasToken.toUpperCase())) {
        aliasMap.set(normalizedAlias, table);
      }
    }
  }

  return aliasMap;
};

const resolveTable = (
  qualifier: string,
  tablesByLowerName: Map<string, DqlTableSchema>,
  aliasMap: Map<string, DqlTableSchema>
): DqlTableSchema | undefined => {
  const key = qualifier.toLowerCase();
  return aliasMap.get(key) ?? tablesByLowerName.get(key);
};

const buildTableSuggestions = (schema: DqlSchemaResponse | undefined) => {
  const suggestions: DqlCompletionSuggestion[] = [];
  if (!schema) {
    return suggestions;
  }

  schema.tables.forEach((table) => {
    suggestions.push({
      label: table.name,
      insertText: table.name,
      kind: 'table',
      detail: 'table',
      documentation:
        table.columns.length > 0
          ? `Columns:\n${table.columns.map((col) => `• ${col.name}`).join('\n')}`
          : undefined,
    });

    (table.aliases ?? []).forEach((alias) => {
      suggestions.push({
        label: alias,
        insertText: alias,
        kind: 'table',
        detail: `alias for ${table.name}`,
      });
    });
  });

  return suggestions;
};

const buildColumnSuggestions = (
  table: DqlTableSchema,
  qualifier: string,
  includeQualifierInInsert = false
) => {
  const suggestions: DqlCompletionSuggestion[] = [];
  table.columns.forEach((column) => {
    const qualifiedLabel = `${qualifier}.${column.name}`;
    const insertText = includeQualifierInInsert ? qualifiedLabel : column.name;
    suggestions.push({
      label: qualifiedLabel,
      insertText,
      filterText: qualifiedLabel,
      kind: 'column',
      detail: column.alias_for
        ? `${table.name} (alias for ${column.alias_for})`
        : table.name,
      documentation: column.data_type
        ? `${column.data_type}${column.nullable ? ' (nullable)' : ''}`
        : column.nullable
          ? 'nullable column'
          : undefined,
    });
  });
  return suggestions;
};

const buildKeywordSuggestions = (
  textBeforeCursor: string,
  contextKeywords: string[]
): DqlCompletionSuggestion[] => {
  const keywordSet = new Set<string>([...SQL_KEYWORDS, ...contextKeywords]);

  const suggestions: DqlCompletionSuggestion[] = [];
  keywordSet.forEach((keyword) => {
    const guard = KEYWORD_GUARDS[keyword];
    if (guard && !guard(textBeforeCursor)) {
      return;
    }
    suggestions.push({
      label: keyword,
      insertText: keyword,
      kind: 'keyword',
      detail: 'keyword',
    });
  });
  return suggestions;
};

const buildMetadataSuggestions = (
  textBeforeCursor: string,
  textAfterCursor: string,
  metadataSegmentMap: MetadataSegmentMap,
  tablesByLowerName: Map<string, DqlTableSchema>,
  aliasMap: Map<string, DqlTableSchema>
): DqlCompletionSuggestion[] => {
  if (metadataSegmentMap.size === 0) {
    return [];
  }

  const match = textBeforeCursor.match(
    /(?:\b([A-Za-z_][\w]*)\.)?(?:metadata_json|metadata)((?:->'[^']*')*)->'?([A-Za-z0-9_]*)$/i
  );

  if (!match) {
    return [];
  }

  const qualifierToken = match[1];
  if (qualifierToken) {
    const table = resolveTable(qualifierToken, tablesByLowerName, aliasMap);
    const hasMetadataColumn =
      table?.columns.some(
        (column) => column.name.toLowerCase() === 'metadata_json'
      ) ?? false;
    if (!hasMetadataColumn) {
      return [];
    }
  }

  const pathExpression = match[2] ?? '';
  const partial = (match[3] ?? '').toLowerCase();

  const segments: string[] = [];
  const segmentRegex = /->'([^']*)'/g;
  let segmentMatch: RegExpExecArray | null;
  while ((segmentMatch = segmentRegex.exec(pathExpression)) !== null) {
    if (segmentMatch[1]) {
      segments.push(segmentMatch[1]);
    }
  }

  const key = segments.join('.');
  const children = metadataSegmentMap.get(key);
  if (!children) {
    return [];
  }

  const hasOpeningQuoteForCurrentSegment = /->'[A-Za-z0-9_]*$/.test(match[0]);

  const hasClosingQuoteForCurrentSegment = textAfterCursor.startsWith("'");
  const hasClosingQuoteBeforeCursor = /''$/.test(textBeforeCursor);

  const suggestions: DqlCompletionSuggestion[] = [];
  children.forEach((info) => {
    if (partial && !info.segment.toLowerCase().startsWith(partial)) {
      return;
    }
    const label = `'${info.segment}'`;
    let insertText: string;
    let replaceBefore = 0;
    if (hasOpeningQuoteForCurrentSegment && hasClosingQuoteForCurrentSegment) {
      insertText = info.segment;
    } else if (hasOpeningQuoteForCurrentSegment) {
      insertText = `${info.segment}'`;
      if (hasClosingQuoteBeforeCursor && partial.length === 0) {
        replaceBefore = 1;
      }
    } else if (hasClosingQuoteForCurrentSegment) {
      insertText = `'${info.segment}`;
    } else {
      insertText = label;
    }
    const detail = info.field
      ? formatFilterFieldLabel(info.field.name)
      : info.isLeaf
        ? 'metadata field'
        : 'metadata object';
    const documentation = info.field ? `Type: ${info.field.type}` : undefined;
    suggestions.push({
      label,
      insertText,
      kind: 'metadata',
      detail,
      documentation,
      replaceBefore: replaceBefore || undefined,
    });
  });
  return suggestions;
};

const kindPriority: Record<DqlCompletionSuggestion['kind'], number> = {
  metadata: 0,
  column: 1,
  table: 2,
  keyword: 3,
};

const finalizeSuggestions = (
  suggestions: DqlCompletionSuggestion[],
  rawPrefix: string,
  preferTablesFirst: boolean
) => {
  const normalizedPrefix = rawPrefix.replace(/^'+/, '').toLowerCase();
  const seen = new Map<string, DqlCompletionSuggestion>();

  suggestions.forEach((suggestion) => {
    const compareLabel = suggestion.label.replace(/'/g, '').toLowerCase();
    const compareInsert = suggestion.insertText.replace(/'/g, '').toLowerCase();

    if (
      normalizedPrefix &&
      !compareLabel.startsWith(normalizedPrefix) &&
      !compareInsert.startsWith(normalizedPrefix)
    ) {
      return;
    }

    const key = `${suggestion.label}::${suggestion.insertText}`;
    if (!seen.has(key)) {
      seen.set(key, suggestion);
    }
  });

  const ordered = Array.from(seen.values());

  const rankByKind = (kind: DqlCompletionSuggestion['kind']): number => {
    if (preferTablesFirst) {
      switch (kind) {
        case 'table':
          return 0;
        case 'column':
          return 1;
        case 'metadata':
          return 2;
        default:
          return 3;
      }
    }
    if (normalizedPrefix && kind === 'table') {
      return -1;
    }
    return kindPriority[kind] ?? 99;
  };

  ordered.sort((a, b) => {
    const kindDiff = rankByKind(a.kind) - rankByKind(b.kind);
    if (kindDiff !== 0) {
      return kindDiff;
    }
    return a.label.toLowerCase().localeCompare(b.label.toLowerCase());
  });

  ordered.forEach((suggestion, index) => {
    suggestion.priority = index;
  });

  return ordered;
};

export const getWordAtPosition = (sql: string, offset: number): string => {
  let index = offset;
  while (index > 0 && /[A-Za-z0-9_'"]/.test(sql.charAt(index - 1))) {
    index -= 1;
  }
  return sql.slice(index, offset);
};

export const computeDqlSuggestions = (
  sql: string,
  offset: number,
  schema: DqlSchemaResponse | undefined,
  metadataFields: TranscriptMetadataField[]
): DqlCompletionSuggestion[] => {
  const prefix = getWordAtPosition(sql, offset);
  const textBeforeCursor = sql.slice(0, offset);
  const clause = detectActiveClause(textBeforeCursor);
  const contextKeywords = getContextKeywords(clause);

  const tablesByLowerName = new Map<string, DqlTableSchema>();
  (schema?.tables ?? []).forEach((table) => {
    const canonical = normalize(table.name);
    tablesByLowerName.set(canonical, table);
    (table.aliases ?? []).forEach((alias) => {
      tablesByLowerName.set(normalize(alias), table);
    });
  });

  const aliasMap = buildAliasMap(sql, tablesByLowerName);
  const metadataSegmentMap = buildMetadataSegmentMap(
    metadataFields.map((field) => [field.name, field])
  );

  const suggestions: DqlCompletionSuggestion[] = [];
  const expectTablesOnly = /\b(from|join)\s+$/i.test(textBeforeCursor);
  const trailingFromJoinMatch = textBeforeCursor.match(
    /\b(from|join)\s+[A-Za-z_][\w]*(?:\s+(?:as\s+)?([A-Za-z_][\w]*))?\s*$/i
  );
  const trailingAliasCandidate = trailingFromJoinMatch?.[2];
  const trailingIncludesOn =
    trailingFromJoinMatch && /\bON\b/i.test(trailingFromJoinMatch[0]);
  const suppressColumnsAfterTable =
    !!trailingFromJoinMatch &&
    !expectTablesOnly &&
    !trailingIncludesOn &&
    (!trailingAliasCandidate ||
      !SQL_KEYWORD_SET.has(trailingAliasCandidate.toUpperCase()));
  const preferTablesFirst =
    clause === 'ON' ||
    clause === 'JOIN' ||
    (clause === 'FROM' && /\(\s*$/.test(textBeforeCursor)) ||
    /\bON\s*\($/i.test(textBeforeCursor) ||
    /\bON\s*\([^)]*$/i.test(textBeforeCursor);

  const columnMatch = textBeforeCursor.match(
    /([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)?(?:->'[^']*')*$/
  );
  if (columnMatch) {
    const qualifier = columnMatch[1];
    const columnPrefix = (columnMatch[2] ?? '').toLowerCase();
    const table = resolveTable(qualifier, tablesByLowerName, aliasMap);
    if (table) {
      const columnSuggestions = buildColumnSuggestions(table, qualifier).filter(
        (suggestion) => {
          if (!columnPrefix) {
            return true;
          }
          return suggestion.insertText.toLowerCase().startsWith(columnPrefix);
        }
      );
      suggestions.push(...columnSuggestions);
    }
  } else {
    suggestions.push(
      ...buildKeywordSuggestions(textBeforeCursor, contextKeywords)
    );
    suggestions.push(...buildTableSuggestions(schema));

    if (!expectTablesOnly && !suppressColumnsAfterTable) {
      const seenQualifiers = new Set<string>();
      (schema?.tables ?? []).forEach((table) => {
        const key = table.name.toLowerCase();
        if (seenQualifiers.has(key)) {
          return;
        }
        seenQualifiers.add(key);
        suggestions.push(...buildColumnSuggestions(table, table.name, true));
      });

      aliasMap.forEach((table, alias) => {
        const qualifier =
          table.name.toLowerCase() === alias ? table.name : alias;
        const key = `${table.name.toLowerCase()}::${qualifier.toLowerCase()}`;
        if (seenQualifiers.has(key)) {
          return;
        }
        seenQualifiers.add(key);
        suggestions.push(...buildColumnSuggestions(table, qualifier, true));
      });
    }
  }

  suggestions.push(
    ...buildMetadataSuggestions(
      textBeforeCursor,
      sql.slice(offset),
      metadataSegmentMap,
      tablesByLowerName,
      aliasMap
    )
  );

  return finalizeSuggestions(suggestions, prefix, preferTablesFirst);
};

const mapKindToMonaco = (
  monaco: typeof monacoEditor,
  kind: DqlCompletionSuggestion['kind']
) => {
  const { languages } = monaco;
  switch (kind) {
    case 'keyword':
      return languages.CompletionItemKind.Keyword;
    case 'table':
      return languages.CompletionItemKind.Class;
    case 'column':
      return languages.CompletionItemKind.Field;
    case 'metadata':
      return languages.CompletionItemKind.Property;
    default:
      return languages.CompletionItemKind.Text;
  }
};

const logDebug = (message: string, payload?: unknown) => {
  if (typeof window !== 'undefined') {
    console.debug(`[DQL completions] ${message}`, payload ?? {});
  }
};

export const registerDqlCompletionProvider = (
  monaco: typeof monacoEditor,
  schema: DqlSchemaResponse | undefined,
  metadataFields: TranscriptMetadataField[]
): monacoEditor.IDisposable => {
  logDebug('registering provider', {
    schemaTables: schema?.tables?.length ?? 0,
    metadataFields: metadataFields.length,
  });

  return monaco.languages.registerCompletionItemProvider('sql', {
    triggerCharacters: [' ', '.', "'", '>', '('],
    provideCompletionItems(model, position) {
      const offset = model.getOffsetAt(position);
      const sql = model.getValue();
      const suggestions = computeDqlSuggestions(
        sql,
        offset,
        schema,
        metadataFields
      );

      logDebug('provideCompletionItems', {
        offset,
        cursor: { line: position.lineNumber, column: position.column },
        totalSuggestions: suggestions.length,
        sample: suggestions.slice(0, 5),
      });

      const prefix = getWordAtPosition(sql, offset);
      const trailingWordMatch = prefix.match(/([A-Za-z0-9_]+)$/);
      const replaceLength = trailingWordMatch ? trailingWordMatch[1].length : 0;
      return {
        suggestions: suggestions.map((item, index) => ({
          label: item.label,
          insertText: item.insertText,
          filterText:
            item.filterText ??
            (item.kind === 'metadata'
              ? item.label.replace(/'/g, '')
              : item.insertText || item.label),
          kind: mapKindToMonaco(monaco, item.kind),
          detail: item.detail,
          documentation: item.documentation,
          range: new monaco.Range(
            position.lineNumber,
            Math.max(
              1,
              position.column - replaceLength - (item.replaceBefore ?? 0)
            ),
            position.lineNumber,
            position.column
          ),
          sortText: `${(item.priority ?? index).toString().padStart(6, '0')}`,
        })),
      };
    },
  });
};
