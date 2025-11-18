'use client';

import { useCallback, useState, useEffect, useMemo } from 'react';
import { useParams } from 'next/navigation';
import {
  ChatArea,
  SuggestedMessage,
} from '@/app/dashboard/[collection_id]/components/chat/ChatArea';
import { ChatHeader } from '@/app/dashboard/[collection_id]/components/chat/ChatHeader';
import { ModelOption } from '@/app/store/rubricSlice';
import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import { useTranscriptChat } from '@/app/hooks/use-transcript-chat';
import { useGetChatModelsQuery } from '@/app/api/chatApi';
import { cn } from '@/lib/utils';
import JudgeResultWithReflection from './JudgeResultWithReflection';
import ModelPicker from './ModelPicker';
import SelectionBadges from './SelectionBadges';
import { InlineCitation } from '@/app/types/citationTypes';
import { useTextSelection } from '@/providers/use-text-selection';
import { useCitationNavigation } from '@/providers/CitationNavigationProvider';
import Link from 'next/link';

const ESTIMATED_CHAT_MESSAGE_OUTPUT_TOKENS = 8192;

export interface TranscriptChatProps {
  agentRunId: string;
  collectionId?: string;
  rubricId?: string;

  // Result-specific props
  agentRunResults?: AgentRunJudgeResults | null;
  selectedResultId?: string;
  showEmptyResultMessage?: boolean;

  // UI customization
  suggestedMessages?: SuggestedMessage[];
  title?: string;

  // Layout
  className?: string;
}

const defaultSuggestedMessages: SuggestedMessage[] = [
  {
    label: 'Summarize',
    message: 'Summarize the transcript succinctly.',
  },
  {
    label: 'Explain mistakes',
    message: 'Explain mistakes the agent made, if there are any.',
  },
  {
    label: 'Identify unusual behavior',
    message:
      'Identify any unusual or unexpected behavior on the part of the agent.',
  },
];

const resultSpecificSuggestedMessages: SuggestedMessage[] = [
  {
    label: "Play devil's advocate",
    message:
      "Play devil's advocate. Is there a reasonable case to be made that the judge result is incorrect?",
  },
  {
    label: 'Provide context for judge result',
    message:
      'Summarize the context leading up to the behavior relevant to the rubric.',
  },
  {
    label: 'Explain judge result in more detail',
    message:
      'Walk through the rubric step by step and explain why the judge produced this result.',
  },
];

export default function TranscriptChat({
  agentRunId,
  collectionId: propCollectionId,
  rubricId,
  agentRunResults,
  selectedResultId,
  showEmptyResultMessage = false,
  title = 'Transcript Chat',
  className = 'flex flex-col h-full space-y-2',
}: TranscriptChatProps) {
  const params = useParams();

  // Use provided collectionId or extract from params
  const collectionId = propCollectionId || (params.collection_id as string);

  // Extract the selected result from agentRunResults
  const judgeResult = useMemo(() => {
    if (!agentRunResults || !selectedResultId) return null;
    return (
      agentRunResults.results.find((r) => r.id === selectedResultId) ??
      agentRunResults.results[0] ??
      null
    );
  }, [agentRunResults, selectedResultId]);

  const { selections, removeSelection, clearSelections } = useTextSelection({});
  const selectedTexts = selections.map((s) => s.text);
  const handleRemoveSelectedText = (index: number) => removeSelection(index);

  const citationNav = useCitationNavigation();

  const {
    sessionId,
    messages,
    isLoading,
    sendMessage: baseSendMessage,
    resetChat,
    chatState,
    errorMessage,
    errorId,
    estimatedInputTokens,
  } = useTranscriptChat({ agentRunId, collectionId, judgeResult });

  // Chat models state
  const { data: availableChatModels } = useGetChatModelsQuery();
  const [selectedChatModel, setSelectedChatModel] =
    useState<ModelOption | null>(null);

  // Set model when chat state is loaded (use session's current model)
  useEffect(() => {
    if (chatState?.chat_model && !selectedChatModel) {
      setSelectedChatModel(chatState.chat_model);
    }
  }, [chatState?.chat_model, selectedChatModel]);

  let shownChatModel = selectedChatModel;
  if (
    availableChatModels &&
    availableChatModels.length > 0 &&
    !shownChatModel
  ) {
    shownChatModel = availableChatModels[0];
  }

  // Check if context window is exceeded (local estimation) or if there's an API error
  const contextWindowErrorMessage: React.ReactNode | undefined = useMemo(() => {
    // If we have an error message from the SSE stream (actual failure), prioritize that
    if (errorId == 'docent_usage_limit') {
      return (
        <>
          Free daily usage limit reached.{' '}
          <Link
            style={{ textDecoration: 'underline' }}
            href="/settings/model-providers"
          >
            Add your own API key
          </Link>{' '}
          or{' '}
          <a
            style={{ textDecoration: 'underline' }}
            href="mailto:docent@transluce.org"
          >
            contact us
          </a>
          .
        </>
      );
    }
    if (errorMessage) {
      return <>{errorMessage}</>;
    }

    // Otherwise, check local estimation for proactive warning
    if (!estimatedInputTokens || !availableChatModels || !shownChatModel) {
      return undefined;
    }

    // Find the selected model's context window
    const selectedModelWithContext = availableChatModels.find(
      (model) =>
        model.model_name === shownChatModel.model_name &&
        model.provider === shownChatModel.provider
    );

    if (!selectedModelWithContext) {
      return undefined;
    }

    const isExceeded =
      estimatedInputTokens &&
      estimatedInputTokens + ESTIMATED_CHAT_MESSAGE_OUTPUT_TOKENS >
        selectedModelWithContext.context_window;

    if (!isExceeded) {
      return undefined;
    }

    const longerContextAvailable = availableChatModels.some(
      (model) =>
        model.context_window &&
        estimatedInputTokens + ESTIMATED_CHAT_MESSAGE_OUTPUT_TOKENS <=
          model.context_window
    );

    return longerContextAvailable ? (
      <>Context window exceeded. Try a different model.</>
    ) : (
      <>Context window exceeded.</>
    );
  }, [errorMessage, estimatedInputTokens, availableChatModels, shownChatModel]);

  // Wrap sendMessage to include the selected chat model
  const onSendMessage = useCallback(
    (message: string) => {
      if (selectedChatModel) {
        baseSendMessage(message, selectedChatModel);
      } else {
        baseSendMessage(message);
      }
    },
    [baseSendMessage, selectedChatModel]
  );

  const onSendMessageWithSelectedText = (text: string) => {
    if (selectedTexts.length === 0) {
      // Send message normally if no text is selected
      onSendMessage(text);
      return;
    }

    // Format selected texts with proper indentation
    const formatSelection = selectedTexts
      .map((selectedText) => `<selection>\n${selectedText}\n</selection>`)
      .join('\n');

    const message = `${formatSelection}\n<docent_user_message>\n${text}\n</docent_user_message>`;
    clearSelections();
    onSendMessage(message);
  };

  // Determine which suggested messages to use
  const finalSuggestedMessages = judgeResult
    ? resultSpecificSuggestedMessages
    : defaultSuggestedMessages;

  const headerElement = (
    <ChatHeader
      title={title}
      description="Ask questions about the transcript (⌘K)"
      onReset={resetChat}
      canReset={sessionId !== null && messages.length > 0}
    />
  );

  const inputAreaFooter = selectedChatModel && availableChatModels && (
    <div className="flex justify-end">
      <div className="w-64">
        <ModelPicker
          selectedModel={selectedChatModel}
          availableModels={availableChatModels}
          onChange={setSelectedChatModel}
          className="h-7 text-xs"
          borderless
        />
      </div>
    </div>
  );

  return (
    <div
      className={cn(
        'flex flex-col min-w-0 w-full mx-auto max-w-4xl',
        className
      )}
    >
      {sessionId ? (
        <ChatArea
          isReadonly={contextWindowErrorMessage !== undefined}
          messages={messages}
          onSendMessage={onSendMessageWithSelectedText}
          isSendingMessage={isLoading}
          headerElement={
            <>
              {headerElement}
              {agentRunResults && rubricId ? (
                <JudgeResultWithReflection
                  agentRunResults={agentRunResults}
                  selectedResultId={selectedResultId}
                  collectionId={collectionId}
                  rubricId={rubricId}
                />
              ) : showEmptyResultMessage ? (
                <div className="text-xs text-muted-foreground flex items-center border rounded-lg bg-muted border-dashed h-24 justify-center p-2">
                  Agent run {agentRunId?.split('-')?.[0] || 'unknown'} has no
                  result at this rubric version.
                </div>
              ) : null}
            </>
          }
          inputHeaderElement={
            selections.length > 0 ? (
              <SelectionBadges
                selections={selections}
                onRemove={handleRemoveSelectedText}
                onNavigate={(item) => {
                  const { transcriptId, blockIdx } = item;
                  if (
                    !transcriptId ||
                    !collectionId ||
                    !agentRunId ||
                    blockIdx == null
                  )
                    return;

                  const citation: InlineCitation = {
                    start_idx: 0,
                    end_idx: 0,
                    target: {
                      item: {
                        item_type: 'block_content',
                        agent_run_id: agentRunId,
                        collection_id: collectionId,
                        transcript_id: transcriptId,
                        block_idx: blockIdx,
                      },
                      text_range: null,
                    },
                  };
                  citationNav?.navigateToCitation?.({
                    target: citation.target,
                  });
                }}
              />
            ) : null
          }
          suggestedMessages={finalSuggestedMessages}
          byoFlexDiv={true}
          inputAreaFooter={inputAreaFooter}
          inputErrorMessage={contextWindowErrorMessage}
        />
      ) : (
        headerElement
      )}
    </div>
  );
}
