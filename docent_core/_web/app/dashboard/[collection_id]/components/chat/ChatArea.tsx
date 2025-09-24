'use client';

import { useScrollToBottom } from '@/app/hooks/use-scroll-to-bottom';
import { motion } from 'framer-motion';

import { useEffect, useMemo, useRef, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { ChatMessage } from '@/app/types/transcriptTypes';
import { ChatMessage as ChatMessageComponent } from './ChatMessage';
import InputArea from './InputArea';

export type SuggestedMessage = string | { label: string; message: string };

interface ChatAreaProps {
  isReadonly: boolean;
  messages: ChatMessage[];
  onSendMessage: (message: string) => void;
  onCancelMessage?: () => void;
  onRetry?: () => void;
  isSendingMessage?: boolean;
  headerElement?: ReactNode;
  suggestedMessages?: SuggestedMessage[];
  byoFlexDiv: boolean;
  __showThinkingSpacerAfterFirstMessage?: boolean;
  inputAreaFooter?: ReactNode;
  inputHeaderElement?: ReactNode;
  inputErrorMessage?: string;
  scrollContainerClassName?: string;
  inputAreaClassName?: string;
}

export function ChatArea({
  isReadonly,
  messages,
  onSendMessage,
  onCancelMessage,
  onRetry,
  isSendingMessage = false,
  headerElement,
  suggestedMessages,
  byoFlexDiv = false,
  __showThinkingSpacerAfterFirstMessage = false,
  inputAreaFooter,
  inputErrorMessage,
  inputHeaderElement,
  scrollContainerClassName,
  inputAreaClassName,
}: ChatAreaProps) {
  const {
    isAtBottom,
    containerRef,
    endRef,
    onViewportEnter,
    onViewportLeave,
    scrollToBottom,
  } = useScrollToBottom();

  // Scroll to bottom after messages load
  const didInitialScrollRef = useRef(false);
  useEffect(() => {
    if (!didInitialScrollRef.current && messages && messages.length > 0) {
      didInitialScrollRef.current = true;
      scrollToBottom('auto');
    }
  }, [messages, scrollToBottom]);

  const lastMessage = messages[messages.length - 1];
  const showThinkingSpacer =
    (isSendingMessage &&
      lastMessage?.role !== 'assistant' &&
      lastMessage?.role !== 'tool') ||
    (messages.length === 1 && __showThinkingSpacerAfterFirstMessage);

  // Index of the currently streaming message (if any)
  const streamingMessageIdx =
    isSendingMessage && messages.length > 0 ? messages.length - 1 : undefined;

  // Define messages to display
  const displayedMessages = useMemo(() => {
    const ans = messages.map((message, index) => (
      <ChatMessageComponent
        key={index}
        message={message}
        isLoadingPlaceholder={false}
        isStreaming={index === streamingMessageIdx}
        requiresScrollPadding={
          isSendingMessage &&
          !showThinkingSpacer &&
          index === messages.length - 1 &&
          message.role === 'assistant'
        }
      />
    ));
    if (showThinkingSpacer) {
      ans.push(
        <ChatMessageComponent
          key="thinking-spacer"
          message={{
            role: 'assistant',
            content: 'Thinking...',
          }}
          isLoadingPlaceholder={true}
          isStreaming={true}
          requiresScrollPadding={true}
        />
      );
    }
    return ans;
  }, [messages, showThinkingSpacer, isSendingMessage, streamingMessageIdx]);

  // Auto-scroll when the thinking spacer first appears in the message history (i.e., upon send)
  const lastMessageIsThinkingSpacer = useMemo(() => {
    return (
      displayedMessages.length > 0 &&
      displayedMessages[displayedMessages.length - 1].props.isLoadingPlaceholder
    );
  }, [displayedMessages]);
  useEffect(() => {
    if (lastMessageIsThinkingSpacer) {
      // Small delay to ensure the thinking spacer is visible
      setTimeout(() => scrollToBottom('smooth'), 100);
    }
  }, [lastMessageIsThinkingSpacer, scrollToBottom]);

  // Extract suggested messages from the last assistant message
  const finalSuggestedMessages = (() => {
    if (isSendingMessage) {
      return [];
    }
    // Use hardcoded suggestions at start of chat
    if (messages.length === 0) {
      return suggestedMessages;
    }

    const lastMsg = messages[messages.length - 1];
    if (
      lastMsg.role === 'assistant' &&
      lastMsg.suggested_messages &&
      lastMsg.suggested_messages.length > 0
    ) {
      return lastMsg.suggested_messages;
    }

    // Fall back to provided suggestions if no assistant suggestions found
    return suggestedMessages;
  })();

  const coreComponent = (
    <>
      <div
        className={cn(
          'flex-1 flex flex-col min-w-0 gap-3 overflow-y-scroll relative custom-scrollbar',
          scrollContainerClassName
        )}
        ref={containerRef}
      >
        {headerElement}
        {displayedMessages}
        {/* Suggestions row at the end of the chat */}
        {finalSuggestedMessages &&
          !isReadonly &&
          finalSuggestedMessages.length > 0 &&
          onSendMessage && (
            <div className="w-full mx-auto">
              <div className="flex flex-col items-start flex-wrap gap-2">
                {finalSuggestedMessages.map((s, i) => {
                  const label = typeof s === 'string' ? s : s.label;
                  const messageToSend = typeof s === 'string' ? s : s.message;
                  return (
                    <button
                      key={`sugg-${i}`}
                      type="button"
                      className="text-xs px-3 py-2 text-left rounded-lg w-full border border-border text-primary bg-secondary hover:bg-primary/10 transition-colors"
                      onClick={(e) => {
                        e.preventDefault();
                        onSendMessage(messageToSend);
                      }}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        {/* Sentinel to detect when viewport is at the bottom and to provide a scroll target */}
        <motion.div
          ref={endRef}
          onViewportEnter={onViewportEnter}
          onViewportLeave={onViewportLeave}
          className="min-h-1"
          data-testid="messages-end"
        />
      </div>

      <form
        className={cn(
          'flex mx-auto bg-background gap-2 w-full',
          inputAreaClassName
        )}
      >
        <InputArea
          onSendMessage={onSendMessage}
          disabled={isReadonly}
          isSendingMessage={isSendingMessage}
          onCancelMessage={onCancelMessage}
          onRetry={onRetry}
          footer={inputAreaFooter}
          errorMessage={inputErrorMessage}
          inputHeaderElement={inputHeaderElement}
        />
      </form>
    </>
  );

  if (byoFlexDiv) {
    return coreComponent;
  } else {
    return (
      <div className="flex-1 flex flex-col min-w-0 bg-background">
        {coreComponent}
      </div>
    );
  }
}
