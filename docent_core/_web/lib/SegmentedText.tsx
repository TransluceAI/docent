import React from 'react';
import {
  computeSegmentsFromIntervals,
  TextSpanWithCitations,
} from '@/lib/citationMatch';

const getCitationColors = (
  role: string | undefined,
  isHighlighted: boolean
) => {
  if (!role) {
    return 'bg-yellow-300 dark:bg-yellow-700 text-black dark:text-white';
  }
  switch (role) {
    case 'user':
      return isHighlighted
        ? 'bg-muted-foreground text-background'
        : 'bg-muted-foreground/20';
    case 'assistant':
      return isHighlighted ? 'bg-blue-600 text-white' : 'bg-blue-500/20';
    case 'system':
      return isHighlighted ? 'bg-orange-600 text-white' : 'bg-orange-500/20';
    case 'tool':
      return isHighlighted ? 'bg-green-600 text-white' : 'bg-green-500/20';
    default:
      return isHighlighted ? 'bg-slate-600 text-white' : 'bg-slate-500/20';
  }
};

export interface SegmentedTextProps {
  text: string;
  intervals: TextSpanWithCitations[];
  role?: string;
  highlightedCitationId?: string | null;
  className?: string;
}

export const SegmentedText: React.FC<SegmentedTextProps> = ({
  text,
  intervals,
  role = undefined,
  highlightedCitationId = null,
  className,
}) => {
  const segments = computeSegmentsFromIntervals(text, intervals);

  return (
    <span className={className}>
      {segments.map((seg, i) => {
        if (!seg.citationIds.length)
          return <React.Fragment key={`seg-${i}`}>{seg.text}</React.Fragment>;

        const isHighlighted = highlightedCitationId
          ? seg.citationIds.includes(highlightedCitationId)
          : false;

        // Use role-based colors if role is provided and highlightedCitationId exists,
        // otherwise use simple yellow highlighting for metadata
        const colorClass = getCitationColors(role, isHighlighted);

        return (
          <span
            key={`seg-${i}`}
            className={colorClass}
            data-citation-ids={seg.citationIds.join(',')}
          >
            {seg.text}
          </span>
        );
      })}
    </span>
  );
};
