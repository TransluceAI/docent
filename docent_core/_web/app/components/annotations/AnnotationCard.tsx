'use client';

import { Button } from '@/components/ui/button';
import {
  Annotation,
  useUpdateAnnotationMutation,
  useDeleteAnnotationMutation,
  useCreateAnnotationMutation,
} from '@/app/api/labelApi';
import { Edit, MoreVertical, Share, Trash2, UserRoundIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { AnnotationForm } from './AnnotationForm';
import { useState, useRef, useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  setHoveredAnnotationId,
  clearDraftAnnotation,
} from '@/app/store/transcriptSlice';
import SelectionBadges from '@/components/SelectionBadges';
import { CitationTarget } from '@/app/types/citationTypes';
import { useParams } from 'next/navigation';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

interface AnnotationCardProps {
  annotation: Annotation;
  isFocused: boolean;
  onFocus: () => void;
  onNavigateToCitation?: (citation: CitationTarget) => void;
}

export function AnnotationCard({
  annotation,
  isFocused,
  onFocus,
  onNavigateToCitation,
}: AnnotationCardProps) {
  const [updateAnnotation] = useUpdateAnnotationMutation();
  const [deleteAnnotation] = useDeleteAnnotationMutation();
  const [createAnnotation] = useCreateAnnotationMutation();

  const { collection_id: collectionId, agent_run_id: agentRunId } = useParams<{
    collection_id: string;
    agent_run_id: string;
  }>();

  const dispatch = useAppDispatch();
  const draftAnnotation = useAppSelector(
    (state) => state.transcript.draftAnnotation
  );
  const hasWritePermission = useHasCollectionWritePermission();

  // Detect if this is a draft annotation
  const isDraft = annotation.id === 'draft';

  // For drafts, start in edit mode
  const [isEditing, setIsEditing] = useState(isDraft);

  // Track if content is truncated. If so, render a "Show more" button.
  const contentRef = useRef<HTMLDivElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  useEffect(() => {
    if (contentRef.current && !isFocused) {
      setIsTruncated(
        contentRef.current.scrollHeight > contentRef.current.clientHeight
      );
    }
  }, [annotation.content, isFocused]);

  // Use draft content/citations from Redux store if this is a draft
  const effectiveContent =
    isDraft && draftAnnotation ? draftAnnotation.content : annotation.content;

  const effectiveCitations =
    isDraft && draftAnnotation
      ? draftAnnotation.citations
      : annotation.citations;

  // Handler for updating annotation
  const handleUpdateAnnotation = async (content: string) => {
    if (!collectionId || !agentRunId) return;
    await updateAnnotation({
      collectionId,
      annotationId: annotation.id,
      content,
      agentRunId,
    });
  };

  // Handler for deleting annotation
  const handleDeleteAnnotation = async () => {
    if (!collectionId || !agentRunId) return;
    await deleteAnnotation({
      collectionId,
      annotationId: annotation.id,
      agentRunId,
    });
  };

  // Handler for creating draft annotation
  const handleCreateAnnotation = async (content: string) => {
    if (!collectionId || !agentRunId || !draftAnnotation) return;
    try {
      await createAnnotation({
        collectionId,
        annotation: {
          agent_run_id: agentRunId,
          citations: draftAnnotation.citations,
          content,
        },
      });
      dispatch(clearDraftAnnotation());
    } catch (error) {
      console.error('Failed to create annotation:', error);
    }
  };

  // Convert citations to TextSelectionItem format for badges
  // Badges will only show target (no text preview)
  const selectionItems = effectiveCitations
    ? effectiveCitations.map((citation) => ({
        text: '',
        citation: citation.target,
      }))
    : [];

  const handleSave = async (content: string) => {
    if (isDraft) {
      await handleCreateAnnotation(content);
    } else {
      await handleUpdateAnnotation(content);
      setIsEditing(false);
    }
  };

  const handleCancel = () => {
    if (isDraft) {
      dispatch(clearDraftAnnotation());
    } else {
      setIsEditing(false);
    }
  };

  if (isEditing) {
    return (
      <div className="mb-3">
        <AnnotationForm
          initialContent={effectiveContent}
          onSave={handleSave}
          onCancel={handleCancel}
          isEditing={!isDraft}
        />
      </div>
    );
  }

  // Get user initials from email (first letter of email)
  const getInitials = (email: string) => {
    return email.charAt(0).toUpperCase();
  };

  const isAnonymous = (email: string) => {
    return email.startsWith('anonymous_') || !email.includes('@');
  };

  return (
    <div
      data-annotation-card
      className={cn(
        'group border rounded-lg p-3 space-y-2 cursor-pointer transition-all mb-3',
        isFocused
          ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-950'
          : 'border-border bg-background hover:border-indigo-300 hover:bg-accent'
      )}
      onClick={() => {
        onFocus();
        const firstCitation = effectiveCitations?.[0]?.target;
        if (firstCitation && onNavigateToCitation) {
          onNavigateToCitation(firstCitation);
        }
      }}
      onMouseEnter={() =>
        dispatch(setHoveredAnnotationId(annotation.id ?? null))
      }
      onMouseLeave={() => dispatch(setHoveredAnnotationId(null))}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="bg-muted hover:bg-accent border-border h-7 w-7 border rounded-full flex items-center justify-center cursor-pointer ">
            {isAnonymous(annotation.user_email) ? (
              <UserRoundIcon className="text-primary h-4 w-4" />
            ) : (
              <span className="text-xs font-medium text-primary">
                {getInitials(annotation.user_email)}
              </span>
            )}
          </div>
          <div>
            <div className="text-xs text-muted-foreground">
              {' '}
              {annotation.user_email}
            </div>
            {annotation.created_at && (
              <div className="text-[10px] text-muted-foreground">
                {/* DB will save dates in UTC but strips timezone, need to add it back. */}
                {new Date(annotation.created_at + 'Z').toLocaleString(
                  undefined,
                  {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                  }
                )}
              </div>
            )}
          </div>
        </div>

        {/* Action dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="size-7 group-hover:opacity-100 opacity-0 transition-opacity"
              onClick={(e) => e.stopPropagation()}
            >
              <MoreVertical className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {hasWritePermission && (
              <DropdownMenuItem onClick={() => setIsEditing(true)}>
                <Edit className="size-4 mr-2" />
                Edit
              </DropdownMenuItem>
            )}
            <DropdownMenuItem
              onClick={() => {
                const url = new URL(window.location.href);
                url.searchParams.set('annotation_id', annotation.id ?? '');
                navigator.clipboard.writeText(url.toString());
              }}
            >
              <Share className="size-4 mr-2" />
              Copy Link
            </DropdownMenuItem>
            {hasWritePermission && (
              <DropdownMenuItem
                className="text-red-text focus:text-red-text"
                onClick={handleDeleteAnnotation}
              >
                <Trash2 className="size-4 mr-2" />
                Delete
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Citation Badges */}
      {annotation.citations && annotation.citations.length > 0 && (
        <div className="mb-2">
          <SelectionBadges
            selections={selectionItems}
            onNavigate={
              onNavigateToCitation
                ? (item) => {
                    if (item.citation) onNavigateToCitation(item.citation);
                  }
                : undefined
            }
          />
        </div>
      )}

      {/* Comment content */}
      <div>
        <div
          ref={contentRef}
          className={cn(
            'text-sm text-primary whitespace-pre-wrap',
            !isFocused && 'line-clamp-2'
          )}
        >
          {annotation.content}
        </div>
        {!isFocused && isTruncated && (
          <button
            className="text-xs text-muted-foreground hover:text-primary mt-1"
            onClick={(e) => {
              e.stopPropagation();
              onFocus();
            }}
          >
            Show more
          </button>
        )}
      </div>
    </div>
  );
}
