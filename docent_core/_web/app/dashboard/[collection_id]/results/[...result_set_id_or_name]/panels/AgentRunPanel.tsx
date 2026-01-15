'use client';

import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  SlidingPanel,
  PanelCitationProvider,
  SlidingPanelBody,
  type PanelState,
} from '@/components/sliding-panels';
import AgentRunViewer, {
  AgentRunViewerHandle,
} from '@/app/dashboard/[collection_id]/agent_run/components/AgentRunViewer';
import { CitationTargetTextRange } from '@/app/types/citationTypes';
import UuidPill from '@/components/UuidPill';
import { MetadataPopover } from '@/components/metadata/MetadataPopover';
import { MetadataBlock } from '@/components/metadata/MetadataBlock';
import { useGetAgentRunQuery } from '@/app/api/collectionApi';

interface AgentRunPanelContentProps {
  agentRunId: string;
  collectionId: string;
  citationTarget?: PanelState['citationTarget'];
  citationRequestId?: number;
  panelId: string;
  onRequestOpenRunMetadata?: (args: {
    citedKey?: string;
    textRange?: CitationTargetTextRange;
  }) => void;
}

function AgentRunPanelContent({
  agentRunId,
  collectionId,
  citationTarget,
  citationRequestId,
  panelId,
  onRequestOpenRunMetadata,
}: AgentRunPanelContentProps) {
  const viewerRef = useRef<AgentRunViewerHandle>(null);

  // Handle scrolling to citation - needs timeout to wait for viewer to mount
  useEffect(() => {
    if (citationTarget) {
      const timer = setTimeout(() => {
        viewerRef.current?.focusCitationTarget(citationTarget);
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [citationTarget, citationRequestId]);

  return (
    <PanelCitationProvider
      panelId={panelId}
      currentAgentRunId={agentRunId}
      viewerRef={viewerRef}
      initialCitationTarget={citationTarget}
      citationRequestId={citationRequestId}
    >
      <SlidingPanelBody className="h-full min-h-0">
        <AgentRunViewer
          ref={viewerRef}
          agentRunId={agentRunId}
          collectionId={collectionId}
          hideTopRow
          onRequestOpenRunMetadata={onRequestOpenRunMetadata}
        />
      </SlidingPanelBody>
    </PanelCitationProvider>
  );
}

export type AgentRunPanelState = PanelState & {
  type: 'agent_run';
  agentRunId: string;
  collectionId: string;
};

interface AgentRunSlidingPanelProps {
  panel: AgentRunPanelState;
  index: number;
  isRoot: boolean;
  isAlone: boolean;
}

export function AgentRunSlidingPanel({
  panel,
  index,
  isRoot,
  isAlone,
}: AgentRunSlidingPanelProps) {
  const [runMetadataOpen, setRunMetadataOpen] = useState(false);
  const [runMetadataHighlight, setRunMetadataHighlight] = useState<{
    citedKey?: string;
    textRange?: CitationTargetTextRange;
  } | null>(null);

  const shouldFetchRunMetadata =
    runMetadataOpen || runMetadataHighlight !== null;
  const { data: agentRun, isLoading: isAgentRunLoading } = useGetAgentRunQuery(
    { collectionId: panel.collectionId, agentRunId: panel.agentRunId },
    { skip: !shouldFetchRunMetadata }
  );

  const onRequestOpenRunMetadata = useCallback(
    (args: { citedKey?: string; textRange?: CitationTargetTextRange }) => {
      setRunMetadataHighlight(args);
      setRunMetadataOpen(true);
    },
    []
  );

  return (
    <SlidingPanel
      key={panel.id}
      id={panel.id}
      title={panel.title}
      isRoot={isRoot}
      isAlone={isAlone}
      index={index}
      renderHeader={({ closeButton, title }) => (
        <>
          {closeButton}
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <h2 className="text-sm font-medium truncate min-w-0">{title}</h2>
            <UuidPill uuid={panel.agentRunId} stopPropagation />
            <MetadataPopover.Root
              open={runMetadataOpen}
              onOpenChange={(open) => {
                setRunMetadataOpen(open);
                if (!open) setRunMetadataHighlight(null);
              }}
            >
              <MetadataPopover.DefaultTrigger />
              <MetadataPopover.Content title="Agent Run Metadata">
                <MetadataPopover.Body
                  metadata={agentRun?.metadata ?? {}}
                  emptyText={
                    isAgentRunLoading ? 'Loading…' : 'No metadata available'
                  }
                >
                  {(md) => (
                    <MetadataBlock
                      metadata={md}
                      showSearchControls={true}
                      citedKey={runMetadataHighlight?.citedKey}
                      textRange={runMetadataHighlight?.textRange}
                    />
                  )}
                </MetadataPopover.Body>
              </MetadataPopover.Content>
            </MetadataPopover.Root>
          </div>
        </>
      )}
    >
      <AgentRunPanelContent
        agentRunId={panel.agentRunId}
        collectionId={panel.collectionId}
        citationTarget={panel.citationTarget}
        citationRequestId={panel.citationRequestId}
        panelId={panel.id}
        onRequestOpenRunMetadata={onRequestOpenRunMetadata}
      />
    </SlidingPanel>
  );
}
