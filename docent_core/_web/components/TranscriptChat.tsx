'use client';

import { useCallback, useState, useEffect, useMemo } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  ChatArea,
  SuggestedMessage,
} from '@/app/dashboard/[collection_id]/components/chat/ChatArea';
import { ChatHeader } from '@/app/dashboard/[collection_id]/components/chat/ChatHeader';
import { JudgeResultWithCitations, ModelOption } from '@/app/store/rubricSlice';
import { useTranscriptChat } from '@/app/hooks/use-transcript-chat';
import { useGetChatModelsQuery } from '@/app/api/chatApi';
import { cn } from '@/lib/utils';
import JudgeResultDetail from './JudgeResultDetail';
import ModelPicker from './ModelPicker';
import SelectionBadges from './SelectionBadges';
import { Citation } from '@/app/types/experimentViewerTypes';
import { useTextSelection } from '@/providers/use-text-selection';
import { useCitationNavigation } from '@/app/dashboard/[collection_id]/rubric/[rubric_id]/NavigateToCitationContext';

const ESTIMATED_CHAT_MESSAGE_OUTPUT_TOKENS = 8192;

export interface TranscriptChatProps {
  runId: string;
  collectionId?: string;

  // Result-specific props
  judgeResult?: JudgeResultWithCitations | null;
  resultContext?: {
    rubricId: string;
    resultId: string;
  };

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
  runId,
  collectionId: propCollectionId,
  judgeResult,
  resultContext,
  title = 'Transcript Chat',
  className = 'flex flex-col h-full space-y-2',
}: TranscriptChatProps) {
  const params = useParams();
  const router = useRouter();

  // Use provided collectionId or extract from params
  const collectionId = propCollectionId || (params.collection_id as string);

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
    estimatedInputTokens,
  } = useTranscriptChat({ runId, collectionId, judgeResult });

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
  const contextWindowErrorMessage: string | undefined = useMemo(() => {
    // If we have an error message from the SSE stream (actual failure), prioritize that
    if (errorMessage) {
      return errorMessage;
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

    return longerContextAvailable
      ? 'Context window exceeded. Try a different model.'
      : 'Context window exceeded.';
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
              {judgeResult && <JudgeResultDetail judgeResult={judgeResult} />}
            </>
          }
          inputHeaderElement={
            selections.length > 0 ? (
              <SelectionBadges
                selections={selections}
                onRemove={handleRemoveSelectedText}
                onNavigate={(item) => {
                  const { transcriptIdx, blockIdx } = item;
                  if (transcriptIdx == null || blockIdx == null) return;
                  const citation: Citation = {
                    transcript_idx: transcriptIdx,
                    block_idx: blockIdx,
                    start_idx: 0,
                    end_idx: 0,
                    metadata_key: undefined,
                    start_pattern: undefined,
                  };
                  citationNav?.navigateToCitation?.({ citation });
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
