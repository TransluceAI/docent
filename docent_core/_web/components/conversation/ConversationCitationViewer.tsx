import { useCallback, useEffect, useRef } from 'react';
import AgentRunViewer, {
  AgentRunViewerHandle,
} from '@/app/dashboard/[collection_id]/agent_run/components/AgentRunViewer';
import { ChatMessage } from '@/app/types/transcriptTypes';
import { CitationTarget } from '@/app/types/citationTypes';
import { useCitationNavigation } from '@/providers/CitationNavigationProvider';

export function extractCitationsFromMessages(
  messages: ChatMessage[]
): CitationTarget[] {
  return messages
    .filter(
      (msg) =>
        msg.role === 'assistant' &&
        'citations' in msg &&
        msg.citations &&
        msg.citations.length > 0
    )
    .flatMap((msg) => {
      const assistantMsg = msg as any;
      return (assistantMsg.citations || []).map(
        (citation: any) => citation.target as CitationTarget
      );
    });
}

interface ConversationCitationViewerProps {
  citations: CitationTarget[];
}

export function ConversationCitationViewer({
  citations,
}: ConversationCitationViewerProps) {
  const viewerRef = useRef<AgentRunViewerHandle>(null);
  const citationNav = useCitationNavigation();
  const selectedCitation = citationNav?.selectedCitation ?? null;

  const handleCitationNavigation = useCallback(
    ({ target }: { target: CitationTarget; source?: string }) => {
      if (viewerRef.current) {
        viewerRef.current.focusCitationTarget(target);
      }
    },
    []
  );

  useEffect(() => {
    if (citationNav) {
      citationNav.registerHandler(handleCitationNavigation);
      return () => {
        citationNav.registerHandler(null);
      };
    }
  }, [citationNav, handleCitationNavigation]);

  if (!selectedCitation) {
    return (
      <div className="flex h-full items-center justify-center p-3">
        <div className="text-center text-muted-foreground">
          <p className="text-sm">No citation selected</p>
          <p className="mt-2 text-xs">
            Click on a citation in the chat to view it here
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-hidden p-3">
      <AgentRunViewer
        ref={viewerRef}
        agentRunId={selectedCitation.item.agent_run_id}
        collectionId={selectedCitation.item.collection_id}
        allConversationCitations={citations}
      />
    </div>
  );
}
