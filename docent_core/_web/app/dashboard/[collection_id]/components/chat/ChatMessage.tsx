'use client';

import { cn } from '@/lib/utils';
import Markdown from './Markdown';
import {
  ChatMessage as ChatMessageType,
  Content as ChatContent,
  ToolMessage,
} from '@/app/types/transcriptTypes';
import { MarkdownWithCitations } from '@/components/CitationRenderer';
import ToolCallMessage from './ToolCallMessage';

interface ChatMessageProps {
  message: ChatMessageType;
  toolOutputs?: Map<string, ToolMessage>;
  isLoadingPlaceholder: boolean;
  requiresScrollPadding: boolean;
  isStreaming?: boolean;
}

function parseDocentUserMessage(text: string): string {
  const match = text.match(
    /<docent_user_message>([\s\S]*?)<\/docent_user_message>/
  );
  return match ? match[1].trim() : text;
}

export function ChatMessage({
  message,
  toolOutputs,
  isLoadingPlaceholder,
  requiresScrollPadding,
  isStreaming = false,
}: ChatMessageProps) {
  const isStreamingThisMessage = !!isStreaming;

  // Render tool calls attached to assistant messages, including their outputs
  const renderToolCalls = () => {
    if (
      message.role === 'assistant' &&
      'tool_calls' in message &&
      message.tool_calls
    ) {
      return message.tool_calls.map((tool, i) => (
        <ToolCallMessage
          key={i}
          tool={tool}
          toolOutput={toolOutputs?.get(tool.id)}
          isStreaming={isStreamingThisMessage}
        />
      ));
    }
    return null;
  };

  const renderBubble = (key: string | number, children: React.ReactNode) => (
    <div key={key} className="flex flex-row gap-2 items-start">
      <div
        data-testid="message-content"
        className={cn('flex flex-col gap-4 min-w-0', {
          'bg-primary text-primary-foreground px-3 py-2 rounded-xl':
            message.role === 'user',
        })}
      >
        {children}
      </div>
    </div>
  );

  return (
    <div
      className={cn('group/message text-sm w-full mx-auto')}
      data-role={message.role}
    >
      <div
        className={cn(
          'flex gap-4 w-full group-data-[role=user]/message:ml-auto group-data-[role=user]/message:max-w-2xl group-data-[role=user]/message:w-fit'
        )}
      >
        <div
          className={cn('flex flex-col gap-4 w-full', {
            'min-h-64': message.role === 'assistant' && requiresScrollPadding,
          })}
        >
          {(() => {
            // Skip tool messages - they're rendered as part of tool calls
            if (message.role === 'tool') {
              return null;
            }

            const contentList = Array.isArray(message.content)
              ? message.content
              : [{ type: 'text', text: message.content } as ChatContent];

            const parts = contentList.map((part, index) => {
              const key = `message-part-${index}`;
              if (part.type === 'reasoning') {
                const text = part.reasoning ?? '';
                if (!text.trim()) return null;
                return renderBubble(
                  key,
                  <div className="text-muted-foreground">{text}</div>
                );
              }
              if (part.type === 'text') {
                const text = part.text ?? '';
                if (!text.trim()) return null;
                if (isLoadingPlaceholder) {
                  return renderBubble(
                    key,
                    <div className="animate-pulse text-muted-foreground">
                      {text}
                    </div>
                  );
                }
                if (message.role === 'user') {
                  return renderBubble(
                    key,
                    <Markdown>{parseDocentUserMessage(text)}</Markdown>
                  );
                }
                // For assistant messages, render with both markdown and citations support
                if (message.role === 'assistant') {
                  const citations =
                    'citations' in message && Array.isArray(message.citations)
                      ? message.citations
                      : [];

                  return renderBubble(
                    key,
                    <div className="leading-normal whitespace-pre-wrap break-words">
                      <MarkdownWithCitations
                        text={text}
                        citations={citations}
                      />
                    </div>
                  );
                }
                return renderBubble(key, <Markdown>{text}</Markdown>);
              }
              // ignore images and unknown types for now
              return null;
            });
            return parts;
          })()}
          {renderToolCalls()}
        </div>
      </div>
    </div>
  );
}
