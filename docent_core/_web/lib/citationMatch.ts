import { CitationTarget } from '@/app/types/citationTypes';
import { logErrorWithToast } from './errorUtils';
import { citationTargetToId } from './citationId';

export interface TextSpanWithCitations {
  start: number;
  end: number;
  // Citation/comment highlighting (optional - not all spans are citations)
  citationId?: string;
  commentId?: string;
  // Search highlighting (separate from citations)
  searchMatchId?: string;
  isCurrentSearchMatch?: boolean;
}

// Position without citation ID (used for caching)
interface Position {
  start: number;
  end: number;
}

// Simple capped cache (LRU-ish) keyed by text + pattern signature
// Cache stores positions only, not citation IDs, to avoid stale ID issues when switching results
const MAX_CACHE_ENTRIES = 100;
const patternMatchCache = new Map<string, Position[]>();

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

const CAP_MATCHES_PER_CITATION = 200;

// Find pattern matches (cached at pattern level)
const findMatchesForPattern = (text: string, pattern: string): Position[] => {
  if (!pattern) return [];

  // Create cache key from text hash and pattern
  const textHash = simpleHash(text);
  const cacheKey = `${textHash}::${pattern}`;

  // Check cache first
  const cached = patternMatchCache.get(cacheKey);
  if (cached) return cached;

  // Compute matches
  const positions: Position[] = [];
  const regex = buildWhitespaceFlexibleRegex(pattern);
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m[0].length === 0) {
      regex.lastIndex++;
      continue;
    }
    positions.push({ start: m.index, end: m.index + m[0].length });
    if (positions.length >= CAP_MATCHES_PER_CITATION) break;
  }

  // Cache with simple eviction
  if (patternMatchCache.size >= MAX_CACHE_ENTRIES) {
    const firstKey = patternMatchCache.keys().next().value;
    if (firstKey) {
      patternMatchCache.delete(firstKey);
    }
  }
  patternMatchCache.set(cacheKey, positions);

  return positions;
};

// Compute intervals for an arbitrary pattern without requiring a full citation
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
      citationId: 'pattern-citation',
    });
    if (intervals.length >= CAP_MATCHES_PER_CITATION) break;
  }
  return intervals;
};

/**
 * Compute intervals for citation targets with text ranges
 * Uses the full CitationTarget to generate a proper, lossless citation ID
 *
 * If both target_start_idx and target_end_idx are present, uses them directly.
 * Otherwise, if target_start_idx is present, only highlights the match closest to that position.
 * Otherwise, highlights all matches.
 */
export const computeIntervalsForCitationTargets = (
  text: string,
  targets: CitationTarget[]
): TextSpanWithCitations[] => {
  if (!targets || targets.length === 0) return [];

  const intervals: TextSpanWithCitations[] = [];
  for (const target of targets) {
    const { start_pattern, target_start_idx, target_end_idx } =
      target.text_range || {};

    // Generate proper citation ID from full CitationTarget
    const citationId = citationTargetToId(target);

    // If we have both start and end indices, use them directly without regex
    if (target_start_idx != null && target_end_idx != null) {
      intervals.push({
        start: target_start_idx,
        end: target_end_idx,
        citationId,
      });
      continue;
    }

    // Fall back to pattern matching
    if (!start_pattern) continue;

    // Get positions from cache (pattern-based)
    const positions = findMatchesForPattern(text, start_pattern);
    if (positions.length === 0) continue;

    // If target_start_idx is present, only use the match closest to that position
    if (target_start_idx !== undefined && target_start_idx !== null) {
      // Find the match with start position closest to target_start_idx
      let closestMatch = positions[0];
      let closestDistance = Math.abs(positions[0].start - target_start_idx);

      for (const pos of positions) {
        const distance = Math.abs(pos.start - target_start_idx);
        if (distance < closestDistance) {
          closestDistance = distance;
          closestMatch = pos;
        }
      }

      intervals.push({ ...closestMatch, citationId });
    } else {
      // No target_start_idx - highlight all matches
      const matches = positions.map((pos) => ({ ...pos, citationId }));
      intervals.push(...matches);
    }
  }

  return intervals;
};

export type TextSegment = {
  text: string;
  citationIds: string[];
  commentIds: string[];
  searchMatchIds: string[];
  hasCurrentSearchMatch: boolean;
};

export const computeSegmentsFromIntervals = (
  text: string,
  intervals: TextSpanWithCitations[]
): TextSegment[] => {
  if (!intervals || intervals.length === 0)
    return [
      {
        text,
        citationIds: [],
        commentIds: [],
        searchMatchIds: [],
        hasCurrentSearchMatch: false,
      },
    ];

  // Track opens/closes for each type separately
  const citationOpens: Record<number, string[]> = {};
  const citationCloses: Record<number, string[]> = {};
  const commentOpens: Record<number, string[]> = {};
  const commentCloses: Record<number, string[]> = {};
  const searchOpens: Record<number, string[]> = {};
  const searchCloses: Record<number, string[]> = {};
  const currentSearchOpens: Record<number, boolean> = {};
  const currentSearchCloses: Record<number, boolean> = {};

  intervals.forEach(
    ({
      start,
      end,
      citationId,
      commentId,
      searchMatchId,
      isCurrentSearchMatch,
    }) => {
      if (start >= end) return;

      // Track citation IDs
      if (citationId) {
        if (!citationOpens[start]) citationOpens[start] = [];
        if (!citationCloses[end]) citationCloses[end] = [];
        citationOpens[start].push(citationId);
        citationCloses[end].push(citationId);
      }

      // Track comment IDs
      if (commentId) {
        if (!commentOpens[start]) commentOpens[start] = [];
        if (!commentCloses[end]) commentCloses[end] = [];
        commentOpens[start].push(commentId);
        commentCloses[end].push(commentId);
      }

      // Track search match IDs
      if (searchMatchId) {
        if (!searchOpens[start]) searchOpens[start] = [];
        if (!searchCloses[end]) searchCloses[end] = [];
        searchOpens[start].push(searchMatchId);
        searchCloses[end].push(searchMatchId);

        // Track current search match state
        if (isCurrentSearchMatch) {
          currentSearchOpens[start] = true;
          currentSearchCloses[end] = true;
        }
      }
    }
  );

  const boundaries = new Set<number>([0, text.length]);
  Object.keys(citationOpens).forEach((k) => boundaries.add(Number(k)));
  Object.keys(citationCloses).forEach((k) => boundaries.add(Number(k)));
  Object.keys(commentOpens).forEach((k) => boundaries.add(Number(k)));
  Object.keys(commentCloses).forEach((k) => boundaries.add(Number(k)));
  Object.keys(searchOpens).forEach((k) => boundaries.add(Number(k)));
  Object.keys(searchCloses).forEach((k) => boundaries.add(Number(k)));
  const sorted = Array.from(boundaries).sort((a, b) => a - b);

  const segments: TextSegment[] = [];
  const activeCitations = new Set<string>();
  const activeComments = new Set<string>();
  const activeSearchMatches = new Set<string>();
  let hasCurrentSearchMatch = false;

  for (let i = 0; i < sorted.length - 1; i++) {
    const idx = sorted[i];
    const next = sorted[i + 1];

    // Process closes
    (citationCloses[idx] || []).forEach((id) => activeCitations.delete(id));
    (commentCloses[idx] || []).forEach((id) => activeComments.delete(id));
    (searchCloses[idx] || []).forEach((id) => activeSearchMatches.delete(id));
    if (currentSearchCloses[idx]) hasCurrentSearchMatch = false;

    // Process opens
    (citationOpens[idx] || []).forEach((id) => activeCitations.add(id));
    (commentOpens[idx] || []).forEach((id) => activeComments.add(id));
    (searchOpens[idx] || []).forEach((id) => activeSearchMatches.add(id));
    if (currentSearchOpens[idx]) hasCurrentSearchMatch = true;

    if (next <= idx) continue;
    const slice = text.slice(idx, next);
    if (!slice) continue;

    segments.push({
      text: slice,
      citationIds: Array.from(activeCitations),
      commentIds: Array.from(activeComments),
      searchMatchIds: Array.from(activeSearchMatches),
      hasCurrentSearchMatch,
    });
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

type PrettyPrintMappings = {
  originalToPretty: number[];
  prettyToOriginal: number[];
};

function createPrettyPrintMappings(
  originalText: string,
  prettyText: string
): PrettyPrintMappings {
  const originalToPretty: number[] = new Array(originalText.length);
  const prettyToOriginal: number[] = new Array(prettyText.length);

  let originalPos = 0;
  let prettyPos = 0;

  while (originalPos < originalText.length && prettyPos < prettyText.length) {
    const originalChar = originalText[originalPos];
    const prettyChar = prettyText[prettyPos];

    if (originalChar === prettyChar) {
      originalToPretty[originalPos] = prettyPos;
      prettyToOriginal[prettyPos] = originalPos;
      originalPos++;
      prettyPos++;
    } else if (/\s/.test(originalChar) && /\s/.test(prettyChar)) {
      originalToPretty[originalPos] = prettyPos;
      prettyToOriginal[prettyPos] = originalPos;
      originalPos++;
      prettyPos++;
    } else if (/\s/.test(prettyChar)) {
      prettyToOriginal[prettyPos] = originalPos;
      prettyPos++;
    } else if (/\s/.test(originalChar)) {
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
      originalToPretty[originalPos] = prettyPos;
      prettyToOriginal[prettyPos] = originalPos;
      originalPos++;
      prettyPos++;
    }
  }

  while (originalPos < originalText.length) {
    originalToPretty[originalPos] = prettyText.length;
    originalPos++;
  }
  while (prettyPos < prettyText.length) {
    prettyToOriginal[prettyPos] = originalText.length;
    prettyPos++;
  }

  return { originalToPretty, prettyToOriginal };
}

export function transformCitationIntervalsForPrettyPrintJson(
  intervals: TextSpanWithCitations[],
  originalText: string,
  prettyText: string
) {
  const { originalToPretty } = createPrettyPrintMappings(
    originalText,
    prettyText
  );

  return intervals
    .map((interval) => {
      const newStart = originalToPretty[interval.start] ?? interval.start;
      const newEnd = originalToPretty[interval.end - 1] ?? interval.end;
      return { ...interval, start: newStart, end: newEnd + 1 };
    })
    .filter((interval) => interval.start < interval.end);
}

export function reverseTransformPrettyPrintIndices(
  prettyStartIdx: number,
  prettyEndIdx: number,
  originalText: string,
  prettyText: string
): { startIdx: number; endIdx: number } {
  const { prettyToOriginal } = createPrettyPrintMappings(
    originalText,
    prettyText
  );

  const startIdx = prettyToOriginal[prettyStartIdx] ?? 0;
  const endIdx =
    prettyEndIdx > 0
      ? (prettyToOriginal[prettyEndIdx - 1] ?? originalText.length - 1) + 1
      : 0;

  return { startIdx, endIdx };
}
