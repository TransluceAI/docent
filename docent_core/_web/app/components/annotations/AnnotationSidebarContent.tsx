'use client';

import { Annotation } from '@/app/api/labelApi';
import { AnnotationCard } from './AnnotationCard';
import { CitationTarget } from '@/app/types/citationTypes';
import { useCallback } from 'react';
import { useCommentPositions } from '@/hooks/use-comment-positions';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { setSelectedAnnotationId } from '@/app/store/transcriptSlice';
import { AnnotationTab } from './AnnotationSidebarHeader';
import { cn } from '@/lib/utils';

interface AnnotationSidebarContentProps {
  annotationsForTranscript: Annotation[];
  listModeAnnotations: Annotation[];
  scrollContainer?: HTMLElement | null;
  scrollToCitation: (citation: CitationTarget) => void;
  activeTab: AnnotationTab;
}

export const AnnotationSidebarContent = ({
  annotationsForTranscript,
  listModeAnnotations,
  scrollContainer,
  scrollToCitation,
  activeTab,
}: AnnotationSidebarContentProps) => {
  const dispatch = useAppDispatch();
  const selectedAnnotationId = useAppSelector(
    (state) => state.transcript.selectedAnnotationId
  );

  // Inline mode - positioned annotations for current transcript
  // Sort by first citation for positioning
  const sortedAnnotations = [...annotationsForTranscript].sort((a, b) => {
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
    sortedAnnotations,
    scrollContainer: scrollContainer ?? null,
    focusedAnnotationId: selectedAnnotationId,
    enabled: activeTab === 'inline',
  });

  // Handler for clicking outside annotations to deselect
  // Must be called before any conditional returns to satisfy React hooks rules
  const handleContainerClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      // Only deselect if clicking directly on the container (not on a card)
      if (e.target === e.currentTarget && selectedAnnotationId) {
        dispatch(setSelectedAnnotationId(null));
      }
    },
    [dispatch, selectedAnnotationId]
  );

  // Render List mode - show all annotations in a flat list
  if (activeTab === 'list') {
    return (
      <div className="flex flex-col p-3 pb-16">
        {listModeAnnotations.map((annotation) => {
          if (!annotation.id) return null;

          return (
            <AnnotationCard
              key={annotation.id}
              annotation={annotation}
              isFocused={selectedAnnotationId === annotation.id}
              onFocus={() => dispatch(setSelectedAnnotationId(annotation.id))}
              onNavigateToCitation={scrollToCitation}
            />
          );
        })}
      </div>
    );
  }

  if (sortedAnnotations.length === 0) {
    return (
      <div className="text-xs text-muted-foreground text-center py-8">
        No comments yet
      </div>
    );
  }

  return (
    <div className="relative min-h-full" onClick={handleContainerClick}>
      {sortedAnnotations.map((annotation) => {
        if (!annotation.id) return null;

        const position = positions.get(annotation.id);
        if (position === undefined) return null;

        const isFocused = selectedAnnotationId === annotation.id;

        // Draft cards appear instantly, existing cards slide smoothly
        const isDraft = annotation.id === 'draft';

        return (
          <div
            key={annotation.id}
            className={cn(
              'absolute left-0 right-0 px-3',
              isFocused ? 'z-10' : 'z-0',
              !isDraft && 'transition-[top] duration-300 ease-out'
            )}
            style={{
              top: `${position}px`,
            }}
          >
            <AnnotationCard
              annotation={annotation}
              isFocused={isFocused}
              onFocus={() => dispatch(setSelectedAnnotationId(annotation.id))}
              onNavigateToCitation={scrollToCitation}
            />
          </div>
        );
      })}
    </div>
  );
};
