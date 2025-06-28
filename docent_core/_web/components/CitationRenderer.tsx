import React from "react";
import { cn } from "@/lib/utils";

export interface Citation {
  start_idx: number;
  end_idx: number;
  block_idx: number;
  transcript_idx: number | null;
}

interface CitationRendererProps {
  text: string;
  citations: Citation[];
  onCitationClick: (citation: Citation) => void;
}

export const CitationRenderer: React.FC<CitationRendererProps> = ({
  text,
  citations,
  onCitationClick,
}) => {
  if (!citations.length) {
    return <>{text}</>;
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
          {text.slice(lastIndex, citation.start_idx)}
        </span>
      );
    }

    // Add the cited text as a clickable element
    const citedText = text.slice(citation.start_idx, citation.end_idx);
    parts.push(
      <button
        key={`citation-${i}`}
        className={cn(
          "px-1 rounded font-medium text-xs",
          "bg-purple-200/50 dark:bg-purple-800/50",
          "text-purple-800 dark:text-purple-200",
          "hover:bg-purple-400/50 dark:hover:bg-purple-600/50",
          "hover:text-white dark:hover:text-white",
          "transition-colors"
        )}
        onClick={(e) => {
          e.stopPropagation();
          onCitationClick(citation);
        }}
      >
        {citedText}
      </button>
    );

    lastIndex = citation.end_idx;
  });

  // Add any remaining text
  if (lastIndex < text.length) {
    parts.push(<span key="text-end">{text.slice(lastIndex)}</span>);
  }

  return <>{parts}</>;
};
