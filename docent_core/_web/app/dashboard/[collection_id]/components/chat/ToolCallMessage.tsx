'use client';

import { useState } from 'react';
import { Loader2, ChevronRight, ChevronDown } from 'lucide-react';
import { ToolCall } from '@/app/types/transcriptTypes';

export default function ToolCallMessage({
  tool,
  isStreaming = false,
}: {
  tool: ToolCall;
  isStreaming?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  const fullArgs = () =>
    Object.entries(tool.arguments || {})
      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
      .join(', ');

  const isExpandable = tool.arguments && Object.keys(tool.arguments).length > 0;

  return (
    <div className="mt-1 p-1.5 bg-secondary/85 rounded text-xs break-all whitespace-pre-wrap">
      <div className="text-[10px] text-muted-foreground mb-0.5">
        Tool Call ID: {tool.id}
      </div>
      <div className="font-mono">
        {isExpandable ? (
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
          <span className="font-semibold">{tool.function}(...)</span>
        )}

        {isExpanded &&
          (tool.view ? (
            <span className="font-mono">{tool.view.content}</span>
          ) : (
            <div className="mt-1 text-muted-foreground">{fullArgs()}</div>
          ))}
      </div>
    </div>
  );
}
