import { ChatMessage, Content, Datapoint, ToolCall } from '@/app/types/docent';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { toast } from '@/hooks/use-toast';
import {
  ChevronDown,
  ChevronUp,
  FileText,
  Loader,
  Loader2,
  MessageSquarePlus,
  Pencil,
} from 'lucide-react';
import React, {
  forwardRef,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useFrameGrid } from '../../../contexts/FrameGridContext';
import { useRouter } from 'next/navigation';

// Add this helper function near the top of the file
const formatMetadataValue = (value: any): string => {
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

// Add this interface at the top level of the file
interface EditingToolCall extends Omit<ToolCall, 'arguments'> {
  arguments: Record<string, unknown>;
  argumentsString: string;
}

const TranscriptViewer = forwardRef<
  { scrollToBlock: (blockIndex: number) => void },
  {
    datapoint: Datapoint | null;
    attributes: Record<string, string[]>;
  }
>(({ datapoint, attributes }, ref) => {
  const transcript = useMemo(() => datapoint?.obj || null, [datapoint]);

  // Create a ref for the transcript scroll area specifically
  const transcriptScrollAreaRef = useRef<HTMLDivElement>(null);

  // Add state to track current block index
  const [currentBlockIndex, setCurrentBlockIndex] = useState<number | null>(
    null
  );

  // Function to determine which block is most visible in the viewport
  const updateCurrentBlockFromScroll = useCallback(() => {
    if (!transcript || !transcriptScrollAreaRef.current) return;

    const scrollViewport = transcriptScrollAreaRef.current.querySelector(
      '[data-radix-scroll-area-viewport]'
    );

    if (!scrollViewport) return;

    const viewportRect = scrollViewport.getBoundingClientRect();
    const viewportTop = viewportRect.top;
    const viewportBottom = viewportRect.bottom;
    const viewportHeight = viewportRect.height;

    // Find all block elements
    const blockElements = Array.from(
      document.querySelectorAll('[id^="block-"]')
    );

    if (blockElements.length === 0) return;

    // Calculate visibility for each block
    const visibilityScores = blockElements.map((element) => {
      const rect = element.getBoundingClientRect();

      // Calculate how much of the element is visible in the viewport
      const top = Math.max(rect.top, viewportTop);
      const bottom = Math.min(rect.bottom, viewportBottom);
      const visibleHeight = Math.max(0, bottom - top);

      // Calculate visibility as a percentage of the element's height
      const visibilityScore = visibleHeight / rect.height;

      // Extract block index from the id
      const blockId = element.id;
      const blockIndex = parseInt(blockId.replace('block-', ''), 10);

      return { blockIndex, visibilityScore };
    });

    // Find the block with the highest visibility score
    const mostVisibleBlock = visibilityScores.reduce(
      (prev, current) =>
        current.visibilityScore > prev.visibilityScore ? current : prev,
      { blockIndex: -1, visibilityScore: 0 }
    );

    // Only update if we found a visible block
    if (
      mostVisibleBlock.blockIndex >= 0 &&
      mostVisibleBlock.visibilityScore > 0
    ) {
      setCurrentBlockIndex(mostVisibleBlock.blockIndex);
    }
  }, [transcript]);

  // Updated scroll function
  const scrollToBlock = useCallback((blockIndex: number) => {
    const tryScrolling = (attempts = 0, maxAttempts = 5) => {
      const blockElement = document.getElementById(`block-${blockIndex}`);
      console.log('Scrolling to block', blockElement);
      console.log(
        'Transcript scroll area ref',
        transcriptScrollAreaRef.current
      );

      if (blockElement && transcriptScrollAreaRef.current) {
        const scrollViewport = transcriptScrollAreaRef.current.querySelector(
          '[data-radix-scroll-area-viewport]'
        );
        if (scrollViewport) {
          const containerRect = scrollViewport.getBoundingClientRect();
          const elementRect = blockElement.getBoundingClientRect();
          const relativeTop =
            elementRect.top - containerRect.top + scrollViewport.scrollTop;

          scrollViewport.scrollTo({
            top: relativeTop,
            behavior: 'smooth',
          });

          // Update current block index
          setCurrentBlockIndex(blockIndex);
          return true;
        }
      }

      // If element not found and we haven't exceeded max attempts
      if (attempts < maxAttempts) {
        // Try again after a short delay
        setTimeout(() => tryScrolling(attempts + 1, maxAttempts), 50);
        return false;
      }

      console.warn(
        `Failed to scroll to block ${blockIndex} after ${maxAttempts} attempts`
      );
      return false;
    };

    tryScrolling();
  }, []);

  // Add navigation functions
  const goToNextBlock = useCallback(() => {
    if (!transcript) return;

    const nextIndex =
      currentBlockIndex !== null
        ? Math.min(currentBlockIndex + 1, transcript.messages.length - 1)
        : 0;

    scrollToBlock(nextIndex);
  }, [currentBlockIndex, transcript, scrollToBlock]);

  const goToPrevBlock = useCallback(() => {
    if (!transcript) return;

    const prevIndex =
      currentBlockIndex !== null ? Math.max(currentBlockIndex - 1, 0) : 0;

    scrollToBlock(prevIndex);
  }, [currentBlockIndex, transcript, scrollToBlock]);

  // Add scroll event listener to update current block
  useEffect(() => {
    if (!transcriptScrollAreaRef.current) return;

    const scrollViewport = transcriptScrollAreaRef.current.querySelector(
      '[data-radix-scroll-area-viewport]'
    );

    if (!scrollViewport) return;

    // Debounce function to limit how often we update during scrolling
    let scrollTimeout: NodeJS.Timeout | null = null;

    const handleScroll = () => {
      if (scrollTimeout) {
        clearTimeout(scrollTimeout);
      }

      scrollTimeout = setTimeout(() => {
        updateCurrentBlockFromScroll();
      }, 100); // 100ms debounce
    };

    scrollViewport.addEventListener('scroll', handleScroll);

    // Initial check
    updateCurrentBlockFromScroll();

    return () => {
      if (scrollTimeout) {
        clearTimeout(scrollTimeout);
      }
      scrollViewport.removeEventListener('scroll', handleScroll);
    };
  }, [transcript, updateCurrentBlockFromScroll]);

  // Expose scrollToBlock via ref
  React.useImperativeHandle(
    ref,
    () => ({
      scrollToBlock,
    }),
    [scrollToBlock]
  );

  // Update the useEffect to use the new ref
  useEffect(() => {
    if (transcriptScrollAreaRef.current) {
      const scrollViewport = transcriptScrollAreaRef.current.querySelector(
        '[data-radix-scroll-area-viewport]'
      );
      if (scrollViewport) {
        scrollViewport.scrollTo({
          top: 0,
          behavior: 'instant',
        });
      }
    }
    // Reset current block index when transcript changes
    setCurrentBlockIndex(null);
  }, [transcript?.id]);

  return (
    <div className="flex flex-col space-y-2 min-h-0 relative h-full">
      {/* Transcript metadata */}
      <div>
        <div className="flex items-center">
          <div className="font-semibold text-sm">Selected Transcript</div>
          {transcript?.metadata &&
            Object.keys(transcript.metadata).length > 0 && (
              <Sheet>
                <SheetTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    title="View Metadata"
                  >
                    <FileText className="h-4 w-4" />
                  </Button>
                </SheetTrigger>
                <SheetContent
                  side="left"
                  className="w-[400px] sm:w-[540px] md:w-[640px] lg:w-[800px] p-4"
                >
                  <SheetHeader className="mb-4 space-y-1">
                    <SheetTitle className="text-sm font-semibold">
                      Transcript Metadata
                    </SheetTitle>
                    <SheetDescription className="text-xs text-muted-foreground">
                      Additional information about this transcript
                    </SheetDescription>
                  </SheetHeader>
                  <ScrollArea className="h-[calc(100vh-8rem)]">
                    <div className="font-mono">
                      <div className="w-full space-y-2">
                        {/* Add a special section for scores if they exist */}
                        {transcript.metadata?.['scores'] &&
                          Object.keys(transcript.metadata?.['scores']).length >
                            0 && (
                            <div className="p-1.5 rounded-md bg-gray-50">
                              <span className="text-xs font-semibold text-gray-700">
                                Scores
                              </span>
                              <div className="mt-1 pl-2 border-l-2 border-gray-200">
                                {Object.entries(
                                  transcript.metadata?.['scores']
                                ).map(([key, value], idx) => (
                                  <div
                                    key={idx}
                                    className="text-xs leading-tight mb-1 flex justify-between overflow-x-auto"
                                  >
                                    <span
                                      className={
                                        key ===
                                        transcript.metadata?.[
                                          'default_score_key'
                                        ]
                                          ? 'font-medium'
                                          : ''
                                      }
                                    >
                                      {key}
                                      {key ===
                                      transcript.metadata?.['default_score_key']
                                        ? ' (default)'
                                        : ''}
                                      :
                                    </span>
                                    <span
                                      className={`ml-2 px-1 rounded ${
                                        typeof value === 'boolean'
                                          ? value
                                            ? 'bg-green-50 text-green-600'
                                            : 'bg-red-50 text-red-600'
                                          : 'text-blue-600'
                                      }`}
                                    >
                                      {typeof value === 'boolean'
                                        ? value
                                          ? '✓ correct'
                                          : '✗ incorrect'
                                        : value}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        {/* Filter out scores from the regular metadata display */}
                        {Object.entries(transcript.metadata)
                          .filter(
                            ([key, _]) =>
                              !['scores', 'default_score_key'].includes(key)
                          )
                          .map(([key, value], index) => (
                            <div
                              key={index}
                              className="flex items-start p-1.5 rounded-md bg-gray-50"
                            >
                              <div className="flex-1">
                                <span className="text-xs font-semibold text-gray-700">
                                  {key}
                                </span>
                                <div className="mt-1 text-xs leading-tight pl-2 border-l-2 border-gray-200 whitespace-pre-wrap overflow-x-auto">
                                  {formatMetadataValue(value)}
                                </div>
                              </div>
                            </div>
                          ))}
                      </div>
                    </div>
                  </ScrollArea>
                </SheetContent>
              </Sheet>
            )}
        </div>
        {transcript && (
          <div className="border-gray-100 text-xs text-gray-500 flex flex-wrap gap-x-3 gap-y-0.5">
            {transcript.metadata?.is_loading_messages ? (
              <span className="whitespace-nowrap flex items-center">
                <Loader2 className="h-3 w-3 animate-spin text-blue-500 mr-1" />
                <span className="text-blue-500 font-medium">
                  Running experiment...
                </span>
              </span>
            ) : (
              <>
                <span className="whitespace-nowrap">
                  <span className="font-medium text-gray-600">task:</span>{' '}
                  {transcript.metadata?.['task_id']}
                </span>
                <span className="whitespace-nowrap">
                  <span className="font-medium text-gray-600">run:</span>{' '}
                  {transcript.metadata?.['epoch_id']}
                </span>
                {transcript.metadata?.['experiment_id'] !== undefined && (
                  <span className="whitespace-nowrap">
                    <span className="font-medium text-gray-600">
                      experiment:
                    </span>{' '}
                    {transcript.metadata?.['experiment_id'] as string}
                  </span>
                )}
                {transcript.metadata?.['model'] !== undefined && (
                  <span className="whitespace-nowrap">
                    <span className="font-medium text-gray-600">model:</span>{' '}
                    {transcript.metadata?.['model'] as string}
                  </span>
                )}
                {transcript.metadata?.['scores'] &&
                  transcript.metadata?.['default_score_key'] && (
                    <span
                      className={`whitespace-nowrap font-medium px-1 rounded ${
                        typeof transcript.metadata?.['scores'][
                          transcript.metadata?.['default_score_key'] as string
                        ] === 'boolean'
                          ? transcript.metadata?.['scores'][
                              transcript.metadata?.[
                                'default_score_key'
                              ] as string
                            ]
                            ? 'bg-green-50 text-green-600'
                            : 'bg-red-50 text-red-600'
                          : 'bg-blue-50 text-blue-600'
                      }`}
                    >
                      {typeof transcript.metadata?.['scores'][
                        transcript.metadata?.['default_score_key'] as string
                      ] === 'boolean'
                        ? transcript.metadata?.['scores'][
                            transcript.metadata?.['default_score_key'] as string
                          ]
                          ? '✓ correct'
                          : '✗ incorrect'
                        : `${transcript.metadata?.['default_score_key']}: ${transcript.metadata?.['scores'][transcript.metadata?.['default_score_key'] as string]}`}
                    </span>
                  )}
                <span className="whitespace-nowrap">
                  <span className="font-medium text-gray-600">length:</span>{' '}
                  {transcript.messages.length} message
                  {transcript.messages.length !== 1 ? 's' : ''}
                </span>
              </>
            )}
          </div>
        )}
      </div>

      {datapoint && transcript ? (
        <>
          <ScrollArea className="relative" ref={transcriptScrollAreaRef}>
            <div className="space-y-2">
              {transcript.messages.map((message, index) => (
                <MessageBox
                  key={index}
                  message={message}
                  index={index}
                  id={`block-${index}`}
                  datapoint={datapoint}
                  scrollToBlock={scrollToBlock}
                />
              ))}

              {/* Loading indicator */}
              {transcript.metadata.is_loading_messages && (
                <div className="flex items-center justify-center p-4 space-x-2 bg-gray-50 border border-gray-100 rounded-md">
                  <Loader className="h-4 w-4 animate-spin text-blue-500" />
                  <span className="text-xs font-medium text-gray-600">
                    Running evaluation...
                  </span>
                </div>
              )}
            </div>

            {/* Navigation buttons inside the ScrollArea */}
            {transcript && transcript.messages.length > 0 && (
              <div className="absolute bottom-4 right-4 flex flex-col gap-1">
                <div className="bg-gray-100 border border-gray-200 rounded-md shadow-sm flex flex-col">
                  <button
                    onClick={goToPrevBlock}
                    className="p-1.5 hover:bg-gray-200 transition-colors rounded-t-md"
                    title="Previous block"
                  >
                    <ChevronUp className="h-4 w-4 text-gray-600" />
                  </button>
                  <div className="h-px bg-gray-200" />
                  <button
                    onClick={goToNextBlock}
                    className="p-1.5 hover:bg-gray-200 transition-colors rounded-b-md"
                    title="Next block"
                  >
                    <ChevronDown className="h-4 w-4 text-gray-600" />
                  </button>
                </div>
              </div>
            )}
          </ScrollArea>
        </>
      ) : (
        <div className="flex items-center justify-center h-full">
          <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
        </div>
      )}
    </div>
  );
});

// Add display name for forwardRef
TranscriptViewer.displayName = 'TranscriptViewer';

export default TranscriptViewer;

// Add AttributeDisplay component to show attributes below citations
const AttributeDisplay: React.FC<{
  datapointId: string;
  blockIndex: number;
  scrollToBlock?: (blockIndex: number) => void;
}> = ({ datapointId, blockIndex, scrollToBlock }) => {
  const { curAttributeQuery, attributeMap } = useFrameGrid();

  if (!curAttributeQuery || !attributeMap.has(datapointId)) {
    return null;
  }

  const attributeValues = attributeMap.get(datapointId)?.get(curAttributeQuery);

  if (!attributeValues || attributeValues.length === 0) {
    return null;
  }

  // Filter attributes that have citations referencing this specific block
  const relevantAttributes = attributeValues.filter(
    (attr) =>
      attr.citations &&
      attr.citations.some((citation) => citation.block_idx === blockIndex)
  );

  if (relevantAttributes.length === 0) {
    return null;
  }

  // Render the attribute section with exact same styling as InnerCard.tsx
  return (
    <div className="ml-6 mt-2 mb-3 pt-1.5 border-t border-indigo-100 text-xs">
      <div className="flex items-center mb-1">
        <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
        <span className="text-xs font-medium text-indigo-700">
          Attributes from your query
        </span>
      </div>

      <div>
        {relevantAttributes.map((attributeValue, idx) => {
          const attributeText = attributeValue.attribute;
          // Use all citations for the attribute, not just those for this block
          const citations = attributeValue.citations || [];

          // Create a component that renders text with citations highlighted
          const renderTextWithCitations = () => {
            if (!citations.length) {
              return attributeText;
            }

            // Sort citations by start index to process them in order
            const sortedCitations = [...citations].sort(
              (a, b) => a.start_idx - b.start_idx
            );

            const parts: JSX.Element[] = [];
            let lastIndex = 0;

            sortedCitations.forEach((citation, i) => {
              // Add text before the citation
              if (citation.start_idx > lastIndex) {
                parts.push(
                  <span key={`text-${i}`}>
                    {attributeText.slice(lastIndex, citation.start_idx)}
                  </span>
                );
              }

              // Add the cited text as a clickable element
              const citedText = attributeText.slice(
                citation.start_idx,
                citation.end_idx
              );
              // Use different style for current block vs. other blocks
              const isCurrentBlock = citation.block_idx === blockIndex;
              parts.push(
                <button
                  key={`citation-${i}`}
                  className={`px-0.5 py-0.25 ${
                    isCurrentBlock
                      ? 'bg-indigo-200 text-indigo-800 hover:bg-indigo-400'
                      : 'bg-blue-100 text-blue-800 hover:bg-blue-300'
                  } rounded hover:text-white transition-colors font-medium`}
                  onClick={(e) => {
                    e.stopPropagation();
                    scrollToBlock?.(citation.block_idx);
                  }}
                >
                  {citedText}
                </button>
              );

              lastIndex = citation.end_idx;
            });

            // Add any remaining text
            if (lastIndex < attributeText.length) {
              parts.push(
                <span key={`text-end`}>{attributeText.slice(lastIndex)}</span>
              );
            }

            return <>{parts}</>;
          };

          return (
            <div
              key={`${curAttributeQuery}-${idx}`}
              className="group bg-indigo-50 rounded-md p-1 text-xs text-indigo-900 leading-snug mt-1 hover:bg-indigo-100 transition-colors cursor-pointer border border-transparent hover:border-indigo-200"
              onClick={(e) => {
                e.stopPropagation();
                if (scrollToBlock && citations.length > 0) {
                  const firstCitation = citations[0];
                  scrollToBlock(firstCitation.block_idx);
                }
              }}
            >
              <p className="mb-0.5">{renderTextWithCitations()}</p>
              <div className="flex items-center gap-1 text-[10px] text-indigo-600 mt-1">
                <span className="opacity-70">{curAttributeQuery}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const MessageBox: React.FC<{
  message: ChatMessage;
  index: number;
  id?: string;
  datapoint: Datapoint;
  scrollToBlock: (blockIndex: number) => void;
}> = ({ message, index, id, datapoint, scrollToBlock }) => {
  const router = useRouter();

  const { sendMessage, handleClearAttribute } = useFrameGrid();
  const datapointId = datapoint.id;
  const [isEditing, setIsEditing] = React.useState(false);
  const [editedContent, setEditedContent] = React.useState('');
  const [editedReasoningContent, setEditedReasoningContent] = React.useState<
    string | null
  >(null);
  const [editedToolCalls, setEditedToolCalls] = React.useState<
    EditingToolCall[]
  >([]);
  const [showNewMessageDialog, setShowNewMessageDialog] = React.useState(false);
  const [newMessageContent, setNewMessageContent] = React.useState('');
  // Add state for additional messages and epochs
  const [numAdditionalMessages, setNumAdditionalMessages] =
    React.useState<string>('');
  const [numEpochs, setNumEpochs] = React.useState<string>('');
  const [editNumAdditionalMessages, setEditNumAdditionalMessages] =
    React.useState<string>('');
  const [editNumEpochs, setEditNumEpochs] = React.useState<string>('');

  const getRoleStyle = () => {
    switch (message.role) {
      case 'assistant':
        return 'bg-blue-50 border-l-4 border-blue-500';
      case 'user':
        return 'bg-gray-50 border-l-4 border-gray-500';
      case 'system':
        return 'bg-orange-50 border-l-4 border-orange-500';
      case 'tool':
        return 'bg-green-50 border-l-4 border-green-500';
      default:
        return 'bg-gray-50 border-l-4 border-gray-500';
    }
  };

  const getMessageContent = (content: string | Content[]): string => {
    if (typeof content === 'string') {
      return content;
    }
    // If content is an array of Content objects
    return content
      .filter(
        (item): item is Content & { text: string } =>
          item.type === 'text' && typeof item.text === 'string'
      )
      .map((item) => item.text)
      .join('\n');
  };

  // Add a new function to extract reasoning content
  const getReasoningContent = (content: string | Content[]): string | null => {
    if (typeof content === 'string') {
      return null;
    }
    // Find the first reasoning content item
    const reasoningItem = content.find(
      (item): item is Content & { reasoning: string } =>
        item.type === 'reasoning' && typeof item.reasoning === 'string'
    );
    return reasoningItem ? reasoningItem.reasoning : null;
  };

  const handleEditClick = () => {
    setEditedContent(getMessageContent(message.content));
    setEditedReasoningContent(
      message.role === 'assistant' ? getReasoningContent(message.content) : null
    );
    if ('tool_calls' in message && message.tool_calls) {
      setEditedToolCalls(
        message.tool_calls.map((tool) => ({
          ...tool,
          arguments: tool.arguments || {},
          argumentsString: JSON.stringify(tool.arguments || {}, null, 2),
        }))
      );
    } else {
      setEditedToolCalls([]);
    }
    // Reset the additional messages and epochs fields
    setEditNumAdditionalMessages('');
    setEditNumEpochs('');
    setIsEditing(true);
  };

  const handleEditSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    let editedMessage: ChatMessage;

    // For assistant messages, validate tool calls JSON
    if (message.role === 'assistant' && editedToolCalls.length > 0) {
      try {
        // Validate each tool call's arguments
        const validatedToolCalls = editedToolCalls.map((tool) => {
          const parsedArguments = JSON.parse(tool.argumentsString);
          return {
            id: tool.id,
            function: tool.function,
            arguments: parsedArguments,
            type: 'function',
            view: tool.view
              ? {
                  content: tool.view.content,
                  format: 'markdown', // TODO(vincent): why do we have both text and markdown?
                }
              : undefined,
          };
        });

        // Create content array with both text and reasoning if applicable
        let newContent: string | Content[];
        if (typeof message.content === 'string') {
          newContent = editedContent;
        } else {
          // Build a new content array
          newContent = message.content
            .filter((item) => item.type !== 'text' && item.type !== 'reasoning')
            .concat([{ type: 'text', text: editedContent }]);

          // Add reasoning if it exists in the original message - preserve it as is
          const originalReasoning = message.content.find(
            (item) => item.type === 'reasoning'
          );
          if (message.role === 'assistant' && originalReasoning) {
            newContent.push(originalReasoning);
          }
        }

        editedMessage = {
          ...message,
          content: newContent,
          tool_calls: validatedToolCalls,
        };
      } catch (error) {
        toast({
          title: 'Invalid JSON',
          description: 'Please check the tool call arguments format',
          variant: 'destructive',
        });
        return;
      }
    } else {
      // Handle non-assistant messages
      // Create content array with both text and reasoning if applicable
      let newContent: string | Content[];
      if (typeof message.content === 'string') {
        newContent = editedContent;
      } else {
        // Build a new content array
        newContent = message.content
          .filter((item) => item.type !== 'text' && item.type !== 'reasoning')
          .concat([{ type: 'text', text: editedContent }]);

        // Add reasoning if it exists in the original message - preserve it as is
        const originalReasoning = message.content.find(
          (item) => item.type === 'reasoning'
        );
        if (message.role === 'assistant' && originalReasoning) {
          newContent.push(originalReasoning);
        }
      }

      editedMessage = {
        ...message,
        content: newContent,
      };
    }

    // Parse the additional messages and epochs values
    const additionalMessages =
      editNumAdditionalMessages.trim() !== ''
        ? parseInt(editNumAdditionalMessages, 10)
        : undefined;

    const epochs =
      editNumEpochs.trim() !== '' ? parseInt(editNumEpochs, 10) : undefined;

    // Send to server with optional parameters
    sendMessage('conversation_intervention', {
      datapoint_id: datapointId,
      message_index: index,
      new_message: editedMessage,
      ...(additionalMessages !== undefined && {
        num_additional_messages: additionalMessages,
      }),
      ...(epochs !== undefined && { num_epochs: epochs }),
    });

    setIsEditing(false);
    toast({
      title: 'New experiment created',
      description: 'Return to the experiment page to view the new experiment',
    });
    handleClearAttribute(null);
  };

  const handleToolCallChange = (
    index: number,
    field: keyof ToolCall | 'argumentsString',
    value: string
  ) => {
    setEditedToolCalls((prev) => {
      const updated = [...prev];
      const toolCall = { ...updated[index] };

      if (field === 'argumentsString') {
        toolCall.argumentsString = value;
        // Keep the arguments object as-is until submit
      } else if (field === 'function' || field === 'id') {
        toolCall[field] = value;
      } else if (field === 'view') {
        toolCall.view = { content: value, format: 'markdown' };
      }

      updated[index] = toolCall;
      return updated;
    });
  };

  const addToolCall = () => {
    setEditedToolCalls((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        function: '',
        arguments: {},
        argumentsString: '{}',
        type: 'function',
      },
    ]);
  };

  const removeToolCall = (index: number) => {
    setEditedToolCalls((prev) => prev.filter((_, i) => i !== index));
  };

  // Helper to render tool-specific information
  const renderToolInfo = () => {
    if (message.role === 'tool') {
      return (
        <div className="mt-1 text-[10px] text-gray-500">
          {message.tool_call_id && (
            <span>Tool Call ID: {message.tool_call_id}</span>
          )}
          {message.function && (
            <span className="ml-2">Function: {message.function}</span>
          )}
          {message.error && (
            <div className="mt-1 text-red-500">
              Error: {message.error.message}
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  // Helper to render tool calls for assistant messages
  const renderToolCalls = () => {
    if (message.role === 'assistant' && message.tool_calls) {
      return message.tool_calls.map((tool, i) => (
        <div
          key={i}
          className="mt-1 p-1.5 bg-gray-100 rounded text-xs break-all whitespace-pre-wrap"
        >
          <div className="text-[10px] text-gray-600 mb-0.5">
            Tool Call ID: {tool.id}
          </div>
          {tool.view ? (
            <span className="font-mono">{tool.view.content}</span>
          ) : (
            <div className="font-mono">
              <span className="font-semibold">{tool.function}</span>
              <span className="text-gray-600">
                (
                {Object.entries(tool.arguments || {})
                  .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                  .join(', ')}
                )
              </span>
            </div>
          )}
        </div>
      ));
    }
    return null;
  };

  const handleAddMessage = () => {
    if (!newMessageContent.trim()) {
      toast({
        title: 'Empty message',
        description: 'Please enter a message',
        variant: 'destructive',
      });
      return;
    }

    // Parse the additional messages and epochs values
    const additionalMessages =
      numAdditionalMessages.trim() !== ''
        ? parseInt(numAdditionalMessages, 10)
        : undefined;

    const epochs =
      numEpochs.trim() !== '' ? parseInt(numEpochs, 10) : undefined;

    // Send to server with optional parameters
    sendMessage('conversation_intervention', {
      datapoint_id: datapointId,
      message_index: index + 1,
      new_message: {
        role: 'user',
        content: newMessageContent,
      },
      insert: true,
      ...(additionalMessages !== undefined && {
        num_additional_messages: additionalMessages,
      }),
      ...(epochs !== undefined && { num_epochs: epochs }),
    });

    setShowNewMessageDialog(false);
    setNewMessageContent('');
    setNumAdditionalMessages('');
    setNumEpochs('');
    toast({
      title: 'New experiment created',
      description: 'Return to the experiment page to view the new experiment',
    });
    handleClearAttribute(null);
  };

  return (
    <div className="mb-1">
      <div id={id} className={`p-2 rounded-md text-sm ${getRoleStyle()}`}>
        <div className="text-[10px] text-gray-600 flex justify-between mb-1">
          <span>
            Block {index} |{' '}
            {message.role.charAt(0).toUpperCase() + message.role.slice(1)}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={handleEditClick}
              className="hover:text-blue-600 transition-colors p-1 hover:bg-blue-50 rounded"
              title="Edit message"
            >
              <Pencil size={12} />
            </button>
            <button
              onClick={() => setShowNewMessageDialog(true)}
              className="hover:text-blue-600 transition-colors p-1 hover:bg-blue-50 rounded"
              title="Add new message"
            >
              <MessageSquarePlus size={12} />
            </button>
            <span>ID: B{index}</span>
          </div>
        </div>

        <Dialog
          open={showNewMessageDialog}
          onOpenChange={setShowNewMessageDialog}
        >
          <DialogContent>
            <DialogHeader className="space-y-1">
              <DialogTitle className="text-sm font-semibold">
                Add New Message
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground">
                Add a new user message after block {index}
              </DialogDescription>
            </DialogHeader>
            <div className="mt-4">
              <label className="block text-xs text-gray-700 mb-1">
                Message Content
              </label>
              <textarea
                value={newMessageContent}
                onChange={(e) => setNewMessageContent(e.target.value)}
                className="w-full p-2 border rounded-md text-xs min-h-[100px] focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                placeholder="Enter your message here..."
                autoFocus
              />
            </div>

            {/* Add fields for additional messages and epochs */}
            <div className="mt-4 grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-700 mb-1">
                  Number of Additional Messages
                </label>
                <input
                  type="number"
                  value={numAdditionalMessages}
                  onChange={(e) => setNumAdditionalMessages(e.target.value)}
                  className="w-full p-2 border rounded-md text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                  placeholder="Leave empty for default"
                  min="1"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-700 mb-1">
                  Number of Epochs
                </label>
                <input
                  type="number"
                  value={numEpochs}
                  onChange={(e) => setNumEpochs(e.target.value)}
                  className="w-full p-2 border rounded-md text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                  placeholder="Leave empty for default"
                  min="1"
                />
              </div>
            </div>

            <DialogFooter className="mt-4">
              <Button
                variant="outline"
                onClick={() => setShowNewMessageDialog(false)}
                className="text-xs"
              >
                Cancel
              </Button>
              <Button onClick={handleAddMessage} className="text-xs">
                Add Message
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {isEditing ? (
          <form
            onSubmit={handleEditSubmit}
            className="mt-1 space-y-4 font-mono"
          >
            <div>
              <label className="block text-xs text-gray-700 mb-1">
                Content
              </label>
              <textarea
                value={editedContent}
                onChange={(e) => setEditedContent(e.target.value)}
                className="w-full p-2 border rounded-md text-xs min-h-[100px] focus:outline-none focus:ring-2 focus:ring-blue-500"
                autoFocus
              />
            </div>

            {message.role === 'assistant' && (
              <>
                {editedReasoningContent !== null ? (
                  <div>
                    <label className="block text-xs text-gray-700 mb-1 flex items-center justify-between">
                      <span>Reasoning (Read Only)</span>
                      <span className="text-[10px] text-gray-500 italic">
                        Model thinking tokens cannot be modified
                      </span>
                    </label>
                    <textarea
                      value={editedReasoningContent}
                      className="w-full p-2 border rounded-md text-xs min-h-[80px] focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-100 cursor-not-allowed"
                      placeholder="Reasoning content (read-only)"
                      disabled={true}
                    />
                  </div>
                ) : (
                  <div>
                    <button
                      type="button"
                      className="text-xs px-2 py-1 bg-gray-50 text-gray-400 rounded border border-gray-200 cursor-not-allowed opacity-60 relative group"
                      disabled={true}
                    >
                      Reasoning (Read Only)
                      <span className="absolute left-0 -bottom-5 text-[9px] text-gray-500 italic whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
                        Model thinking tokens cannot be modified
                      </span>
                    </button>
                  </div>
                )}
              </>
            )}

            {/* Add fields for additional messages and epochs */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-700 mb-1">
                  Number of Additional Messages
                </label>
                <input
                  type="number"
                  value={editNumAdditionalMessages}
                  onChange={(e) => setEditNumAdditionalMessages(e.target.value)}
                  className="w-full p-2 border rounded-md text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                  placeholder="Leave empty for default"
                  min="1"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-700 mb-1">
                  Number of Epochs
                </label>
                <input
                  type="number"
                  value={editNumEpochs}
                  onChange={(e) => setEditNumEpochs(e.target.value)}
                  className="w-full p-2 border rounded-md text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                  placeholder="Leave empty for default"
                  min="1"
                />
              </div>
            </div>

            {message.role === 'assistant' && (
              <div>
                <div className="flex justify-between items-center mb-2">
                  <label className="block text-xs text-gray-700">
                    Tool Calls
                  </label>
                  <button
                    type="button"
                    onClick={addToolCall}
                    className="text-xs px-2 py-1 bg-blue-50 hover:bg-blue-100 text-blue-600 rounded"
                  >
                    Add Tool Call
                  </button>
                </div>

                {editedToolCalls.map((tool, idx) => (
                  <div key={tool.id} className="mb-4 p-3 bg-gray-50 rounded-md">
                    <div className="flex justify-between mb-2">
                      <span className="text-xs text-gray-600">
                        Tool Call {idx + 1}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeToolCall(idx)}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </div>

                    <div className="space-y-2">
                      <input
                        value={tool.id}
                        onChange={(e) =>
                          handleToolCallChange(idx, 'id', e.target.value)
                        }
                        placeholder="Tool Call ID"
                        className="w-full p-1.5 text-xs border rounded"
                      />

                      <input
                        value={tool.function}
                        onChange={(e) =>
                          handleToolCallChange(idx, 'function', e.target.value)
                        }
                        placeholder="Function name"
                        className="w-full p-1.5 text-xs border rounded"
                      />

                      <textarea
                        value={tool.argumentsString}
                        onChange={(e) =>
                          handleToolCallChange(
                            idx,
                            'argumentsString',
                            e.target.value
                          )
                        }
                        placeholder="Arguments (JSON)"
                        className="w-full p-1.5 text-xs border rounded font-mono min-h-[80px]"
                      />

                      {tool.view && (
                        <textarea
                          value={tool.view.content}
                          onChange={(e) =>
                            handleToolCallChange(idx, 'view', e.target.value)
                          }
                          placeholder="View content"
                          className="w-full p-1.5 text-xs border rounded min-h-[60px]"
                        />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsEditing(false)}
                className="px-2 py-1 text-xs rounded-md bg-gray-100 hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-2 py-1 text-xs rounded-md bg-blue-500 text-white hover:bg-blue-600 transition-colors"
              >
                Submit
              </button>
            </div>
          </form>
        ) : (
          <>
            {typeof message.content !== 'string' && (
              <>
                {message.role === 'assistant' &&
                  getReasoningContent(message.content) && (
                    <div className="mb-2 px-2 py-2 bg-gray-100 border-l-2 border-gray-400 text-xs text-gray-700 italic whitespace-pre-wrap [overflow-wrap:anywhere] max-w-full overflow-x-auto font-mono rounded">
                      {getReasoningContent(message.content)}
                    </div>
                  )}
              </>
            )}
            <div className="whitespace-pre-wrap [overflow-wrap:anywhere] max-w-full text-xs overflow-x-auto font-mono">
              {getMessageContent(message.content)}
            </div>
            {renderToolInfo()}
            {renderToolCalls()}
          </>
        )}
      </div>

      {/* Add the AttributeDisplay component outside the message card */}
      {!isEditing && (
        <AttributeDisplay
          datapointId={datapointId}
          blockIndex={index}
          scrollToBlock={scrollToBlock}
        />
      )}
    </div>
  );
};
