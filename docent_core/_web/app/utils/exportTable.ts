export type DelimitedFormat = 'csv' | 'tsv';

interface TabularExportOptions {
  columns: string[];
  rows: unknown[][];
  format?: DelimitedFormat;
  filename?: string;
}

const FORMAT_CONFIG: Record<
  DelimitedFormat,
  { delimiter: string; mime: string; extension: string }
> = {
  csv: {
    delimiter: ',',
    mime: 'text/csv;charset=utf-8;',
    extension: 'csv',
  },
  tsv: {
    delimiter: '\t',
    mime: 'text/tab-separated-values;charset=utf-8;',
    extension: 'tsv',
  },
};

const normalizeValue = (value: unknown): string => {
  if (value === null || value === undefined) {
    return '';
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (Array.isArray(value) || typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
};

const escapeField = (value: string, delimiter: string): string => {
  if (value === '') {
    return '';
  }

  const needsQuotes =
    value.includes('"') ||
    value.includes('\n') ||
    value.includes('\r') ||
    value.includes(delimiter);

  if (!needsQuotes) {
    return value;
  }

  const escaped = value.replace(/"/g, '""');
  return `"${escaped}"`;
};

export const exportTabularData = ({
  columns,
  rows,
  format = 'csv',
  filename = 'data',
}: TabularExportOptions) => {
  const config = FORMAT_CONFIG[format] ?? FORMAT_CONFIG.csv;
  const delimiter = config.delimiter;

  const headerLine = columns
    .map((column) => escapeField(column ?? '', delimiter))
    .join(delimiter);

  const dataLines = rows.map((row) =>
    columns
      .map((_, index) => escapeField(normalizeValue(row[index]), delimiter))
      .join(delimiter)
  );

  const content = [headerLine, ...dataLines].join('\n');
  const blob = new Blob([content], { type: config.mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${filename}.${config.extension}`;
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 500);
};
