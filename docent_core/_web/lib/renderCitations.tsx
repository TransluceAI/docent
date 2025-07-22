import { Citation } from '../app/types/experimentViewerTypes';
import { navToAgentRun } from './nav';
import { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime';
import { openAgentRunInDashboard } from '../app/store/transcriptSlice';
import { AppDispatch } from '../app/store/store';

export const renderTextWithCitations = (
  text: string,
  citations: Citation[],
  dataId: string,
  router: AppRouterInstance,
  window: Window,
  dispatch: AppDispatch,
  searchQuery?: string,
  collectionId?: string
) => {
  if (!citations.length) {
    return text;
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
        className="px-0.5 py-0.25 bg-indigo-muted text-primary rounded hover:bg-indigo-muted/50 transition-colors font-medium"
        onMouseDown={(e) => {
          e.stopPropagation();

          if (e.ctrlKey || e.metaKey) {
            // Open in new tab - use original navigation
            navToAgentRun(
              router,
              window,
              dataId,
              citation.transcript_idx ?? undefined,
              citation.block_idx,
              collectionId,
              searchQuery,
              false
            );
          } else if (e.button === 0) {
            // Open in dashboard - use new mechanism if dispatch is available
            dispatch(
              openAgentRunInDashboard({
                agentRunId: dataId,
                blockIdx: citation.block_idx,
                transcriptIdx: citation.transcript_idx ?? undefined,
              })
            );
          }
        }}
      >
        {citedText}
      </button>
    );

    lastIndex = citation.end_idx;
  });

  // Add any remaining text
  if (lastIndex < text.length) {
    parts.push(<span key={`text-end`}>{text.slice(lastIndex)}</span>);
  }

  return <>{parts}</>;
};
