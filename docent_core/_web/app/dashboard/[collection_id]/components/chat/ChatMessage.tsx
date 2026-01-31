'use client';

import { useState } from 'react';
import { Check, Copy, FileCode2 } from 'lucide-react';

import { cn, copyToClipboard } from '@/lib/utils';
import Markdown from './Markdown';
import {
  ChatMessage as ChatMessageType,
  Content as ChatContent,
  ToolMessage,
} from '@/app/types/transcriptTypes';
import { MarkdownWithCitations } from '@/components/CitationRenderer';
import ToolCallMessage from './ToolCallMessage';
import { Button } from '@/components/ui/button';

interface DiffMetadata {
  diffContent: string;
  query: string;
  previous_query: string;
  execution: unknown;
  error: string | null;
  used_tables: string[];
}

interface ChatMessageProps {
  message: ChatMessageType;
  toolOutputs?: Map<string, ToolMessage>;
  isLoadingPlaceholder: boolean;
  requiresScrollPadding: boolean;
  isStreaming?: boolean;
  onApplyQuery?: (query: string) => void;
}

function parseDocentUserMessage(text: string): string {
  const match = text.match(
    /<docent_user_message>([\s\S]*?)<\/docent_user_message>/
  );
  return match ? match[1].trim() : text;
}

function DiffViewer({
  metadata,
  onApplyQuery,
}: {
  metadata: DiffMetadata;
  onApplyQuery?: (query: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<
    'before' | 'after' | 'diff' | null
  >(null);
  const [copied, setCopied] = useState(false);

  const handleTabClick = (tab: 'before' | 'after' | 'diff') => {
    setActiveTab((current) => (current === tab ? null : tab));
  };

  const handleCopy = async () => {
    if (!activeTab) return;
    const textToCopy =
      activeTab === 'before'
        ? metadata.previous_query
        : activeTab === 'after'
          ? metadata.query
          : cleanedDiffContent;
    const success = await copyToClipboard(textToCopy);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const cleanedDiffContent = metadata.diffContent
    .split('\n')
    .filter((line) => !line.startsWith('---') && !line.startsWith('+++'))
    .join('\n');

  const renderDiffLine = (line: string, index: number) => {
    if (line.startsWith('+')) {
      return (
        <div
          key={index}
          className="bg-green-bg/30 text-green-text font-mono text-xs whitespace-pre"
        >
          {line}
        </div>
      );
    }
    if (line.startsWith('-')) {
      return (
        <div
          key={index}
          className="bg-red-bg/30 text-red-text font-mono text-xs whitespace-pre"
        >
          {line}
        </div>
      );
    }
    return (
      <div key={index} className="font-mono text-xs whitespace-pre">
        {line}
      </div>
    );
  };

  return (
    <div className="w-full space-y-2">
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <FileCode2 className="h-3.5 w-3.5" />
          <span>Query updated</span>
        </div>
        <div className="flex gap-1 ml-auto">
          {(['before', 'after', 'diff'] as const).map((tab) => (
            <Button
              key={tab}
              variant={activeTab === tab ? 'secondary' : 'ghost'}
              size="sm"
              className="h-6 px-2 text-xs capitalize"
              onClick={() => handleTabClick(tab)}
            >
              {tab}
            </Button>
          ))}
        </div>
      </div>

      {activeTab && (
        <>
          <div className="rounded border bg-muted/30 p-2 max-h-48 overflow-auto">
            {activeTab === 'diff' ? (
              <div className="space-y-0">
                {cleanedDiffContent.split('\n').map(renderDiffLine)}
              </div>
            ) : (
              <pre className="font-mono text-xs whitespace-pre-wrap">
                {activeTab === 'before'
                  ? metadata.previous_query
                  : metadata.query}
              </pre>
            )}
          </div>

          <div className="flex items-center gap-2">
            {onApplyQuery &&
              metadata.query &&
              (activeTab === 'before' || activeTab === 'after') && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-6 text-xs"
                  onClick={() =>
                    onApplyQuery(
                      activeTab === 'before'
                        ? metadata.previous_query
                        : metadata.query
                    )
                  }
                >
                  Apply Query
                </Button>
              )}
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => void handleCopy()}
            >
              {copied ? (
                <>
                  <Check className="h-3 w-3 mr-1" /> Copied
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3 mr-1" /> Copy
                </>
              )}
            </Button>
          </div>
        </>
      )}

      {metadata.error && (
        <div className="text-xs text-red-text bg-red-bg/20 rounded p-2">
          {metadata.error}
        </div>
      )}
    </div>
  );
}

export function ChatMessage({
  message,
  toolOutputs,
  isLoadingPlaceholder,
  requiresScrollPadding,
  isStreaming = false,
  onApplyQuery,
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

            // Check for diff metadata (used by DQL generator)
            const metadata = 'metadata' in message ? message.metadata : null;
            if (
              metadata &&
              typeof metadata === 'object' &&
              'diffContent' in metadata &&
              metadata.diffContent
            ) {
              return (
                <DiffViewer
                  metadata={metadata as unknown as DiffMetadata}
                  onApplyQuery={onApplyQuery}
                />
              );
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
