import React, { useMemo, useRef } from 'react';
import jsonStringFormatter from 'json-string-formatter';
import { useAppSelector } from '@/app/store/hooks';
import { ChatMessage, Content, ToolCall } from '@/app/types/transcriptTypes';
import { cn } from '@/lib/utils';
import { Citation } from '@/app/types/experimentViewerTypes';
import {
  computeCitationIntervals,
  sliceIntervals,
  TextSpanWithCitations,
  transformCitationIntervalsForPrettyPrintJson,
} from '@/lib/citationMatch';
import { SegmentedText } from '@/lib/SegmentedText';
import { MetadataPopover } from '@/components/metadata/MetadataPopover';
import { MetadataBlock } from '@/components/metadata/MetadataBlock';
import { useTextSelection } from '@/providers/use-text-selection';

function stringify(x: any): string {
  if (typeof x === 'string') return x;
  return JSON.stringify(x);
}

export const shiftIntervals = (
  intervals: TextSpanWithCitations[],
  delta: number
): TextSpanWithCitations[] =>
  intervals
    .map((interval) => ({
      ...interval,
      start: interval.start - delta,
      end: interval.end - delta,
    }))
    .filter((interval) => interval.start < interval.end);

export const formatToolCallArgs = (args: Record<string, unknown> | undefined) =>
  Object.entries(args || {})
    .map(([k, v]) => `${k}=${stringify(v)}`)
    .join(', ');

export const getToolCallDisplayContent = (tool: ToolCall) =>
  tool.view
    ? tool.view.content
    : `${tool.function}(${formatToolCallArgs(tool.arguments)})`;

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

const getRoleStyle = (role: string, isHighlighted: boolean) => {
  const transitionClasses = 'transition-colors duration-500 ease-out';

  // Use specific color classes instead of dynamic ones
  const getColorClasses = (role: string, highlighted: boolean) => {
    switch (role) {
      case 'user':
        return highlighted
          ? 'bg-muted-foreground/40 border-l-4 border-muted-foreground'
          : 'bg-gray-50 dark:bg-gray-900/50 border-l-4 border-gray-300 dark:border-gray-700';
      case 'assistant':
        return highlighted
          ? 'bg-blue-500/40 border-l-4 border-blue-500'
          : 'bg-blue-50 dark:bg-blue-950/30 border-l-4 border-blue-300 dark:border-blue-700';
      case 'system':
        return highlighted
          ? 'bg-orange-500/40 border-l-4 border-orange-500'
          : 'bg-orange-50 dark:bg-orange-950/30 border-l-4 border-orange-300 dark:border-orange-700';
      case 'tool':
        return highlighted
          ? 'bg-green-500/40 border-l-4 border-green-500'
          : 'bg-green-50 dark:bg-green-950/30 border-l-4 border-green-300 dark:border-green-700';
      default:
        return highlighted
          ? 'bg-slate-500/40 border-l-4 border-slate-500'
          : 'bg-gray-50 dark:bg-gray-900/50 border-l-4 border-gray-300 dark:border-gray-700';
    }
  };

  const colorClasses = getColorClasses(role, isHighlighted);
  return `${colorClasses} ${transitionClasses}`;
};

type MessageComponentRange = {
  content: string;
  start: number;
  end: number;
  source?: any;
};
type MessageContentRanges = {
  main: MessageComponentRange;
  reasoning: MessageComponentRange | null;
  toolCalls: MessageComponentRange[];
};

// Take a ChatMessage and re-create the text that the judge model would have seen when writing citations
// Returns tuple of text and ranges where message components appear in the text
export function getMessageContentForCitations(
  message: ChatMessage
): [string, MessageContentRanges] {
  // Main content
  let mainContent = '';

  if (typeof message.content === 'string') {
    mainContent = message.content;
  } else {
    mainContent = message.content
      .filter(
        (item): item is Content & { text: string } =>
          item.type === 'text' && typeof item.text === 'string'
      )
      .map((item) => item.text)
      .join('\n');
  }

  const main: MessageComponentRange = {
    content: mainContent,
    start: 0,
    end: mainContent.length,
  };

  let textContent = mainContent;

  // Reasoning
  const reasoningText = getReasoningContent(message.content);
  let reasoning: MessageComponentRange | null = null;
  if (reasoningText) {
    const startIndex = textContent.length + 1; // account for leading newline
    textContent += `\n${reasoningText}`;
    reasoning = {
      content: reasoningText,
      start: startIndex,
      end: startIndex + reasoningText.length,
    };
  }

  // Tool calls
  const toolCalls: MessageComponentRange[] = [];
  if (
    message?.role === 'assistant' &&
    'tool_calls' in message &&
    message.tool_calls
  ) {
    for (const toolCall of message.tool_calls) {
      const innerContent = toolCall.view
        ? toolCall.view.content
        : `${toolCall.function}(${formatToolCallArgs(toolCall.arguments)})`;

      textContent += '\n<tool call>\n';
      toolCalls.push({
        content: innerContent,
        start: textContent.length,
        end: textContent.length + innerContent.length,
        source: toolCall,
      });
      textContent += innerContent;
      textContent += '\n</tool call>';
    }
  }

  return [textContent, { main, reasoning, toolCalls }];
}

interface MessageBoxProps {
  message: ChatMessage;
  index: number;
  blockId?: string;
  isHighlighted: boolean;
  citedRanges: Citation[];
  prettyPrintJsonMessages: Set<number>;
  setPrettyPrintJsonMessages: React.Dispatch<React.SetStateAction<Set<number>>>;
  transcriptIdx?: number;
  metadataDialogControl?: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    citedKey?: string;
    citedTextRange?: string;
  };
}

export function MessageBox({
  message,
  index,
  blockId: id,
  isHighlighted,
  citedRanges,
  prettyPrintJsonMessages,
  setPrettyPrintJsonMessages,
  transcriptIdx,
  metadataDialogControl,
}: MessageBoxProps) {
  const containerRef = useRef<HTMLSpanElement | null>(null);
  useTextSelection({
    containerRef:
      containerRef as unknown as React.RefObject<HTMLElement | null>,
    selectionItem: {
      transcriptIdx,
      blockIdx: index,
      text: '',
    },
  });
  const highlightedCitationId = useAppSelector(
    (state) => state.transcript.highlightedCitationId
  );

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

  // Reconstruct the string that the judge saw when writing citations, and track how it maps to the chunks we'll render
  const [textForCitations, componentRanges] = useMemo(
    () => getMessageContentForCitations(message),
    [message]
  );
  const allCitationIntervals = computeCitationIntervals(
    textForCitations as string,
    citedRanges
  );

  const renderMainMessageContent = () => {
    const rawContentString = componentRanges.main.content;

    const contentString = prettyPrintJsonMessages.has(index)
      ? prettyPrintJson(rawContentString)
      : rawContentString;

    // Slice intervals to the main content range and align to that slice
    const mainIntervals = sliceIntervals(
      allCitationIntervals,
      componentRanges.main.start,
      componentRanges.main.end
    );

    // If content was pretty-printed, transform the citation intervals to match the new positions
    const citationIntervals =
      prettyPrintJsonMessages.has(index) && rawContentString !== contentString
        ? transformCitationIntervalsForPrettyPrintJson(
            mainIntervals,
            rawContentString,
            contentString
          )
        : mainIntervals;

    return (
      <div>
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
    if (message.role === 'assistant' && message.tool_calls) {
      return componentRanges.toolCalls.map((tool, i) => {
        const toolCallIntervals = sliceIntervals(
          allCitationIntervals,
          tool.start,
          tool.end
        );

        return (
          <div
            key={i}
            className="mt-1 p-1.5 bg-secondary/85 rounded text-xs break-all whitespace-pre-wrap"
          >
            <div className="text-[10px] text-muted-foreground mb-0.5">
              Tool Call ID: {tool.source.id}
            </div>
            {tool.source.view ? (
              <span className="font-mono">
                <SegmentedText
                  text={tool.content}
                  intervals={toolCallIntervals}
                  role={message.role}
                  highlightedCitationId={highlightedCitationId ?? null}
                />
              </span>
            ) : (
              <div className="font-mono">
                <span className="font-semibold">{tool.source.function}</span>
                <span className="text-muted-foreground">
                  (
                  <SegmentedText
                    text={formatToolCallArgs(tool.source.arguments)}
                    intervals={shiftIntervals(
                      toolCallIntervals,
                      tool.source.function.length + 1
                    )}
                    role={message.role}
                    highlightedCitationId={highlightedCitationId ?? null}
                  />
                  )
                </span>
              </div>
            )}
          </div>
        );
      });
    }
    return null;
  };

  const renderReasoningBlock = () => {
    const reasoningText = componentRanges.reasoning?.content;
    if (!reasoningText) return null;

    const intervals = sliceIntervals(
      allCitationIntervals,
      componentRanges.reasoning!.start,
      componentRanges.reasoning!.end
    );

    return (
      <div className="mb-2 px-2 py-2 bg-muted border-l-2 border-border text-xs text-primary italic whitespace-pre-wrap [overflow-wrap:anywhere] max-w-full overflow-x-auto font-mono rounded custom-scrollbar">
        <SegmentedText
          text={reasoningText}
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

  return (
    <div className="mb-1">
      <div
        id={id}
        className={cn(
          'p-2 rounded-md text-sm',
          !isHighlighted && 'transition-all duration-1500',
          getRoleStyle(message.role, isHighlighted)
        )}
      >
        <div className="text-[10px] text-muted-foreground flex justify-between mb-1">
          <span>
            Block {index} |{' '}
            {message.role.charAt(0).toUpperCase() + message.role.slice(1)}
          </span>
          <div className="flex items-center gap-2">
            {hasJsonContent(componentRanges.main.content) && (
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
                        citedKey={metadataDialogControl?.citedKey}
                        citedTextRange={metadataDialogControl?.citedTextRange}
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
