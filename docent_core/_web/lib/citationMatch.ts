import { Citation } from '@/app/types/experimentViewerTypes';
import { generateCitationId } from './citationUtils';
import { logErrorWithToast } from './errorUtils';

export interface TextSpanWithCitations {
  start: number;
  end: number;
  citationId: string;
}

// Simple capped cache (LRU-ish) keyed by text + citations signature
const MAX_CACHE_ENTRIES = 100;
const cache = new Map<string, TextSpanWithCitations[]>();

const escapeForRegex = (input: string): string => {
  return input.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
};

const buildWhitespaceFlexibleRegex = (pattern: string): RegExp => {
  let out = '';
  let i = 0;
  while (i < pattern.length) {
    const ch = pattern[i];
    if (/\s/.test(ch)) {
      while (i < pattern.length && /\s/.test(pattern[i])) i++;
      out += '\\s+';
      continue;
    }
    out += escapeForRegex(ch);
    i++;
  }
  return new RegExp(out, 'g');
};

// Build a regex for JSON snippets that:
// - Collapses any explicit whitespace in the pattern to \s+
// - When encountering brackets/braces outside of strings, allows optional whitespace
//   before and after them (\s* [ or ] or { or } \s*) regardless of the original spacing
export const buildWhitespaceFlexibleJsonRegex = (pattern: string): RegExp => {
  let out = '';
  let i = 0;
  let inString = false;
  let escaping = false;

  while (i < pattern.length) {
    const ch = pattern[i];

    if (inString) {
      if (escaping) {
        // Previous char was a backslash inside a string; escape this char literally
        out += escapeForRegex(ch);
        escaping = false;
        i++;
        continue;
      }
      if (ch === '\\') {
        out += '\\\\';
        escaping = true;
        i++;
        continue;
      }
      if (/\s/.test(ch)) {
        while (i < pattern.length && /\s/.test(pattern[i])) i++;
        out += '\\s+';
        continue;
      }
      if (ch === '"') {
        out += '\\"';
        inString = false;
        i++;
        continue;
      }
      out += escapeForRegex(ch);
      i++;
      continue;
    }

    // Not inside a string
    if (/\s/.test(ch)) {
      while (i < pattern.length && /\s/.test(pattern[i])) i++;
      out += '\\s+';
      continue;
    }

    if (ch === '"') {
      out += '\\"';
      inString = true;
      escaping = false;
      i++;
      continue;
    }

    if (ch === '[' || ch === ']' || ch === '{' || ch === '}') {
      out += '\\s*' + escapeForRegex(ch) + '\\s*';
      i++;
      continue;
    }

    out += escapeForRegex(ch);
    i++;
  }

  return new RegExp(out, 'g');
};

const simpleHash = (s: string): string => {
  // Lightweight non-crypto hash
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) | 0;
  }
  return String(h >>> 0);
};

const buildKey = (text: string, citations: Citation[]): string => {
  const textHash = simpleHash(text);
  // Only include fields relevant to matching to keep key stable and small
  const sig = citations
    .map((c) => `${c.transcript_idx}-${c.block_idx}-${c.start_pattern ?? ''}`)
    .join(';');
  return `${textHash}::${sig}`;
};

const CAP_MATCHES_PER_CITATION = 200;

const findMatchesForCitation = (
  text: string,
  citation: Citation
): TextSpanWithCitations[] => {
  const id = generateCitationId(citation);
  const result: TextSpanWithCitations[] = [];
  const { start_pattern } = citation;
  if (!start_pattern) return result;

  const startRe = buildWhitespaceFlexibleRegex(start_pattern);
  let m: RegExpExecArray | null;
  while ((m = startRe.exec(text)) !== null) {
    if (m[0].length === 0) {
      startRe.lastIndex++;
      continue;
    }
    result.push({ start: m.index, end: m.index + m[0].length, citationId: id });
    if (result.length >= CAP_MATCHES_PER_CITATION) break;
  }
  return result;
};

// Compute intervals for an arbitrary pattern without requiring a full Citation
// Useful for UI cases like metadata dialogs where we only need to highlight a pattern
export const computeIntervalsForJsonPattern = (
  text: string,
  pattern: string
): TextSpanWithCitations[] => {
  if (!pattern) return [];
  const intervals: TextSpanWithCitations[] = [];
  const re = buildWhitespaceFlexibleJsonRegex(pattern);
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m[0].length === 0) {
      re.lastIndex++;
      continue;
    }
    intervals.push({
      start: m.index,
      end: m.index + m[0].length,
      citationId: '', // No need to track multiple citations
    });
    if (intervals.length >= CAP_MATCHES_PER_CITATION) break;
  }
  return intervals;
};

export const computeCitationIntervals = (
  text: string,
  citations: Citation[]
): TextSpanWithCitations[] => {
  if (!citations || citations.length === 0) return [];
  const key = buildKey(text, citations);
  const cached = cache.get(key);
  if (cached) return cached;

  const intervals: TextSpanWithCitations[] = [];
  for (const c of citations) {
    const matches = findMatchesForCitation(text, c);
    if (matches.length) intervals.push(...matches);
  }

  // Cache with simple eviction
  if (cache.size >= MAX_CACHE_ENTRIES) {
    const firstKey = cache.keys().next().value;
    if (firstKey) {
      cache.delete(firstKey);
    }
  }
  cache.set(key, intervals);
  return intervals;
};

export type TextSegment = { text: string; citationIds: string[] };

export const computeSegmentsFromIntervals = (
  text: string,
  intervals: TextSpanWithCitations[]
): TextSegment[] => {
  if (!intervals || intervals.length === 0) return [{ text, citationIds: [] }];

  const opens: Record<number, string[]> = {};
  const closes: Record<number, string[]> = {};
  intervals.forEach(({ start, end, citationId }) => {
    if (start >= end) return;
    if (!opens[start]) opens[start] = [];
    if (!closes[end]) closes[end] = [];
    opens[start].push(citationId);
    closes[end].push(citationId);
  });

  const boundaries = new Set<number>([0, text.length]);
  Object.keys(opens).forEach((k) => boundaries.add(Number(k)));
  Object.keys(closes).forEach((k) => boundaries.add(Number(k)));
  const sorted = Array.from(boundaries).sort((a, b) => a - b);

  const segments: TextSegment[] = [];
  const active = new Set<string>();

  for (let i = 0; i < sorted.length - 1; i++) {
    const idx = sorted[i];
    const next = sorted[i + 1];

    (closes[idx] || []).forEach((id) => active.delete(id));
    (opens[idx] || []).forEach((id) => active.add(id));

    if (next <= idx) continue;
    const slice = text.slice(idx, next);
    if (!slice) continue;

    segments.push({ text: slice, citationIds: Array.from(active) });
  }

  return segments;
};

export const sliceIntervals = (
  intervals: TextSpanWithCitations[],
  sliceStart: number,
  sliceEnd: number
): TextSpanWithCitations[] => {
  return intervals
    .filter(
      (interval) => interval.start < sliceEnd && interval.end > sliceStart
    )
    .map((interval) => ({
      ...interval,
      start: Math.max(0, interval.start - sliceStart),
      end: Math.min(interval.end - sliceStart, sliceEnd - sliceStart),
    }))
    .filter((interval) => interval.start < interval.end);
};

// Helper function to create character position mapping between original and pretty-printed JSON
function createPrettyPrintJsonPositionMapping(
  originalText: string,
  prettyText: string
) {
  // Create a mapping from original positions to pretty positions by finding matching content
  const originalToPretty: number[] = new Array(originalText.length);

  let originalPos = 0;
  let prettyPos = 0;

  while (originalPos < originalText.length && prettyPos < prettyText.length) {
    const originalChar = originalText[originalPos];
    const prettyChar = prettyText[prettyPos];

    if (originalChar === prettyChar) {
      // Exact match - record the mapping
      originalToPretty[originalPos] = prettyPos;
      originalPos++;
      prettyPos++;
    } else if (/\s/.test(originalChar) && /\s/.test(prettyChar)) {
      // Both are whitespace - advance both but prefer the pretty position mapping
      originalToPretty[originalPos] = prettyPos;
      originalPos++;
      prettyPos++;
    } else if (/\s/.test(prettyChar)) {
      // Pretty has extra whitespace (common in formatted JSON)
      prettyPos++;
    } else if (/\s/.test(originalChar)) {
      // Original has whitespace that was removed/changed
      originalToPretty[originalPos] = prettyPos;
      originalPos++;
    } else {
      logErrorWithToast(
        'JSON pretty-print resulted in non-matching characters',
        {
          title: 'JSON pretty-print resulted in non-matching characters',
          description: 'Citation ranges may be incorrect.',
          variant: 'destructive',
          context: {
            original_pos: originalPos,
            pretty_pos: prettyPos,
            original_text: originalText,
            pretty_text: prettyText,
          },
        }
      );
    }
  }

  // Fill in any remaining positions
  while (originalPos < originalText.length) {
    originalToPretty[originalPos] = prettyText.length;
    originalPos++;
  }
  while (prettyPos < prettyText.length) {
    prettyPos++;
  }

  return originalToPretty;
}

// Helper function to transform citation intervals from original to pretty-printed positions
export function transformCitationIntervalsForPrettyPrintJson(
  intervals: TextSpanWithCitations[],
  originalText: string,
  prettyText: string
) {
  const originalToPretty = createPrettyPrintJsonPositionMapping(
    originalText,
    prettyText
  );

  return intervals
    .map((interval) => {
      // Map the start and end positions
      const newStart = originalToPretty[interval.start] ?? interval.start;
      const newEnd = originalToPretty[interval.end - 1] ?? interval.end;

      return {
        ...interval,
        start: newStart,
        end: newEnd + 1, // Add 1 back since we mapped end-1
      };
    })
    .filter((interval) => interval.start < interval.end); // Remove invalid intervals
}
