'use client';

import { Comment } from '@/app/api/labelApi';
import { CommentCard } from './CommentCard';
import { CitationTarget } from '@/app/types/citationTypes';
import { useCallback } from 'react';
import { useCommentPositions } from '@/hooks/use-comment-positions';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { setSelectedCommentId } from '@/app/store/transcriptSlice';
import { CommentTab } from './CommentSidebarHeader';
import { cn } from '@/lib/utils';

interface CommentSidebarContentProps {
  commentsForTranscript: Comment[];
  listModeComments: Comment[];
  scrollContainer?: HTMLElement | null;
  scrollToCitation: (citation: CitationTarget) => void;
  activeTab: CommentTab;
  collectionId?: string;
  agentRunId?: string;
}

export const CommentSidebarContent = ({
  commentsForTranscript,
  listModeComments,
  scrollContainer,
  scrollToCitation,
  activeTab,
  collectionId,
  agentRunId,
}: CommentSidebarContentProps) => {
  const dispatch = useAppDispatch();
  const selectedCommentId = useAppSelector(
    (state) => state.transcript.selectedCommentId
  );

  // Inline mode - positioned comments for current transcript
  // Sort by first citation for positioning
  const sortedComments = [...commentsForTranscript].sort((a, b) => {
    const aTarget = a.citations?.[0]?.target;
    const bTarget = b.citations?.[0]?.target;

    if (
      !aTarget ||
      !bTarget ||
      aTarget.item.item_type !== 'block_content' ||
      bTarget.item.item_type !== 'block_content'
    )
      return 0;

    const aBlock = aTarget.item.block_idx;
    const bBlock = bTarget.item.block_idx;

    if (aBlock !== bBlock) return aBlock - bBlock;

    // Block-level comments (no text_range) sort before text selections
    // Use -1 for null text_range to ensure they come first within a block
    const aStart = aTarget.text_range?.target_start_idx ?? -1;
    const bStart = bTarget.text_range?.target_start_idx ?? -1;

    return aStart - bStart;
  });

  // Use comment positions hook for inline mode
  const positions = useCommentPositions({
    sortedComments,
    scrollContainer: scrollContainer ?? null,
    focusedCommentId: selectedCommentId,
    enabled: activeTab === 'inline',
  });

  // Handler for clicking outside comments to deselect
  // Must be called before any conditional returns to satisfy React hooks rules
  const handleContainerClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      // Only deselect if clicking directly on the container (not on a card)
      if (e.target === e.currentTarget && selectedCommentId) {
        dispatch(setSelectedCommentId(null));
      }
    },
    [dispatch, selectedCommentId]
  );

  // Render List mode - show all comments in a flat list
  if (activeTab === 'list') {
    return (
      <div className="flex flex-col p-3 pb-16">
        {listModeComments.map((comment) => {
          if (!comment.id) return null;

          return (
            <CommentCard
              key={comment.id}
              comment={comment}
              isFocused={selectedCommentId === comment.id}
              onFocus={() => dispatch(setSelectedCommentId(comment.id))}
              onNavigateToCitation={scrollToCitation}
              collectionId={collectionId}
              agentRunId={agentRunId}
            />
          );
        })}
      </div>
    );
  }

  if (sortedComments.length === 0) {
    return (
      <div className="text-xs text-muted-foreground text-center py-8">
        No comments yet
      </div>
    );
  }

  return (
    <div className="relative min-h-full" onClick={handleContainerClick}>
      {sortedComments.map((comment) => {
        if (!comment.id) return null;

        const position = positions.get(comment.id);
        if (position === undefined) return null;

        const isFocused = selectedCommentId === comment.id;

        // Draft cards appear instantly, existing cards slide smoothly
        const isDraft = comment.id === 'draft';

        return (
          <div
            key={comment.id}
            className={cn(
              'absolute left-0 right-0 px-3',
              isFocused ? 'z-10' : 'z-0',
              !isDraft && 'transition-[top] duration-300 ease-out'
            )}
            style={{
              top: `${position}px`,
            }}
          >
            <CommentCard
              comment={comment}
              isFocused={isFocused}
              onFocus={() => dispatch(setSelectedCommentId(comment.id))}
              onNavigateToCitation={scrollToCitation}
              collectionId={collectionId}
              agentRunId={agentRunId}
            />
          </div>
        );
      })}
    </div>
  );
};
