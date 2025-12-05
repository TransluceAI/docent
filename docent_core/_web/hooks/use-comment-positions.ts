import { useLayoutEffect, useEffect, useState, useRef } from 'react';
import { Annotation } from '@/app/api/labelApi';

const CARD_HEIGHT = 150;
const FOCUSED_CARD_HEIGHT = 250;
const OVERLAP_THRESHOLD = 80;

function getCardHeight(annotation: Annotation, isFocused: boolean): number {
  if (annotation.id === 'draft') return FOCUSED_CARD_HEIGHT;
  if (isFocused) return FOCUSED_CARD_HEIGHT;
  return CARD_HEIGHT;
}

function getIdealY(
  annotation: Annotation,
  scrollContainer: HTMLElement
): number | null {
  // Try highlight element first, then fall back to block element
  let targetElement = document.querySelector(
    `[data-annotation-id="${annotation.id}"]`
  ) as HTMLElement;

  const firstTarget = annotation.citations?.[0]?.target;
  if (!targetElement && firstTarget?.item.item_type === 'block_content') {
    const blockIdx = firstTarget.item.block_idx;
    targetElement = document.querySelector(
      `[id$="_b-${blockIdx}"]`
    ) as HTMLElement;
  }

  if (!targetElement) return null;

  const targetRect = targetElement.getBoundingClientRect();
  const containerRect = scrollContainer.getBoundingClientRect();
  const relativeTop =
    targetRect.top - containerRect.top + scrollContainer.scrollTop;

  // Block-level: align top; Text selections: center on highlight
  if (!firstTarget?.text_range) {
    return relativeTop;
  }
  return Math.max(0, relativeTop - CARD_HEIGHT / 2);
}

/** Create a stable key that includes annotation citations, not just IDs */
function getAnnotationsKey(annotations: Annotation[]): string {
  return annotations
    .map((a) => {
      const target = a.citations?.[0]?.target;
      if (!target) return a.id;
      const item = target.item;
      const blockIdx = item.item_type === 'block_content' ? item.block_idx : '';
      const startIdx = target.text_range?.target_start_idx ?? '';
      return `${a.id}:${blockIdx}:${startIdx}`;
    })
    .join(',');
}

function computePositions(
  annotations: Annotation[],
  scrollContainer: HTMLElement,
  focusedAnnotationId: string | null
): Map<string, number> {
  if (annotations.length === 0) return new Map();

  const focusedIdx = focusedAnnotationId
    ? annotations.findIndex((a) => a.id === focusedAnnotationId)
    : -1;

  const positions = new Map<string, number>();

  // If focused, start from focused annotation; otherwise start from first
  const startIdx = focusedIdx >= 0 ? focusedIdx : 0;
  const startAnnotation = annotations[startIdx];
  const startIdealY = getIdealY(startAnnotation, scrollContainer);

  if (startIdealY === null) return positions;

  // Place the starting annotation
  positions.set(startAnnotation.id, startIdealY);

  // Stack downward from start
  let currentY =
    startIdealY + getCardHeight(startAnnotation, focusedIdx === startIdx);
  for (let i = startIdx + 1; i < annotations.length; i++) {
    const annotation = annotations[i];
    const idealY = getIdealY(annotation, scrollContainer);
    if (idealY === null) continue;

    const cardHeight = getCardHeight(annotation, false);
    if (currentY > idealY - OVERLAP_THRESHOLD) {
      positions.set(annotation.id, currentY);
      currentY += cardHeight;
    } else {
      positions.set(annotation.id, idealY);
      currentY = idealY + cardHeight;
    }
  }

  // Stack upward from start (only if we started from a focused annotation)
  if (startIdx > 0) {
    currentY = startIdealY - CARD_HEIGHT;
    for (let i = startIdx - 1; i >= 0; i--) {
      const annotation = annotations[i];
      const idealY = getIdealY(annotation, scrollContainer);
      if (idealY === null) continue;

      const cardHeight = getCardHeight(annotation, false);
      if (currentY < idealY + OVERLAP_THRESHOLD) {
        positions.set(annotation.id, currentY);
        currentY -= cardHeight;
      } else {
        positions.set(annotation.id, idealY);
        currentY = idealY - cardHeight;
      }
    }
  }

  return positions;
}

interface UseCommentPositionsParams {
  sortedAnnotations: Annotation[];
  scrollContainer: HTMLElement | null;
  focusedAnnotationId: string | null;
  enabled: boolean;
}

export function useCommentPositions({
  sortedAnnotations,
  scrollContainer,
  focusedAnnotationId,
  enabled,
}: UseCommentPositionsParams): Map<string, number> {
  const [positions, setPositions] = useState<Map<string, number>>(new Map());

  // Track previous focused ID to detect deselection (someId → null)
  const prevFocusedIdRef = useRef<string | null>(focusedAnnotationId);
  // Track the anchor used for the last position calculation (for resize)
  const lastAnchorRef = useRef<string | null>(focusedAnnotationId);

  // Create a key that changes when annotation locations change (not just IDs)
  const annotationsKey = getAnnotationsKey(sortedAnnotations);

  // Calculate positions after DOM updates using useLayoutEffect
  // This runs synchronously after all DOM mutations but before paint,
  // ensuring highlight elements from sibling components exist
  useLayoutEffect(() => {
    if (!enabled || !scrollContainer) {
      setPositions((prev) => (prev.size === 0 ? prev : new Map()));
      prevFocusedIdRef.current = focusedAnnotationId;
      return;
    }

    // Skip recalculation when deselecting (going from someId → null)
    // This keeps positions stable when clicking away
    const isDeselecting =
      prevFocusedIdRef.current !== null && focusedAnnotationId === null;
    prevFocusedIdRef.current = focusedAnnotationId;

    if (isDeselecting) {
      return;
    }

    // Use the new focused ID as anchor, or keep the last anchor if deselected
    const anchor = focusedAnnotationId ?? lastAnchorRef.current;
    lastAnchorRef.current = anchor;

    const newPositions = computePositions(
      sortedAnnotations,
      scrollContainer,
      anchor
    );

    // Only update if positions actually changed to avoid infinite loops
    setPositions((prev) => {
      if (prev.size !== newPositions.size) return newPositions;
      let hasChanged = false;
      newPositions.forEach((value, key) => {
        if (prev.get(key) !== value) hasChanged = true;
      });
      return hasChanged ? newPositions : prev;
    });
    // sortedAnnotations content is tracked via annotationsKey
    // scrollContainer is a direct dependency - when it transitions from null to valid, effect re-runs
  }, [annotationsKey, focusedAnnotationId, enabled, scrollContainer]);

  // Listen for window resize
  useEffect(() => {
    if (!enabled || !scrollContainer) return;
    const handleResize = () => {
      // Use lastAnchorRef to maintain the same anchor after deselection
      const newPositions = computePositions(
        sortedAnnotations,
        scrollContainer,
        lastAnchorRef.current
      );
      setPositions(newPositions);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, annotationsKey, scrollContainer]);

  return positions;
}
