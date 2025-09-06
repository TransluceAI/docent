'use client';

import { useScrollToBottom } from '@/app/hooks/use-scroll-to-bottom';
import { motion } from 'framer-motion';

import { useEffect, type ReactNode } from 'react';
import { ChatMessage } from '@/app/types/transcriptTypes';
import { NavigateToCitation } from '@/components/CitationRenderer';
import { ChatMessage as ChatMessageComponent } from './ChatMessage';
import InputArea from './InputArea';

export type SuggestedMessage = string | { label: string; message: string };

interface ChatAreaProps {
  isReadonly: boolean;
  messages: ChatMessage[];
  onSendMessage: (message: string) => void;
  isLoading?: boolean;
  headerElement?: ReactNode;
  hideAssistantAvatar?: boolean;
  suggestedMessages?: SuggestedMessage[];
  onNavigateToCitation?: NavigateToCitation;
  byoFlexDiv: boolean;
  __showThinkingSpacerAfterFirstMessage?: boolean;
}

/**
 * TODO(mengk): fix the thinking spacer logic, very hacky right now
 */
export function ChatArea({
  isReadonly,
  messages,
  onSendMessage,
  isLoading = false,
  headerElement,
  hideAssistantAvatar = false,
  suggestedMessages,
  onNavigateToCitation,
  byoFlexDiv = false,
  __showThinkingSpacerAfterFirstMessage = false,
}: ChatAreaProps) {
  const {
    containerRef,
    endRef,
    onViewportEnter,
    onViewportLeave,
    isAtBottom,
    scrollToBottom,
  } = useScrollToBottom();

  const lastMessage = messages[messages.length - 1];
  const showThinkingSpacer =
    (isLoading &&
      lastMessage?.role !== 'assistant' &&
      lastMessage?.role !== 'tool') ||
    (messages.length === 1 && __showThinkingSpacerAfterFirstMessage);

  // Auto-scroll when loading and at bottom
  useEffect(() => {
    if (isLoading && isAtBottom) {
      scrollToBottom('auto');
    }
  }, [messages, isLoading, isAtBottom, scrollToBottom]);

  // Extract suggested messages from the last assistant message
  const finalSuggestedMessages = (() => {
    if (isLoading) {
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
        className="flex-1 flex flex-col min-w-0 gap-3 overflow-y-scroll relative custom-scrollbar"
        ref={containerRef}
      >
        {headerElement}
        {messages.map((message, index) => (
          <ChatMessageComponent
            key={index}
            message={message}
            isLoadingPlaceholder={false}
            requiresScrollPadding={
              !showThinkingSpacer &&
              index === messages.length - 1 &&
              message.role === 'assistant'
            }
            hideAssistantAvatar={hideAssistantAvatar}
            onNavigateToCitation={onNavigateToCitation}
          />
        ))}
        {showThinkingSpacer && (
          <ChatMessageComponent
            message={{
              role: 'assistant',
              content: 'Thinking...',
            }}
            isLoadingPlaceholder={true}
            requiresScrollPadding={true}
            hideAssistantAvatar={hideAssistantAvatar}
            onNavigateToCitation={onNavigateToCitation}
          />
        )}

        {/* Suggestions row at the end of the chat */}
        {finalSuggestedMessages &&
          !isReadonly &&
          finalSuggestedMessages.length > 0 &&
          onSendMessage && (
            <div className="w-full mx-auto max-w-4xl">
              <div className="flex flex-col items-start flex-wrap gap-2">
                {finalSuggestedMessages.map((s, i) => {
                  const label = typeof s === 'string' ? s : s.label;
                  const messageToSend = typeof s === 'string' ? s : s.message;
                  return (
                    <button
                      key={`sugg-${i}`}
                      type="button"
                      className="text-xs px-3 py-2 text-left rounded-xl border border-border text-primary bg-secondary hover:bg-primary/10 transition-colors"
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

      <form className="flex mx-auto bg-background mx-2 gap-2 w-full md:max-w-3xl">
        <InputArea
          onSendMessage={onSendMessage}
          disabled={isLoading || isReadonly}
          isLoading={isLoading}
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
