import React, { useMemo, useRef } from 'react';
import jsonStringFormatter from 'json-string-formatter';
import { ChatMessage, Content, ToolCall } from '@/app/types/transcriptTypes';
import { cn } from '@/lib/utils';
import { Comment } from '@/app/api/labelApi';
import {
  CitationTarget,
  CitationTargetTextRange,
  TranscriptBlockContentItem,
} from '@/app/types/citationTypes';
import {
  computeIntervalsForCitationTargets,
  TextSpanWithCitations,
  transformCitationIntervalsForPrettyPrintJson,
} from '@/lib/citationMatch';
import { useAppSelector } from '@/app/store/hooks';
import { citationTargetToId } from '@/lib/citationId';
import { SegmentedText } from '@/lib/SegmentedText';
import { MetadataPopover } from '@/components/metadata/MetadataPopover';
import { MetadataBlock } from '@/components/metadata/MetadataBlock';
import { useCitationNavigation } from '@/providers/CitationNavigationProvider';
import { MessageSquarePlus } from 'lucide-react';
import { MessageTelemetryDialog } from './MessageTelemetryDialog';

function stringify(x: any): string {
  if (typeof x === 'string') return x;
  return JSON.stringify(x);
}

export const formatToolCallData = (tool: ToolCall) => {
  if (tool.type === 'custom') {
    return tool.input || '';
  } else {
    const args = tool.arguments;
    if (!args) return '';
    if (typeof args === 'string') return args;
    return Object.entries(args)
      .map(([k, v]) => `${k}=${stringify(v)}`)
      .join(', ');
  }
};

export const getToolCallDisplayContent = (tool: ToolCall) =>
  tool.view
    ? tool.view.content
    : `${tool.function}(${formatToolCallData(tool)})`;

export function getReasoningContent(
  content: string | Content[]
): string | null {
  if (typeof content === 'string') {
    return null;
  }
  // Find the first reasoning content item
  const reasoningItem = content.find(
    (item): item is Content & { reasoning: string } =>
      item.type === 'reasoning' && typeof item.reasoning === 'string'
  );
  return reasoningItem ? reasoningItem.reasoning : null;
}

type ContentIndices = {
  reasoningIdx: number | null;
  mainTextIdx: number;
};

export function getContentIndices(content: string | Content[]): ContentIndices {
  if (typeof content === 'string') {
    return { reasoningIdx: null, mainTextIdx: 0 };
  }

  let reasoningIdx: number | null = null;
  let mainTextIdx = 0;

  for (let i = 0; i < content.length; i++) {
    const item = content[i];
    if (item.type === 'reasoning' && reasoningIdx === null) {
      reasoningIdx = i;
    } else if (item.type === 'text') {
      mainTextIdx = i;
      break;
    }
  }

  return { reasoningIdx, mainTextIdx };
}

// Helper function to detect if content contains JSON
export const hasJsonContent = (text: string): boolean => {
  try {
    const trimmed = text.trim();
    // Check if it looks like JSON (starts with { or [)
    if (
      (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
      (trimmed.startsWith('[') && trimmed.endsWith(']'))
    ) {
      JSON.parse(trimmed);
      return true;
    }
  } catch (e) {
    // If parsing fails, it's not valid JSON
  }
  return false;
};

// Extract main text content from message
export function getMainTextContent(message: ChatMessage): string {
  if (typeof message.content === 'string') {
    return message.content;
  }
  return message.content
    .filter(
      (item): item is Content & { text: string } =>
        item.type === 'text' && typeof item.text === 'string'
    )
    .map((item) => item.text)
    .join('\n');
}

const getRoleStyle = (role: string, isHighlighted: boolean) => {
  const transitionClasses = 'transition-colors duration-500 ease-out';

  // Use specific color classes instead of dynamic ones
  const getColorClasses = (role: string, highlighted: boolean) => {
    switch (role) {
      case 'user':
        return highlighted
          ? 'bg-muted-foreground/40 border-l-2 border-muted-foreground'
          : 'bg-gray-50 dark:bg-gray-900/50 border-l-2 border-gray-300 dark:border-gray-700';
      case 'assistant':
        return highlighted
          ? 'bg-blue-500/40 border-l-2 border-blue-500'
          : 'bg-blue-50 dark:bg-blue-950/30 border-l-2 border-blue-300 dark:border-blue-700';
      case 'system':
        return highlighted
          ? 'bg-orange-500/40 border-l-2 border-orange-500'
          : 'bg-orange-50 dark:bg-orange-950/30 border-l-2 border-orange-300 dark:border-orange-700';
      case 'tool':
        return highlighted
          ? 'bg-green-500/40 border-l-2 border-green-500'
          : 'bg-green-50 dark:bg-green-950/30 border-l-2 border-green-300 dark:border-green-700';
      default:
        return highlighted
          ? 'bg-slate-500/40 border-l-2 border-slate-500'
          : 'bg-gray-50 dark:bg-gray-900/50 border-l-2 border-gray-300 dark:border-gray-700';
    }
  };

  const colorClasses = getColorClasses(role, isHighlighted);
  return `${colorClasses} ${transitionClasses}`;
};

interface MessageBoxProps {
  message: ChatMessage;
  index: number;
  blockId?: string;
  isHighlighted: boolean;
  citedTargets: CitationTarget[];
  comments: Comment[];
  prettyPrintJsonMessages: Set<number>;
  setPrettyPrintJsonMessages: React.Dispatch<React.SetStateAction<Set<number>>>;
  dataContext: TranscriptBlockContentItem;
  hasTelemetry?: boolean;
  metadataDialogControl?: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    citedKey?: string;
    citedTextRange?: CitationTargetTextRange;
  };
  onAddMetadataComment?: (key: string) => void;
  onAddBlockComment?: () => void;
  onBlockClick?: () => void;
  searchMatches?: Array<{
    start: number;
    end: number;
    contentType: 'main' | 'toolCall' | 'reasoning';
    toolCallIndex?: number;
    localIndex: number;
  }>;
  currentSearchMatchIndex?: number | null;
}

export function MessageBox({
  message,
  index,
  blockId: id,
  isHighlighted,
  citedTargets,
  comments,
  prettyPrintJsonMessages,
  dataContext,
  setPrettyPrintJsonMessages,
  hasTelemetry,
  metadataDialogControl,
  onAddMetadataComment,
  onAddBlockComment,
  onBlockClick,
  searchMatches = [],
  currentSearchMatchIndex = null,
}: MessageBoxProps) {
  const containerRef = useRef<HTMLSpanElement | null>(null);
  const citationNav = useCitationNavigation();
  const selectedConversationCitation = citationNav?.selectedCitation ?? null;

  const highlightedCitationId = selectedConversationCitation
    ? citationTargetToId(selectedConversationCitation)
    : null;

  // Helper function to detect and pretty-print JSON
  const prettyPrintJson = (text: string): string => {
    if (!prettyPrintJsonMessages.has(index)) {
      return text;
    }

    // Try to parse as JSON and pretty-print if successful
    try {
      const trimmed = text.trim();
      // Check if it looks like JSON (starts with { or [)
      if (
        (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
        (trimmed.startsWith('[') && trimmed.endsWith(']'))
      ) {
        const prettyText = jsonStringFormatter.format(trimmed);
        if (prettyText) {
          return prettyText;
        }
      }
    } catch (e) {
      // If parsing fails, return original text
    }
    return text;
  };

  // Extract content texts
  const mainTextContent = useMemo(() => getMainTextContent(message), [message]);
  const reasoningContent = useMemo(
    () => getReasoningContent(message.content),
    [message.content]
  );

  // Compute the content indices for citation context
  const contentIndices = useMemo(
    () => getContentIndices(message.content),
    [message.content]
  );

  /**
   * Compute citation intervals for a content section.
   * Includes citations that either:
   * - Have matching content_idx
   * - Have no content_idx (legacy pattern-based citations)
   */
  const getIntervalsForContentIdx = (
    contentIdx: number,
    contentText: string,
    contentType: 'main' | 'reasoning' = 'main'
  ): TextSpanWithCitations[] => {
    // Filter citations: include those with matching content_idx OR no content_idx
    const relevantTargets = citedTargets.filter((target) => {
      if (target.item.item_type !== 'block_content') return false;
      if (target.text_range === null) return false;
      const item = target.item as TranscriptBlockContentItem;
      // Include if content_idx matches OR if no content_idx (legacy)
      return item.content_idx === contentIdx || item.content_idx == null;
    });

    const regularIntervals = computeIntervalsForCitationTargets(
      contentText,
      relevantTargets
    );

    // Also handle comments
    const commentIntervals = comments.flatMap((cmt) => {
      if (!cmt.citations || cmt.citations.length === 0) return [];
      const matchingTargets = cmt.citations
        .map((citation) => citation.target)
        .filter((target) => {
          if (target.item.item_type !== 'block_content') return false;
          const item = target.item as TranscriptBlockContentItem;
          return item.content_idx === contentIdx;
        });
      if (matchingTargets.length === 0) return [];
      const intervals = computeIntervalsForCitationTargets(
        contentText,
        matchingTargets
      );
      return intervals.map((interval) => ({
        ...interval,
        isComment: true,
        commentId: cmt.id,
      }));
    });

    // Add search match intervals for the specified content type
    const searchIntervals: TextSpanWithCitations[] = [];
    searchMatches.forEach((match, idx) => {
      if (match.contentType !== contentType) return;
      searchIntervals.push({
        start: match.start,
        end: match.end,
        searchMatchId: `${contentType}-${match.localIndex}`,
        isCurrentSearchMatch: idx === currentSearchMatchIndex,
      });
    });

    return [...regularIntervals, ...commentIntervals, ...searchIntervals];
  };

  /**
   * Compute citation intervals for tool calls (pattern-based only, no content_idx).
   */
  const getIntervalsForToolCall = (
    toolCallText: string,
    toolCallIndex: number
  ): TextSpanWithCitations[] => {
    // Only include citations without content_idx (pattern-based)
    const relevantTargets = citedTargets.filter((target) => {
      if (target.item.item_type !== 'block_content') return false;
      if (target.text_range === null) return false;
      const item = target.item as TranscriptBlockContentItem;
      return item.content_idx == null;
    });

    const regularIntervals = computeIntervalsForCitationTargets(
      toolCallText,
      relevantTargets
    );

    // Also handle comments without content_idx
    const commentIntervals = comments.flatMap((cmt) => {
      if (!cmt.citations || cmt.citations.length === 0) return [];
      const matchingTargets = cmt.citations
        .map((citation) => citation.target)
        .filter((target) => {
          if (target.item.item_type !== 'block_content') return false;
          const item = target.item as TranscriptBlockContentItem;
          return item.content_idx == null;
        });
      if (matchingTargets.length === 0) return [];
      const intervals = computeIntervalsForCitationTargets(
        toolCallText,
        matchingTargets
      );
      return intervals.map((interval) => ({
        ...interval,
        isComment: true,
        commentId: cmt.id,
      }));
    });

    // Add search match intervals for this specific tool call
    const searchIntervals: TextSpanWithCitations[] = [];
    searchMatches.forEach((match, idx) => {
      if (
        match.contentType !== 'toolCall' ||
        match.toolCallIndex !== toolCallIndex
      )
        return;
      searchIntervals.push({
        start: match.start,
        end: match.end,
        searchMatchId: `tc${toolCallIndex}-${match.localIndex}`,
        isCurrentSearchMatch: idx === currentSearchMatchIndex,
      });
    });

    return [...regularIntervals, ...commentIntervals, ...searchIntervals];
  };

  const hoveredCommentId = useAppSelector(
    (state) => state.transcript.hoveredCommentId
  );

  const isHovered = comments.some(
    (cmt) =>
      cmt.id === hoveredCommentId &&
      cmt.citations?.some((citation) => citation.target.text_range === null)
  );

  //********************
  // Component Helpers *
  //********************

  const renderMainMessageContent = () => {
    const isPrettyPrinted = prettyPrintJsonMessages.has(index);
    const contentString = isPrettyPrinted
      ? prettyPrintJson(mainTextContent)
      : mainTextContent;
    const isTransformed = isPrettyPrinted && mainTextContent !== contentString;

    const intervals = getIntervalsForContentIdx(
      contentIndices.mainTextIdx,
      mainTextContent,
      'main'
    );

    // If content was pretty-printed, transform the citation intervals to match the new positions
    const citationIntervals = isTransformed
      ? transformCitationIntervalsForPrettyPrintJson(
          intervals,
          mainTextContent,
          contentString
        )
      : intervals;

    const mainContext: TranscriptBlockContentItem = {
      ...dataContext,
      content_idx: contentIndices.mainTextIdx,
    };

    return (
      <div
        data-citation-context={JSON.stringify(mainContext)}
        data-original-text={isTransformed ? mainTextContent : undefined}
      >
        <SegmentedText
          text={contentString}
          intervals={citationIntervals}
          role={message.role}
          highlightedCitationId={highlightedCitationId ?? null}
        />
      </div>
    );
  };

  // Helper to render tool-specific information
  const renderToolInfo = () => {
    if (message.role === 'tool') {
      return (
        <div className="mt-1 text-[10px] text-muted-foreground">
          {message.tool_call_id && (
            <span>Tool Call ID: {message.tool_call_id}</span>
          )}
          {message.function && (
            <span className="ml-2">Function: {message.function}</span>
          )}
          {message.error && (
            <div className="mt-1 text-destructive">
              Error: {message.error.message}
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  // Helper to render tool calls with citation highlighting for assistant messages
  const renderToolCalls = () => {
    if (message.role !== 'assistant' || !message.tool_calls) return null;

    return message.tool_calls.map((toolCall, i) => {
      const toolCallContent = toolCall.view
        ? toolCall.view.content
        : `${toolCall.function}(${formatToolCallData(toolCall)})`;

      const intervals = getIntervalsForToolCall(toolCallContent, i);

      return (
        <div
          key={i}
          className="mt-1 p-1.5 bg-secondary/85 rounded text-xs break-all whitespace-pre-wrap font-mono"
        >
          <div className="text-[10px] text-muted-foreground mb-0.5">
            Tool Call ID: {toolCall.id}
          </div>
          <SegmentedText
            text={toolCallContent}
            intervals={intervals}
            role={message.role}
            highlightedCitationId={highlightedCitationId ?? null}
          />
        </div>
      );
    });
  };

  const renderReasoningBlock = () => {
    if (!reasoningContent || contentIndices.reasoningIdx === null) return null;

    const intervals = getIntervalsForContentIdx(
      contentIndices.reasoningIdx,
      reasoningContent,
      'reasoning'
    );

    const reasoningContext: TranscriptBlockContentItem = {
      ...dataContext,
      content_idx: contentIndices.reasoningIdx,
    };

    return (
      <div
        data-citation-context={JSON.stringify(reasoningContext)}
        className="mb-2 px-2 py-2 bg-muted border-l-2 border-border text-xs text-primary italic whitespace-pre-wrap [overflow-wrap:anywhere] max-w-full overflow-x-auto font-mono rounded custom-scrollbar"
      >
        <SegmentedText
          text={reasoningContent}
          intervals={intervals}
          role={message.role}
          highlightedCitationId={highlightedCitationId ?? null}
        />
      </div>
    );
  };

  const handlePrettyPrintJsonChange = (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    setPrettyPrintJsonMessages((prev) => {
      const newSet = new Set(prev);
      if (e.target.checked) {
        newSet.add(index);
      } else {
        newSet.delete(index);
      }
      return newSet;
    });
  };

  const collectionId = dataContext.collection_id;
  const transcriptId = dataContext.transcript_id;
  const messageId = message.id;

  const canShowTelemetryLink =
    collectionId.length > 0 &&
    transcriptId.length > 0 &&
    typeof messageId === 'string' &&
    messageId.length > 0 &&
    hasTelemetry === true;

  return (
    <div className="mb-1 agent-run-viewer">
      <div
        id={id}
        className={cn(
          'group p-2 rounded-md text-sm',
          !isHighlighted && 'transition-all duration-1500',
          getRoleStyle(message.role, isHighlighted)
        )}
      >
        <div className="text-[10px] text-muted-foreground flex justify-between mb-1">
          <span className="flex items-center gap-1 select-none">
            <span
              onClick={onBlockClick}
              className={cn(
                onBlockClick &&
                  'cursor-pointer hover:text-primary hover:underline',
                isHovered && 'text-primary underline'
              )}
            >
              Block {index} |{' '}
              {message.role.charAt(0).toUpperCase() + message.role.slice(1)}
            </span>
            {onAddBlockComment && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onAddBlockComment();
                }}
                className="p-0.5 rounded hover:bg-muted text-muted-foreground hover:text-primary transition-colors opacity-0 group-hover:opacity-100"
                title="Add comment to block"
              >
                <MessageSquarePlus className="h-3 w-3" />
              </button>
            )}
          </span>
          <div className="flex items-center gap-2">
            {canShowTelemetryLink && (
              <MessageTelemetryDialog
                collectionId={collectionId as string}
                transcriptId={transcriptId as string}
                messageId={messageId as string}
              />
            )}
            {hasJsonContent(mainTextContent) && (
              <label className="flex items-center space-x-1 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={prettyPrintJsonMessages.has(index)}
                  onChange={handlePrettyPrintJsonChange}
                  className="h-3 w-3 rounded border-border"
                />
                <span>Pretty JSON</span>
              </label>
            )}
            {message.metadata && Object.keys(message.metadata).length > 0 && (
              <MetadataPopover.Root
                open={metadataDialogControl?.open}
                onOpenChange={metadataDialogControl?.onOpenChange || (() => {})}
              >
                <MetadataPopover.DefaultTrigger />
                <MetadataPopover.Content
                  title={`Message Metadata - Block ${index}`}
                >
                  <MetadataPopover.Body metadata={message.metadata}>
                    {(md) => (
                      <MetadataBlock
                        metadata={md}
                        showSearchControls={true}
                        citedKey={metadataDialogControl?.citedKey}
                        textRange={metadataDialogControl?.citedTextRange}
                        onAddComment={onAddMetadataComment}
                      />
                    )}
                  </MetadataPopover.Body>
                </MetadataPopover.Content>
              </MetadataPopover.Root>
            )}
          </div>
        </div>

        <span ref={containerRef} className="relative block" tabIndex={0}>
          {typeof message.content !== 'string' && renderReasoningBlock()}
          <div className="whitespace-pre-wrap [overflow-wrap:anywhere] max-w-full text-xs overflow-x-auto font-mono custom-scrollbar">
            {renderMainMessageContent()}
          </div>
          {renderToolInfo()}
          {renderToolCalls()}
        </span>
      </div>
    </div>
  );
}
