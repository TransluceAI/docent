import {
  ChevronDown,
  ChevronUp,
  FileText,
  Loader2,
  Share2,
} from 'lucide-react';
import React, {
  forwardRef,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { useAppSelector } from '@/app/store/hooks';
import { ChatMessage, Content, AgentRun } from '@/app/types/transcriptTypes';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import UuidPill from '@/components/UuidPill';
import { useDebounce } from '@/hooks/use-debounce';
import { toast } from '@/hooks/use-toast';

import MetadataDialog from './MetadataDialog';

// Export interface for use in other components
export interface AgentRunViewerHandle {
  scrollToBlock: (
    blockIdx: number,
    transcriptIdx: number,
    agentRunIdx: number
  ) => void;
}

// Add props interface
interface AgentRunViewerProps {
  secondary: boolean;
  otherAgentRunRef?: React.RefObject<AgentRunViewerHandle>;
}

// Add this helper function near the top of the file
const formatMetadataValue = (value: any): string => {
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

const AgentRunViewer = forwardRef<AgentRunViewerHandle, AgentRunViewerProps>(
  ({ secondary, otherAgentRunRef }, ref) => {
    const agentRun = useAppSelector((state) =>
      secondary ? state.transcript.altAgentRun : state.transcript.curAgentRun
    );

    // Add state for selected transcript key
    const [selectedTranscriptKey, setSelectedTranscriptKey] = useState<
      string | null
    >(null);

    const [transcript, transcriptIdx, transcriptKeys] = useMemo(() => {
      if (!agentRun || Object.keys(agentRun.transcripts).length === 0) {
        return [null, 0, []];
      }

      // If no transcript is selected, default to the first one
      const transcriptKeys = Object.keys(agentRun.transcripts);
      const targetId =
        selectedTranscriptKey && transcriptKeys.includes(selectedTranscriptKey)
          ? selectedTranscriptKey
          : transcriptKeys[0];

      // Update selected transcript key if it was null
      if (!selectedTranscriptKey && transcriptKeys.length > 0) {
        setSelectedTranscriptKey(transcriptKeys[0]);
      }

      return [
        agentRun.transcripts[targetId],
        transcriptKeys.indexOf(targetId),
        transcriptKeys,
      ];
    }, [agentRun, selectedTranscriptKey]);

    /**
     * Scrolling
     */
    const [scrollPosition, setScrollPosition] = useState(0);
    const debouncedScrollPosition = useDebounce(scrollPosition, 100);
    const [scrollNode, setScrollNode] = useState<HTMLDivElement | null>(null);
    const [currentBlockIndex, setCurrentBlockIndex] = useState<number | null>(
      null
    );

    const scrollContainerRef = useCallback((node: HTMLDivElement) => {
      if (!node) return;
      // Store the node reference
      setScrollNode(node);

      // Update scroll position on scroll
      const handleScroll = () => {
        setScrollPosition(node.scrollTop);
      };
      node.addEventListener('scroll', handleScroll);
      return () => {
        node.removeEventListener('scroll', handleScroll);
      };
    }, []);

    // Compute the current block index based on scroll position
    useEffect(() => {
      // Skip if no transcript or no scroll node
      if (!transcript || !scrollNode) return;

      // Get all block elements
      const blockElements = Array.from(
        document.querySelectorAll(
          `[id*="r-${secondary ? 1 : 0}_t-${transcriptIdx}_b-"]`
        )
      );
      if (blockElements.length === 0) return;

      // Use the stored node reference directly
      const containerRect = scrollNode.getBoundingClientRect();
      const viewportTop = containerRect.top;
      const viewportHeight = containerRect.height;

      // Calculate visibility for each block
      const visibilityScores = blockElements.map((element) => {
        const rect = element.getBoundingClientRect();

        // Calculate how much of the element is visible in the viewport
        const top = Math.max(rect.top, viewportTop);
        const bottom = Math.min(rect.bottom, viewportTop + viewportHeight);
        const visibleHeight = Math.max(0, bottom - top);

        // Calculate visibility as a percentage of the element's height
        const visibilityScore = visibleHeight / rect.height;

        // Extract block index from the id
        const blockIdx = parseInt(
          element.id.replace('b-', '').split('_')[2],
          10
        );

        return { blockIndex: blockIdx, visibilityScore };
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
        console.log('Current block index:', mostVisibleBlock.blockIndex);
      }
    }, [debouncedScrollPosition, transcript, scrollNode]);

    /**
     * Scroll to block function - now with cross-scrolling support
     */
    const scrollToBlock = useCallback(
      (
        toBlockIdx: number,
        toTranscriptIdx: number = 0,
        toAgentRunIdx: number = 0
      ) => {
        // Determine which transcript should handle this scroll
        const currentAgentRunIdx = secondary ? 1 : 0;

        if (toAgentRunIdx !== currentAgentRunIdx && otherAgentRunRef?.current) {
          // Cross-scroll to the other agent run
          otherAgentRunRef.current.scrollToBlock(
            toBlockIdx,
            toTranscriptIdx,
            (toAgentRunIdx + 1) % 2
          );
          return;
        }

        // Handle scrolling within this agent run
        // First, change the selected transcript if needed
        const targetTranscriptKey = transcriptKeys[toTranscriptIdx];
        const needsTranscriptChange =
          targetTranscriptKey && targetTranscriptKey !== selectedTranscriptKey;

        if (needsTranscriptChange) {
          setSelectedTranscriptKey(targetTranscriptKey);
        }

        const tryScrolling = (attempts = 0, maxAttempts = 3) => {
          const blockElement = document.getElementById(
            `r-${toAgentRunIdx}_t-${toTranscriptIdx}_b-${toBlockIdx}`
          );
          if (blockElement && scrollNode) {
            const containerRect = scrollNode.getBoundingClientRect();
            const elementRect = blockElement.getBoundingClientRect();
            const relativeTop =
              elementRect.top - containerRect.top + scrollNode.scrollTop;

            scrollNode.scrollTo({
              top: relativeTop,
              behavior: 'smooth',
            });

            // Update current block index
            setCurrentBlockIndex(toBlockIdx);
            return true;
          }

          // If element not found and we haven't exceeded max attempts
          if (attempts < maxAttempts) {
            // Try again after a short delay
            setTimeout(() => tryScrolling(attempts + 1, maxAttempts), 50);
            return false;
          }

          console.warn(
            `Failed to scroll to block ${toBlockIdx} after ${maxAttempts} attempts`
          );
          return false;
        };

        // If we changed the transcript, wait a bit for the UI to update before scrolling
        if (needsTranscriptChange) {
          setTimeout(() => tryScrolling(), 100);
        } else {
          tryScrolling();
        }
      },
      [
        scrollNode,
        secondary,
        otherAgentRunRef,
        transcriptKeys,
        selectedTranscriptKey,
      ]
    );

    React.useImperativeHandle(
      ref,
      () => ({
        scrollToBlock,
      }),
      [scrollToBlock]
    );

    /**
     * Block navigation
     */

    const goToNextBlock = useCallback(() => {
      if (!transcript) return;

      const nextIndex =
        currentBlockIndex !== null
          ? Math.min(currentBlockIndex + 1, transcript.messages.length - 1)
          : 0;

      scrollToBlock(nextIndex, secondary ? 1 : 0);
    }, [currentBlockIndex, transcript, scrollToBlock]);
    const goToPrevBlock = useCallback(() => {
      if (!transcript) return;

      const prevIndex =
        currentBlockIndex !== null ? Math.max(currentBlockIndex - 1, 0) : 0;

      scrollToBlock(prevIndex, secondary ? 1 : 0);
    }, [currentBlockIndex, transcript, scrollToBlock]);

    return (
      <Card className="h-full flex-1 p-3 min-h-0 min-w-0 flex flex-col space-y-3">
        {/* Header area Content */}
        {agentRun && (
          <>
            <div>
              <div className="flex items-center space-x-1">
                <div className="font-semibold text-sm">Agent Run</div>
                <UuidPill uuid={agentRun?.id} />
                {agentRun && (
                  <MetadataDialog
                    metadata={agentRun.metadata}
                    title="Agent Run Metadata"
                  />
                )}
              </div>
              <div className="border-gray-100 text-xs text-gray-500 flex items-center overflow-hidden truncate">
                {Object.entries(agentRun.metadata).map(
                  ([key, value]) =>
                    key !== 'run_id' && (
                      <span key={key} className="mr-3">
                        <span className="font-medium text-gray-600">
                          {key}:
                        </span>{' '}
                        {formatMetadataValue(value)}
                      </span>
                    )
                )}
              </div>
            </div>
            <div className="flex flex-1 min-h-0 w-full space-x-2 overflow-hidden relative">
              {/* Transcript List Sidebar */}
              {transcriptKeys.length > 1 && (
                <>
                  <div className="w-24 flex-shrink-0">
                    <div className="text-xs font-medium text-gray-600 mb-2">
                      Transcripts
                    </div>
                    <div className="space-y-1">
                      {transcriptKeys.map((transcriptKey) => (
                        <div
                          key={transcriptKey}
                          className={`flex items-center w-full text-xs rounded border transition-colors ${
                            selectedTranscriptKey === transcriptKey
                              ? 'bg-blue-100 border-blue-300 text-blue-800'
                              : 'bg-gray-50 border-gray-200 text-gray-700 hover:bg-gray-100'
                          }`}
                        >
                          <button
                            onClick={() =>
                              setSelectedTranscriptKey(transcriptKey)
                            }
                            className="flex-1 text-left px-2 py-1 text-ellipsis whitespace-nowrap overflow-hidden"
                            title={transcriptKey}
                          >
                            {transcriptKey}
                          </button>
                          <div className="pr-1">
                            <MetadataDialog
                              metadata={
                                agentRun?.transcripts[transcriptKey]
                                  ?.metadata || {}
                              }
                              title={`Transcript Metadata - ${transcriptKey}`}
                              trigger={
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <button
                                      className={`p-0.5 rounded transition-colors ${
                                        selectedTranscriptKey === transcriptKey
                                          ? 'hover:bg-blue-200 text-blue-600'
                                          : 'hover:bg-gray-200 text-gray-500'
                                      }`}
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      <FileText className="h-3 w-3" />
                                    </button>
                                  </TooltipTrigger>
                                  <TooltipContent side="left" align="center">
                                    <p>View transcript metadata</p>
                                  </TooltipContent>
                                </Tooltip>
                              }
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="border-r border-gray-200 " />
                </>
              )}

              {transcript && (
                <>
                  {/* Transcript content */}
                  <div
                    className="space-y-2 overflow-y-auto custom-scrollbar flex-1"
                    ref={scrollContainerRef}
                  >
                    {transcript.messages.map((message, index) => (
                      <MessageBox
                        key={index}
                        message={message}
                        index={index}
                        id={`r-${secondary ? 1 : 0}_t-${transcriptIdx}_b-${index}`}
                        agentRun={agentRun}
                        scrollToBlock={scrollToBlock}
                      />
                    ))}
                  </div>

                  {/* Navigation buttons inside the ScrollArea (relative to parent container) */}
                  <div className="absolute bottom-3 right-6 flex flex-col gap-1">
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
                </>
              )}
            </div>
          </>
        )}
        {!agentRun && (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
          </div>
        )}
      </Card>
    );
  }
);

// Add display name for forwardRef
AgentRunViewer.displayName = 'AgentRunViewer';

export default AgentRunViewer;

// Add AttributeDisplay component to show attributes below citations
const AttributeDisplay: React.FC<{
  agentRunId: string;
  blockIndex: number;
  scrollToBlock?: (blockIndex: number, transcriptIdx?: number) => void;
}> = ({ agentRunId, blockIndex, scrollToBlock }) => {
  const { curSearchQuery, searchResultMap } = useAppSelector(
    (state) => state.search
  );

  // Get all attributes that reference this specific block
  const relevantAttributes = useMemo(() => {
    if (!curSearchQuery || !searchResultMap || !searchResultMap[agentRunId]) {
      return [];
    }
    const attributes = searchResultMap[agentRunId]?.[curSearchQuery].filter(
      (attr) => attr.value !== null
    );
    if (!attributes) {
      return [];
    }
    return attributes.filter((attr) =>
      attr.citations?.some((citation) => citation.block_idx === blockIndex)
    );
  }, [searchResultMap, agentRunId, curSearchQuery, blockIndex]);
  if (relevantAttributes.length === 0) {
    return null;
  }

  const handleShareAttribute = () => {
    if (!curSearchQuery) {
      toast({
        title: 'Error',
        description: 'Attribute Dimension ID not found.',
        variant: 'destructive',
      });
      return;
    }

    const currentUrl = new URL(window.location.href);
    currentUrl.searchParams.set('searchQuery', curSearchQuery);

    navigator.clipboard
      .writeText(currentUrl.toString())
      .then(() => {
        toast({
          title: 'Search URL copied',
          description: 'Copied a shareable link to the clipboard',
          variant: 'default',
        });
      })
      .catch(() => {
        toast({
          title: 'Failed to copy',
          description: 'Could not copy to clipboard',
          variant: 'destructive',
        });
      });
  };

  // Render the attribute section with exact same styling as InnerCard.tsx
  return (
    <div className="ml-6 mt-2 mb-3 pt-1.5 border-t border-indigo-100 text-xs">
      <div className="flex items-center mb-1">
        <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
        <span className="text-xs font-medium text-indigo-700">
          Attributes from your query
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5 ml-auto"
          onClick={handleShareAttribute}
          title="Share attribute search"
        >
          <Share2 className="h-3 w-3 text-indigo-600 hover:text-indigo-800" />
        </Button>
      </div>

      <div>
        {relevantAttributes.map((attribute, idx) => {
          const attributeValue = attribute.value;
          if (!attributeValue) {
            return null;
          }

          // Use all citations for the attribute, not just those for this block
          const citations = attribute.citations || [];

          // Create a component that renders text with citations highlighted
          const renderTextWithCitations = () => {
            if (!citations.length) {
              return attributeValue;
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
                    {attributeValue.slice(lastIndex, citation.start_idx)}
                  </span>
                );
              }

              // Add the cited text as a clickable element
              const citedText = attributeValue.slice(
                citation.start_idx,
                citation.end_idx
              );
              // Use different style for current block vs. other blocks
              parts.push(
                <button
                  key={`citation-${i}`}
                  className={`px-0.5 py-0.25 bg-indigo-200 text-indigo-800 hover:bg-indigo-400 rounded hover:text-white transition-colors font-medium`}
                  onClick={(e) => {
                    e.stopPropagation();
                    scrollToBlock?.(
                      citation.block_idx,
                      citation.transcript_idx || undefined
                    );
                  }}
                >
                  {citedText}
                </button>
              );

              lastIndex = citation.end_idx;
            });

            // Add any remaining text
            if (lastIndex < attributeValue.length) {
              parts.push(
                <span key={`text-end`}>{attributeValue.slice(lastIndex)}</span>
              );
            }

            return <>{parts}</>;
          };

          return (
            <div
              key={`${curSearchQuery}-${idx}`}
              className="group bg-indigo-50 rounded-md p-1 text-xs text-indigo-900 leading-snug mt-1 hover:bg-indigo-100 transition-colors border border-transparent hover:border-indigo-200"
            >
              <p className="mb-0.5">{renderTextWithCitations()}</p>
              <div className="flex items-center gap-1 text-[10px] text-indigo-600 mt-1">
                <span className="opacity-70">{curSearchQuery}</span>
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
  agentRun: AgentRun;
  scrollToBlock: (blockIndex: number, transcriptIdx?: number) => void;
}> = ({ message, index, id, agentRun, scrollToBlock }) => {
  const agentRunId = agentRun.id;

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

  return (
    <div className="mb-1">
      <div id={id} className={`p-2 rounded-md text-sm ${getRoleStyle()}`}>
        <div className="text-[10px] text-gray-600 flex justify-between mb-1">
          <span>
            Block {index} |{' '}
            {message.role.charAt(0).toUpperCase() + message.role.slice(1)}
          </span>
        </div>

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
      </div>

      <AttributeDisplay
        agentRunId={agentRunId}
        blockIndex={index}
        scrollToBlock={scrollToBlock}
      />
    </div>
  );
};
