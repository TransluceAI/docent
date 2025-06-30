'use client';

import { CornerDownLeft, Loader2, RotateCcw } from 'lucide-react';
import React, { useEffect, useState, useRef, useCallback } from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  createTaSession,
  loadTaSession,
  resetTaSession,
  sendTaMessage,
  getTaSessionStorageKey,
} from '@/app/store/transcriptSlice';
import { AgentRun, TaMessage } from '@/app/types/transcriptTypes';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { toast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';

const getTaInputStorageKey = (agentRunId: string) => `ta-input-${agentRunId}`;

interface TaPanelProps {
  onShowAgentRun?: (agentRunId: string, blockId: number) => void;
}

interface MessageBubbleProps {
  message: TaMessage;
  onShowAgentRun?: (agentRunId: string, blockId: number) => void;
  curAgentRun?: AgentRun;
}

function MessageBubble({
  message,
  onShowAgentRun,
  curAgentRun,
}: MessageBubbleProps) {
  return (
    <div
      className={cn(
        'flex w-full mt-2',
        message.role === 'user' ? 'justify-end' : 'justify-start'
      )}
    >
      <div
        className={cn(
          'rounded-md px-3 py-2 max-w-[85%]',
          message.role === 'user'
            ? 'bg-primary text-primary-foreground'
            : 'bg-secondary border shadow-sm'
        )}
      >
        <div className="text-sm leading-normal whitespace-pre-wrap break-words">
          {message.role === 'assistant' &&
            message.citations &&
            message.citations.length > 0 ? (
            <>
              {message.citations.reduce((acc, citation, i) => {
                const parts = [];

                // Add text before the citation
                if (i === 0) {
                  parts.push(
                    <span key={`text-start-${i}`}>
                      {message.content.slice(0, citation.start_idx)}
                    </span>
                  );
                } else {
                  parts.push(
                    <span key={`text-between-${i}`}>
                      {message.content.slice(
                        message.citations![i - 1].end_idx,
                        citation.start_idx
                      )}
                    </span>
                  );
                }

                // Add the citation
                parts.push(
                  <button
                    key={`citation-${i}`}
                    onClick={() => {
                      onShowAgentRun?.(
                        curAgentRun?.id ?? '',
                        citation.block_idx
                      );
                    }}
                    className="text-blue-600 hover:text-blue-800 hover:underline font-semibold px-0.5 break-words"
                    title={`Show block ${citation.block_idx} from datapoint ${curAgentRun?.id}`}
                  >
                    {message.content.slice(
                      citation.start_idx,
                      citation.end_idx
                    )}
                  </button>
                );

                // Add remaining text after the last citation
                if (i === message.citations!.length - 1) {
                  parts.push(
                    <span key={`text-end-${i}`}>
                      {message.content.slice(citation.end_idx)}
                    </span>
                  );
                }

                return [...acc, ...parts];
              }, [] as JSX.Element[])}
            </>
          ) : (
            <span>{message.content}</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function TaPanel({ onShowAgentRun }: TaPanelProps) {
  const dispatch = useAppDispatch();

  const curAgentRun = useAppSelector((state) => state.transcript.curAgentRun);
  const taAgentRunId = useAppSelector((state) => state.transcript.taAgentRunId);
  const taSessionId = useAppSelector((state) => state.transcript.taSessionId);
  const taMessages = useAppSelector((state) => state.transcript.taMessages);
  const loadingTaResponse = useAppSelector(
    (state) => state.transcript.loadingTaResponse
  );

  const [inputValue, setInputValue] = useState('');
  const inputValueRef = useRef(inputValue);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      const container = messagesContainerRef.current;
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    }, 0);
  }, []);

  const isScrolledToBottom = useCallback(() => {
    const container = messagesContainerRef.current;
    if (!container) return true;

    const threshold = 10;
    return (
      container.scrollTop + container.clientHeight >=
      container.scrollHeight - threshold
    );
  }, []);

  // Update auto-scroll preference when user manually scrolls
  const handleScroll = useCallback(() => {
    shouldAutoScrollRef.current = isScrolledToBottom();
  }, [isScrolledToBottom]);

  // Always scroll to bottom for new session
  useEffect(() => {
    if (taSessionId) {
      shouldAutoScrollRef.current = true;
      scrollToBottom();
    }
  }, [taSessionId, scrollToBottom]);

  // Scroll to bottom for new messages, if already scrolled to bottom
  useEffect(() => {
    if (shouldAutoScrollRef.current) {
      scrollToBottom();
    }
  }, [taMessages, loadingTaResponse, scrollToBottom]);

  // Keep ref in sync with state
  useEffect(() => {
    inputValueRef.current = inputValue;
  }, [inputValue]);

  // Handle localStorage for message drafts
  useEffect(() => {
    if (curAgentRun?.id) {
      // Load message draft from localStorage if it exists
      const savedDraft = localStorage.getItem(
        getTaInputStorageKey(curAgentRun.id)
      );
      setInputValue(savedDraft || '');
    }

    return () => {
      // Save message draft to localStorage on unmount
      if (curAgentRun?.id && inputValueRef.current.trim() !== '') {
        localStorage.setItem(
          getTaInputStorageKey(curAgentRun.id),
          inputValueRef.current
        );
      }
    };
  }, [curAgentRun?.id]);

  // Save message draft to localStorage before page unload
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (curAgentRun?.id && inputValueRef.current.trim() !== '') {
        localStorage.setItem(
          getTaInputStorageKey(curAgentRun.id),
          inputValueRef.current
        );
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [curAgentRun?.id]);

  // Initialize the TA session when datapoint changes
  useEffect(() => {
    if (curAgentRun?.id) {
      const currentAgentRunId = curAgentRun.id;

      // Check if the datapoint has changed from the one we're chatting about
      if (taAgentRunId !== currentAgentRunId) {
        const savedSessionId = localStorage.getItem(
          getTaSessionStorageKey(currentAgentRunId)
        );

        if (savedSessionId) {
          dispatch(
            loadTaSession({
              agentRunId: curAgentRun.id,
              sessionId: savedSessionId,
            })
          );
        } else {
          // Clear the messages when datapoint changes and no existing session
          dispatch(resetTaSession());

          // Create a new TA session with the current datapoint
          const success = dispatch(createTaSession(currentAgentRunId));
          if (!success) {
            toast({
              title: 'Error',
              description: 'Failed to create TA session',
              variant: 'destructive',
            });
          }
        }
      }
    }
  }, [curAgentRun?.id, taAgentRunId, dispatch]);

  const handleSendMessage = () => {
    if (loadingTaResponse) {
      return;
    }

    if (inputValue.trim() === '') {
      return;
    }

    if (!taSessionId) {
      toast({
        title: 'Error',
        description: 'No active TA session',
        variant: 'destructive',
      });
      return;
    }

    dispatch(sendTaMessage(inputValue));
    setInputValue('');

    // Clear from localStorage after sending
    if (curAgentRun?.id) {
      localStorage.removeItem(getTaInputStorageKey(curAgentRun.id));
    }

    scrollToBottom();
  };

  const handleClearChatHistory = () => {
    if (curAgentRun?.id) {
      const currentAgentRunId = curAgentRun.id;

      // Clear session ID from localStorage
      localStorage.removeItem(getTaSessionStorageKey(currentAgentRunId));

      // Reset the entire session (clears server and client state)
      dispatch(resetTaSession());

      // Create a new fresh session
      dispatch(createTaSession(currentAgentRunId));
    }
  };

  return (
    <div className="flex flex-col h-full space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <h4 className="font-semibold text-sm">Transcript Chat</h4>
          <span className="text-xs text-muted-foreground">Ask questions about transcript</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleClearChatHistory}
          disabled={!taMessages || taMessages.length === 0}
          className="h-7 px-2 text-xs"
          title="Clear chat history"
        >
          <RotateCcw className="h-4 w-4" />
        </Button>
      </div>
      {/* Plain div because ScrollArea uses "display: table" which breaks this layout */}
      <div
        ref={messagesContainerRef}
        onScroll={handleScroll}
        className="flex-1 min-h-0 bg-background rounded-lg border p-2 overflow-y-auto"
      >
        {taMessages?.map(
          (message, index) =>
            message.content.length > 0 && (
              <MessageBubble
                key={index}
                message={message}
                onShowAgentRun={onShowAgentRun}
                curAgentRun={curAgentRun}
              />
            )
        )}
        {loadingTaResponse && (
          <div className="flex w-full mt-2 justify-start">
            <div className="rounded-md px-3 py-2 bg-background border shadow-sm">
              <div className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                <span className="text-sm text-muted-foreground">
                  Thinking...
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
      <div>
        <form
          className="relative overflow-hidden bg-background"
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
        >
          <fieldset
            disabled={!taSessionId}
            className="flex flex-row space-x-2 items-end"
          >
            <div className="relative flex-1">
              <Textarea
                placeholder={
                  taSessionId
                    ? 'Enter a question...'
                    : 'Apply a base collection to start chatting...'
                }
                className="rounded-md border bg-secondary resize-none shadow-none focus-visible:ring-0 max-h-64 overflow-y-auto pr-12"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
              />
              <Button
                type="submit"
                size="sm"
                className="absolute bottom-2 right-2 h-7 w-8 p-0"
                disabled={inputValue === '' || !taSessionId || loadingTaResponse}
              >
                <CornerDownLeft className="size-4" />
              </Button>
            </div>
          </fieldset>
        </form>
      </div>
    </div>
  );
}
