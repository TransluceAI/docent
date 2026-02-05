import React from 'react';
import {
  computeSegmentsFromIntervals,
  TextSpanWithCitations,
} from '@/lib/citationMatch';
import { cn } from '@/lib/utils';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  setSelectedCommentId,
  setCommentSidebarCollapsed,
} from '@/app/store/transcriptSlice';

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

const getCommentColors = (
  isHighlighted: boolean,
  isHovered: boolean,
  isSelected: boolean
) => {
  // Comments use purple color scheme to distinguish from regular citations
  if (isHighlighted) {
    return 'bg-purple-600 text-white';
  }
  if (isHovered) {
    return 'bg-purple-400/40 border-b-2 border-purple-500/50';
  }
  if (isSelected) {
    return 'bg-purple-400/40 border-b-2 border-purple-500/50';
  }
  return 'bg-purple-500/20';
};

const getSearchColors = (isCurrentMatch: boolean) => {
  if (isCurrentMatch) {
    return 'bg-orange-400 dark:bg-orange-500 text-black dark:text-black';
  }
  return 'bg-yellow-200 dark:bg-yellow-500/50';
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
  const dispatch = useAppDispatch();

  const hoveredCommentId = useAppSelector(
    (state) => state.transcript.hoveredCommentId
  );

  const selectedCommentId = useAppSelector(
    (state) => state.transcript.selectedCommentId
  );

  const handleCommentClick = (commentId: string) => {
    dispatch(setSelectedCommentId(commentId));
    dispatch(setCommentSidebarCollapsed(false));
  };

  const segments = computeSegmentsFromIntervals(text, intervals);

  return (
    <span className={className}>
      {segments.map((seg, i) => {
        // Check if segment has any highlighting
        const hasHighlighting =
          seg.citationIds.length > 0 ||
          seg.commentIds.length > 0 ||
          seg.searchMatchIds.length > 0;

        if (!hasHighlighting)
          return <React.Fragment key={`seg-${i}`}>{seg.text}</React.Fragment>;

        // Use enriched segment data directly
        const isSearchMatch = seg.searchMatchIds.length > 0;
        const isCurrentSearchMatch = seg.hasCurrentSearchMatch;
        const isComment = seg.commentIds.length > 0;

        const isHighlighted = highlightedCitationId
          ? seg.citationIds.includes(highlightedCitationId)
          : false;

        const isHovered = hoveredCommentId
          ? seg.commentIds.includes(hoveredCommentId)
          : false;

        const isSelected = selectedCommentId
          ? seg.commentIds.includes(selectedCommentId)
          : false;

        // Priority: currentSearchMatch > searchMatch > comment > citation
        let colorClass: string;
        if (isSearchMatch) {
          colorClass = getSearchColors(isCurrentSearchMatch);
        } else if (isComment) {
          colorClass = getCommentColors(isHighlighted, isHovered, isSelected);
        } else if (highlightedCitationId && !isHighlighted) {
          // When a citation is selected, don't show muted highlights for other citations
          return <React.Fragment key={`seg-${i}`}>{seg.text}</React.Fragment>;
        } else {
          colorClass = getCitationColors(role, isHighlighted);
        }

        // Get the first comment ID for click handling
        const firstCommentId = seg.commentIds[0];

        return (
          <span
            key={`seg-${i}`}
            className={cn(
              colorClass,
              isComment &&
                !isSearchMatch &&
                'cursor-pointer transition-all duration-150',
              isComment &&
                !isSearchMatch &&
                'hover:border-purple-500/50 hover:border-b-2'
            )}
            data-citation-ids={
              seg.citationIds.length > 0 ? seg.citationIds.join(',') : undefined
            }
            data-comment-id={firstCommentId}
            data-search-match-ids={
              seg.searchMatchIds.length > 0
                ? seg.searchMatchIds.join(' ')
                : undefined
            }
            data-current-search-match={
              isCurrentSearchMatch ? 'true' : undefined
            }
            onClick={
              isComment && firstCommentId && !isSearchMatch
                ? () => handleCommentClick(firstCommentId)
                : undefined
            }
          >
            {seg.text}
          </span>
        );
      })}
    </span>
  );
};
