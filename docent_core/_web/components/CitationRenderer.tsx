import { FileTextIcon, Quote } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Citation } from '../app/types/experimentViewerTypes';
import { useAppSelector } from '../app/store/hooks';
import { selectIsCitationHighlighted } from '../lib/citationUtils';
import { useCitationNavigation } from '@/app/dashboard/[collection_id]/rubric/[rubric_id]/NavigateToCitationContext';
import React, { useRef } from 'react';
import { useTextSelection } from '../providers/use-text-selection';

/**
 * Basic markdown patterns for inline formatting
 */
const MARKDOWN_PATTERNS = [
  // Headings (must be at start of line or after newline)
  {
    regex: /(^|\n)#{6}\s+(.*?)(?=\n|$)/g,
    className: 'font-semibold',
    contentIndex: 2,
    element: 'h6',
  },
  {
    regex: /(^|\n)#{5}\s+(.*?)(?=\n|$)/g,
    className: 'font-semibold',
    contentIndex: 2,
    element: 'h5',
  },
  {
    regex: /(^|\n)#{4}\s+(.*?)(?=\n|$)/g,
    className: 'font-semibold',
    contentIndex: 2,
    element: 'h4',
  },
  {
    regex: /(^|\n)#{3}\s+(.*?)(?=\n|$)/g,
    className: 'font-semibold',
    contentIndex: 2,
    element: 'h3',
  },
  {
    regex: /(^|\n)#{2}\s+(.*?)(?=\n|$)/g,
    className: 'font-semibold text-lg pb-1 pt-4',
    contentIndex: 2,
    element: 'h2',
  },
  {
    regex: /(^|\n)#{1}\s+(.*?)(?=\n|$)/g,
    className: 'font-semibold text-xl pb-1 pt-4',
    contentIndex: 2,
    element: 'h1',
  },
  // Inline formatting
  {
    regex: /\*\*(.*?)\*\*/g,
    className: 'font-semibold',
    contentIndex: 1,
    element: 'strong',
  },
  { regex: /\*(.*?)\*/g, className: 'italic', contentIndex: 1, element: 'em' },
  {
    regex: /`(.*?)`/g,
    className:
      'text-sm bg-secondary text-primary py-0.5 px-1 rounded font-mono',
    contentIndex: 1,
    element: 'code',
  },
] as const;

/**
 * Unified text processor that handles markdown formatting and citations in a single pass
 * This eliminates the need for multiple nested spans and ReactMarkdown overhead
 */
function processTextWithMarkdownAndCitations(
  text: string,
  citations: Citation[],
  onCitationClick: (citation: Citation) => void,
  keyBase: string
): JSX.Element[] {
  if (!text) return [];

  const sortedCitations = [...citations].sort(
    (a, b) => a.start_idx - b.start_idx
  );
  const elements: JSX.Element[] = [];
  let currentIndex = 0;

  // Process each citation and the text segments around them
  sortedCitations.forEach((citation, citationIdx) => {
    // Process text before citation
    if (citation.start_idx > currentIndex) {
      const textSegment = text.slice(currentIndex, citation.start_idx);
      elements.push(
        ...processMarkdownText(textSegment, `${keyBase}-pre-${citationIdx}`)
      );
    }

    // Add citation button
    const citationText = text.slice(citation.start_idx, citation.end_idx);
    elements.push(
      <CitationButton
        key={`${keyBase}-citation-${citationIdx}`}
        citation={citation}
        text={citationText}
        onClick={onCitationClick}
      />
    );

    currentIndex = citation.end_idx;
  });

  // Process remaining text after last citation
  if (currentIndex < text.length) {
    const remainingText = text.slice(currentIndex);
    elements.push(...processMarkdownText(remainingText, `${keyBase}-post`));
  }

  return elements;
}

/**
 * Process text with basic markdown formatting without creating excessive nesting
 */
function processMarkdownText(text: string, keyBase: string): JSX.Element[] {
  if (!text) return [];

  // Find all markdown matches across all patterns
  const matches: Array<{
    start: number;
    end: number;
    content: string;
    className: string;
    fullMatch: string;
    isHeading?: boolean;
    element?: string;
  }> = [];

  MARKDOWN_PATTERNS.forEach((pattern) => {
    const regex = new RegExp(pattern.regex);
    let match;
    while ((match = regex.exec(text)) !== null) {
      const contentIndex = pattern.contentIndex || 1;
      const content = match[contentIndex];

      // For headings, we need to handle the newline prefix
      let adjustedStart = match.index;
      const adjustedEnd = match.index + match[0].length;

      if (pattern.contentIndex === 2 && match[1] === '\n') {
        // Skip the newline at the start for headings
        adjustedStart += 1;
      }

      matches.push({
        start: adjustedStart,
        end: adjustedEnd,
        content,
        className: pattern.className,
        fullMatch: match[0],
        isHeading: pattern.contentIndex === 2,
        element: pattern.element,
      });
    }
  });

  // Sort matches by start position
  matches.sort((a, b) => a.start - b.start);

  // Remove overlapping matches (keep first one)
  const cleanMatches = matches.filter((match, idx) => {
    return !matches
      .slice(0, idx)
      .some(
        (prevMatch) =>
          match.start < prevMatch.end && match.end > prevMatch.start
      );
  });

  if (cleanMatches.length === 0) {
    // No markdown, return text as-is with whitespace preservation
    return [
      <span key={keyBase} className="whitespace-pre-wrap">
        {text}
      </span>,
    ];
  }

  const elements: JSX.Element[] = [];
  let currentPos = 0;

  cleanMatches.forEach((match, idx) => {
    // Add text before markdown
    if (match.start > currentPos) {
      let beforeText = text.slice(currentPos, match.start);

      // Trim whitespace around block elements only
      const prevMatch = idx > 0 ? cleanMatches[idx - 1] : null;

      // Trim start if previous element was a heading
      if (prevMatch?.isHeading) {
        beforeText = beforeText.replace(/^\s+/, '');
      }

      // Trim end if current element is a heading
      if (match.isHeading) {
        beforeText = beforeText.replace(/\s+$/, '');
      }

      if (beforeText) {
        elements.push(
          <span key={`${keyBase}-text-${idx}`} className="whitespace-pre-wrap">
            {beforeText}
          </span>
        );
      }
    }

    // Add formatted text with proper semantic elements
    if (match.element) {
      const ElementTag = match.element as keyof JSX.IntrinsicElements;
      elements.push(
        React.createElement(
          ElementTag,
          {
            key: `${keyBase}-md-${idx}`,
            className: cn(match.className, {
              'whitespace-pre-wrap': !match.isHeading,
            }),
          },
          match.content
        )
      );
    } else {
      elements.push(
        <span
          key={`${keyBase}-md-${idx}`}
          className={`${match.className} whitespace-pre-wrap`}
        >
          {match.content}
        </span>
      );
    }

    currentPos = match.end;
  });

  // Add remaining text
  if (currentPos < text.length) {
    let remainingText = text.slice(currentPos);

    // Trim start if previous element was a heading
    const lastMatch = cleanMatches[cleanMatches.length - 1];
    if (lastMatch?.isHeading) {
      remainingText = remainingText.replace(/^\s+/, '');
    }

    if (remainingText) {
      elements.push(
        <span key={`${keyBase}-end`} className="whitespace-pre-wrap">
          {remainingText}
        </span>
      );
    }
  }

  return elements;
}

/**
 * Individual citation span - clickable text with highlighting support
 * Used internally by CitationRenderer and TextWithCitations
 */
export const CitationButton: React.FC<{
  citation: Citation;
  text: string;
  onClick: (citation: Citation) => void;
}> = ({ citation, text, onClick }) => {
  const isHighlighted = useAppSelector((state) =>
    selectIsCitationHighlighted(state, citation)
  );
  // Server-side validation ensures that any citation with start_pattern is valid
  const isMetadataCitation = citation.metadata_key != null;
  const hasMatches = Boolean(citation.start_pattern);

  return (
    <button
      className={cn(
        'px-0.5 py-0.25 rounded font-medium',
        isHighlighted
          ? 'bg-indigo-500 text-white'
          : 'bg-indigo-muted text-primary hover:bg-indigo-muted/50'
      )}
      onClick={(e) => {
        // Prevent the card click from triggering
        e.stopPropagation();
        onClick(citation);
      }}
    >
      <span className="inline-flex items-center">
        {text}
        {isMetadataCitation && (
          <FileTextIcon
            className={cn(
              'w-3 h-3 ml-0.5 inline',
              isHighlighted ? 'text-white' : 'text-indigo-400'
            )}
          />
        )}
        {hasMatches && !isMetadataCitation && (
          <Quote
            className={cn(
              'w-3 h-3 ml-0.5 inline',
              isHighlighted ? 'text-white' : 'text-indigo-400'
            )}
          />
        )}
      </span>
    </button>
  );
};

/**
 * TextWithCitations - Renders text with embedded clickable citations
 */
export type NavigateToCitation = (args: {
  citation: Citation;
  source?: string;
}) => void;

interface TextWithCitationsProps {
  text: string;
  citations: Citation[];
  setSelectedText?: (text: string) => void;
}

export const TextWithCitations: React.FC<TextWithCitationsProps> = ({
  text,
  citations,
}) => {
  const citationNav = useCitationNavigation();

  const containerRef = useRef<HTMLSpanElement | null>(null);
  useTextSelection({ containerRef });

  const sortedCitations = [...citations].sort(
    (a, b) => a.start_idx - b.start_idx
  );
  const parts: JSX.Element[] = [];
  let lastIndex = 0;
  let lastWasCitation = false;

  const handleCitationClick = (citation: Citation) => {
    if (citationNav?.navigateToCitation) {
      citationNav.navigateToCitation({ citation });
    }
  };

  sortedCitations.forEach((citation, i) => {
    // Add text before citation
    if (citation.start_idx > lastIndex) {
      parts.push(
        <span key={`text-${i}`} className="whitespace-pre-wrap">
          {text.slice(lastIndex, citation.start_idx)}
        </span>
      );
      lastWasCitation = false;
    }

    // Add citation span
    const citedText = text.slice(citation.start_idx, citation.end_idx);
    if (citation.start_idx === lastIndex && lastWasCitation) {
      parts.push(
        <span key={`sep-${i}`} className="whitespace-pre-wrap">
          {' '}
        </span>
      );
    }
    parts.push(
      <CitationButton
        key={`citation-${i}`}
        citation={citation}
        text={citedText}
        onClick={handleCitationClick}
      />
    );

    lastIndex = citation.end_idx;
    lastWasCitation = true;
  });

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(
      <span key="text-end" className="whitespace-pre-wrap">
        {text.slice(lastIndex)}
      </span>
    );
  }

  return (
    <span
      ref={containerRef}
      className="relative whitespace-pre-wrap"
      tabIndex={0}
    >
      {parts}
    </span>
  );
};

/**
 * MarkdownWithCitations - Renders text with both markdown formatting and interactive citations
 * Uses unified rendering to eliminate excessive span nesting
 */
interface MarkdownWithCitationsProps {
  text: string;
  citations: Citation[];
}

export const MarkdownWithCitations: React.FC<MarkdownWithCitationsProps> = ({
  text,
  citations,
}) => {
  const citationNav = useCitationNavigation();

  const handleCitationClick = (citation: Citation) => {
    if (citationNav?.navigateToCitation) {
      citationNav.navigateToCitation({ citation });
    }
  };

  const elements = processTextWithMarkdownAndCitations(
    text,
    citations,
    handleCitationClick,
    'md-citations'
  );

  return <>{elements}</>;
};
