/***
 * This is an agent run viewer that looks stylistically like the Docent Agent Run Viewer.
 * However, it has some slight modifications that are tailored to the Investigator interface.
 * In the future, this could probably just be a unified component that is shared between the two.
 */

import React, { useState, useEffect } from 'react';
import { AgentRun } from '@/app/types/transcriptTypes';
import {
  MessageBox,
  hasJsonContent,
} from '@/app/dashboard/[collection_id]/agent_run/components/MessageBox';
import { ChevronDown, ChevronRight, X, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScorePill } from '@/components/ScorePill';

interface InvestigatorAgentRunViewerProps {
  agentRun: AgentRun | null | undefined;
  onCloneToContext?: (data: {
    messages: Array<{ role: string; content: string }>;
    counterfactualName?: string;
  }) => void;
  onClose?: () => void;
}

// Helper function to get message content as string
const getMessageContent = (content: string | any[]): string => {
  if (typeof content === 'string') {
    return content;
  }
  // If content is an array of Content objects
  return content
    .filter(
      (item): item is any & { text: string } =>
        item.type === 'text' && typeof item.text === 'string'
    )
    .map((item) => item.text)
    .join('\n');
};

// ScorePill component is now imported from shared components

export default function InvestigatorAgentRunViewer({
  agentRun,
  onCloneToContext,
  onClose,
}: InvestigatorAgentRunViewerProps) {
  const [prettyPrintJsonMessages, setPrettyPrintJsonMessages] = useState<
    Set<number>
  >(new Set());
  const [isGraderOutputExpanded, setIsGraderOutputExpanded] = useState(false);
  const [isToolsExpanded, setIsToolsExpanded] = useState(false);

  // Get the first transcript (assuming single transcript for investigator runs)
  const transcript = agentRun?.transcripts?.[0];

  // Extract grade, grader output, and error message from metadata
  const grade = agentRun?.metadata?.grade as number | null;
  const graderOutput = agentRun?.metadata?.grader_output as string | undefined;
  const errorMessage = agentRun?.metadata?.error_message as string | undefined;

  // Extract tools from transcript metadata
  const tools = transcript?.metadata?.tools as any[] | undefined;

  // Extract metadata for cloning
  const counterfactualName = agentRun?.metadata?.counterfactual_name as
    | string
    | undefined;

  // Initialize pretty print for messages with JSON content when transcript changes
  useEffect(() => {
    if (transcript && transcript.messages.length > 0) {
      const jsonMessageIndices = new Set<number>();

      transcript.messages.forEach((message, index) => {
        const content = getMessageContent(message.content);
        if (hasJsonContent(content)) {
          jsonMessageIndices.add(index);
        }
      });

      setPrettyPrintJsonMessages(jsonMessageIndices);
    }
  }, [transcript]);

  // Handler to clone to new context
  const handleCloneToContext = () => {
    if (!onCloneToContext || !agentRun || !transcript) return;

    // Just pass the raw data up - let the parent handle the logic
    const messages = transcript.messages.map((msg) => ({
      role: msg.role,
      content: getMessageContent(msg.content),
    }));

    onCloneToContext({
      messages,
      counterfactualName,
    });
  };

  // Handle case where agentRun is not yet loaded
  if (!agentRun) {
    return (
      <div className="flex flex-col h-full">
        {/* Header with close button */}
        <div className="flex items-center justify-between p-3 border-b border-border">
          <h3 className="text-sm font-semibold text-primary">
            Agent Run Details
          </h3>
          {onClose && (
            <Button
              onClick={onClose}
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-muted-foreground">
            Loading agent run...
          </div>
        </div>
      </div>
    );
  }

  if (!transcript) {
    return (
      <div className="p-3 text-center text-muted-foreground">
        No transcript found in this agent run
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header with close button */}
      <div className="flex items-center justify-between p-3 border-b border-border">
        <h3 className="text-sm font-semibold text-primary">
          Agent Run Details
        </h3>
        <div className="flex items-center gap-2">
          {onCloneToContext && (
            <Button
              onClick={handleCloneToContext}
              variant="outline"
              size="sm"
              className="h-8 px-3 text-xs"
              title="Clone to new base context"
            >
              <Copy className="h-3 w-3 mr-1" />
              Clone to Context
            </Button>
          )}
          {onClose && (
            <Button
              onClick={onClose}
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Scrollable content area */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <div className="space-y-3 p-3">
          {/* Grading Block */}
          <div className="bg-secondary border border-border rounded-md p-3 space-y-3">
            <div
              className="flex items-center justify-between cursor-pointer select-none"
              onClick={() =>
                graderOutput &&
                setIsGraderOutputExpanded(!isGraderOutputExpanded)
              }
            >
              <div className="flex items-center space-x-3">
                {graderOutput && (
                  <div className="flex items-center space-x-1 text-xs text-muted-foreground">
                    {isGraderOutputExpanded ? (
                      <ChevronDown className="h-4 w-4" />
                    ) : (
                      <ChevronRight className="h-4 w-4" />
                    )}
                  </div>
                )}

                <span className="font-semibold text-sm">Grade</span>
                <ScorePill
                  score={grade}
                  title={`Grade: ${grade !== null ? grade.toFixed(2) : 'N/A'}`}
                />
              </div>
            </div>

            {/* Collapsible Grader Output */}
            {graderOutput && isGraderOutputExpanded && (
              <div className="border-t border-border pt-3">
                <div className="bg-background rounded-md p-3 text-sm font-mono whitespace-pre-wrap text-muted-foreground">
                  {graderOutput}
                </div>
              </div>
            )}
          </div>

          {/* Error Message */}
          {errorMessage && (
            <div className="bg-red-bg border border-red-border rounded-md p-3">
              <div className="text-sm font-medium text-red-text mb-1">
                Error occurred during rollout:
              </div>
              <div className="text-sm text-red-text whitespace-pre-wrap">
                {errorMessage}
              </div>
            </div>
          )}

          {/* Tools Block */}
          {tools && tools.length > 0 && (
            <div className="bg-secondary border border-border rounded-md p-3 space-y-3">
              <div
                className="flex items-center justify-between cursor-pointer select-none"
                onClick={() => setIsToolsExpanded(!isToolsExpanded)}
              >
                <div className="flex items-center space-x-3">
                  <div className="flex items-center space-x-1 text-xs text-muted-foreground">
                    {isToolsExpanded ? (
                      <ChevronDown className="h-4 w-4" />
                    ) : (
                      <ChevronRight className="h-4 w-4" />
                    )}
                  </div>
                  <span className="font-semibold text-sm">Available Tools</span>
                  <span className="text-xs text-muted-foreground">
                    ({tools.length} tool{tools.length !== 1 ? 's' : ''})
                  </span>
                </div>
              </div>

              {/* Collapsible Tools List */}
              {isToolsExpanded && (
                <div className="border-t border-border pt-3 space-y-3">
                  {tools.map((tool, index) => (
                    <div
                      key={index}
                      className="bg-background rounded-md p-3 space-y-2"
                    >
                      <div className="flex items-start justify-between">
                        <div className="space-y-1">
                          <div className="font-semibold text-sm text-primary">
                            {tool.name}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {tool.description}
                          </div>
                        </div>
                      </div>
                      {tool.parameters && (
                        <div className="border-t border-border pt-2">
                          <div className="text-xs font-mono bg-secondary rounded p-2 overflow-x-auto">
                            <pre>
                              {JSON.stringify(tool.parameters, null, 2)}
                            </pre>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Messages */}
          {transcript.messages.map((message, index) => {
            const blockId = `r-0_t-0_b-${index}`;
            return (
              <MessageBox
                key={index}
                message={message}
                index={index}
                blockId={blockId}
                isHighlighted={false}
                citedRanges={[]}
                prettyPrintJsonMessages={prettyPrintJsonMessages}
                setPrettyPrintJsonMessages={setPrettyPrintJsonMessages}
                transcriptIdx={0}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
