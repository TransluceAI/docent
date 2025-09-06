'use client';

import { SparklesIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import Markdown from './Markdown';
import {
  ChatMessage as ChatMessageType,
  Content as ChatContent,
} from '@/app/types/transcriptTypes';
import {
  MarkdownWithCitations,
  NavigateToCitation,
} from '@/components/CitationRenderer';
import posthog from 'posthog-js';

interface ChatMessageProps {
  message: ChatMessageType;
  isLoadingPlaceholder: boolean;
  requiresScrollPadding: boolean;
  hideAssistantAvatar?: boolean;
  onNavigateToCitation?: NavigateToCitation;
}

export function ChatMessage({
  message,
  isLoadingPlaceholder,
  requiresScrollPadding,
  hideAssistantAvatar = false,
  onNavigateToCitation,
}: ChatMessageProps) {
  // Render tool messages in the same style as tool calls
  const renderToolMessage = () => {
    if (message.role !== 'tool') return null;
    const contentList = Array.isArray(message.content)
      ? message.content
      : ([{ type: 'text', text: message.content }] as ChatContent[]);
    const contentText = contentList
      .map((part) => {
        if (part.type === 'text') return part.text ?? '';
        if (part.type === 'reasoning') return part.reasoning ?? '';
        return '';
      })
      .filter((t) => (t || '').trim() !== '')
      .join('\n\n');

    return (
      <div className="mt-1 p-1.5 bg-secondary/85 rounded text-xs break-all whitespace-pre-wrap">
        <div className="text-[10px] text-muted-foreground mb-0.5">
          {message.tool_call_id ? (
            <>Tool Call ID: {message.tool_call_id}</>
          ) : (
            <>Tool Message</>
          )}
        </div>
        <div className="font-mono">
          {message.function && (
            <span className="font-semibold">{message.function}</span>
          )}
          {message.error && (
            <div className="mt-1 text-red-text">
              Error: {message.error.message}
            </div>
          )}
        </div>
        {contentText && (
          <div className="mt-1 font-mono whitespace-pre-wrap break-all">
            {contentText}
          </div>
        )}
      </div>
    );
  };

  // Render tool calls attached to assistant messages
  const renderToolCalls = () => {
    if (
      message.role === 'assistant' &&
      'tool_calls' in message &&
      message.tool_calls
    ) {
      return message.tool_calls.map((tool, i) => (
        <div
          key={i}
          className="mt-1 p-1.5 bg-secondary/85 rounded text-xs break-all whitespace-pre-wrap"
        >
          <div className="text-[10px] text-muted-foreground mb-0.5">
            Tool Call ID: {tool.id}
          </div>
          {tool.view ? (
            <span className="font-mono">{tool.view.content}</span>
          ) : (
            <div className="font-mono">
              <span className="font-semibold">{tool.function}</span>
              <span className="text-muted-foreground">
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
      className={cn('group/message text-sm w-full mx-auto max-w-4xl')}
      data-role={message.role}
    >
      <div
        className={cn(
          'flex gap-4 w-full group-data-[role=user]/message:ml-auto group-data-[role=user]/message:max-w-2xl group-data-[role=user]/message:w-fit'
        )}
      >
        {(message.role === 'assistant' || message.role === 'tool') &&
          !hideAssistantAvatar && (
            <div className="size-8 flex items-center rounded-full justify-center ring-1 shrink-0 ring-border bg-background">
              <div className="translate-y-px">
                <SparklesIcon size={14} />
              </div>
            </div>
          )}

        <div
          className={cn('flex flex-col gap-4 w-full', {
            'min-h-64': message.role === 'assistant' && requiresScrollPadding,
          })}
        >
          {(() => {
            // For tool messages, render the styled panel inside a standard bubble
            if (message.role === 'tool') {
              return renderBubble('tool-message', renderToolMessage());
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
                        onNavigate={({ citation, newTab }) => {
                          if (citation) {
                            posthog.capture('citation_clicked', {
                              source: 'chat',
                              transcript_idx: citation.transcript_idx,
                              block_idx: citation.block_idx,
                              start_pattern: citation.start_pattern,
                            });
                          }
                          if (onNavigateToCitation) {
                            onNavigateToCitation({ citation, newTab });
                          }
                        }}
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
