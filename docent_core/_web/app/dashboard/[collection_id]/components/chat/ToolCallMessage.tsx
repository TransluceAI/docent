'use client';

import { useState } from 'react';
import { Loader2, ChevronRight, ChevronDown, X } from 'lucide-react';
import {
  ToolCall,
  ToolMessage,
  Content as ChatContent,
} from '@/app/types/transcriptTypes';

export default function ToolCallMessage({
  tool,
  toolOutput,
  isStreaming = false,
}: {
  tool: ToolCall;
  toolOutput?: ToolMessage;
  isStreaming?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isOutputExpanded, setIsOutputExpanded] = useState(false);

  const getToolData = () => {
    if (tool.type === 'custom') {
      return tool.input || '';
    } else {
      // Function tool call
      const args = tool.arguments || {};
      if (typeof args === 'string') {
        return args;
      }
      return Object.entries(args)
        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
        .join(', ');
    }
  };

  const isExpandable = () => {
    if (tool.type === 'custom') {
      return tool.input && tool.input.length > 0;
    } else {
      const args = tool.arguments;
      if (!args) return false;
      if (typeof args === 'string') return args.length > 0;
      return Object.keys(args).length > 0;
    }
  };

  // Get output content text from tool output message
  const getOutputContent = () => {
    if (!toolOutput) return '';
    const contentList = Array.isArray(toolOutput.content)
      ? toolOutput.content
      : ([{ type: 'text', text: toolOutput.content }] as ChatContent[]);
    return contentList
      .map((part) => {
        if (part.type === 'text') return part.text ?? '';
        if (part.type === 'reasoning') return part.reasoning ?? '';
        return '';
      })
      .filter((t) => (t || '').trim() !== '')
      .join('\n\n');
  };

  const outputContent = getOutputContent();
  const outputLineCount = outputContent ? outputContent.split('\n').length : 0;
  const outputLineLabel =
    outputLineCount === 1 ? '1 line' : `${outputLineCount} lines`;
  const hasOutputError = !!toolOutput?.error;

  return (
    <div className="mt-1 p-1.5 bg-secondary/85 rounded text-xs break-all whitespace-pre-wrap">
      <div className="text-[10px] text-muted-foreground mb-0.5">
        Tool Call ID: {tool.id}
      </div>
      <div className="font-mono">
        {isExpandable() ? (
          <button
            type="button"
            className="w-full text-left flex items-center hover:opacity-80"
            onClick={() => setIsExpanded((v) => !v)}
          >
            <span className="flex items-center gap-1.5 font-semibold">
              {isExpanded ? (
                <ChevronDown size={12} className="text-muted-foreground" />
              ) : (
                <ChevronRight size={12} className="text-muted-foreground" />
              )}
              {isStreaming && (
                <Loader2
                  size={12}
                  className="animate-spin text-muted-foreground"
                />
              )}
              {tool.function}
            </span>
            <span className="text-muted-foreground">(...)</span>
          </button>
        ) : (
          <span className="flex items-center gap-1.5 font-semibold">
            {isStreaming && (
              <Loader2
                size={12}
                className="animate-spin text-muted-foreground"
              />
            )}
            {tool.function}()
          </span>
        )}

        {isExpanded &&
          (tool.view ? (
            <span className="font-mono">{tool.view.content}</span>
          ) : (
            <div className="mt-1 text-muted-foreground">{getToolData()}</div>
          ))}
      </div>

      {/* Tool output section */}
      {toolOutput && (
        <div className="mt-1.5 ml-3 pl-2 border-l border-border">
          <button
            type="button"
            className="w-full text-left flex items-center gap-1 hover:opacity-80 font-mono"
            onClick={() => setIsOutputExpanded((v) => !v)}
          >
            {isOutputExpanded ? (
              <ChevronDown size={12} className="text-muted-foreground" />
            ) : (
              <ChevronRight size={12} className="text-muted-foreground" />
            )}
            {hasOutputError && <X size={12} className="text-red-text" />}
            <span className="text-muted-foreground">Output</span>
            <span className="text-muted-foreground">[{outputLineLabel}]</span>
          </button>
          {isOutputExpanded && (
            <div className="mt-1 ml-4">
              {hasOutputError && (
                <div className="text-red-text font-mono">
                  Error: {toolOutput.error?.message}
                </div>
              )}
              {outputContent && (
                <div className="mt-1 font-mono whitespace-pre-wrap break-all text-muted-foreground">
                  {outputContent}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
