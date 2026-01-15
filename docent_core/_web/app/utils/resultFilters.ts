export type ResultColumnType = 'str' | 'number' | 'bool' | 'other';

export type ResultFilterOp = '==' | '!=' | '~*' | '<' | '<=' | '>' | '>=';

export interface ResultFilter {
  id: string;
  column: string;
  op: ResultFilterOp;
  value: string | number | boolean;
}

function normalizeComparableValue(
  value: unknown
): string | number | boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return value;
  if (typeof value === 'boolean') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function applyResultFilterOp(
  actual: unknown,
  op: ResultFilterOp,
  expected: ResultFilter['value']
): boolean {
  const a = normalizeComparableValue(actual);
  if (a === null) {
    return false;
  }

  if (op === '~*') {
    const haystack = String(a);
    const pattern = String(expected);
    try {
      const regex = new RegExp(pattern, 'i');
      return regex.test(haystack);
    } catch {
      return false;
    }
  }

  if (op === '==') {
    if (typeof a === 'number' && typeof expected === 'number')
      return a === expected;
    if (typeof a === 'boolean' && typeof expected === 'boolean')
      return a === expected;
    return String(a) === String(expected);
  }

  if (op === '!=') {
    if (typeof a === 'number' && typeof expected === 'number')
      return a !== expected;
    if (typeof a === 'boolean' && typeof expected === 'boolean')
      return a !== expected;
    return String(a) !== String(expected);
  }

  if (typeof a === 'number' && typeof expected === 'number') {
    if (op === '<') return a < expected;
    if (op === '<=') return a <= expected;
    if (op === '>') return a > expected;
    if (op === '>=') return a >= expected;
  }

  const aStr = String(a);
  const eStr = String(expected);
  if (op === '<') return aStr < eStr;
  if (op === '<=') return aStr <= eStr;
  if (op === '>') return aStr > eStr;
  if (op === '>=') return aStr >= eStr;

  return false;
}
