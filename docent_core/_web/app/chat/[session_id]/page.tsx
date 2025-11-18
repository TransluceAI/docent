'use client';

import { useParams } from 'next/navigation';
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useConversation } from '@/app/hooks/use-conversation';
import {
  ConversationCitationViewer,
  extractCitationsFromMessages,
} from '@/components/conversation/ConversationCitationViewer';
import { ConversationContextSection } from '@/components/conversation/ConversationContextSection';
import { ChatArea } from '@/app/dashboard/[collection_id]/components/chat/ChatArea';
import { useGetChatModelsQuery } from '@/app/api/chatApi';
import { ModelOption } from '@/app/store/rubricSlice';
import ModelPicker from '@/components/ModelPicker';

export default function ConversationPage() {
  const params = useParams();
  const sessionId = (params?.session_id as string) || null;

  const {
    messages,
    isLoading,
    sendMessage: baseSendMessage,
    errorMessage,
    estimatedInputTokens,
    chatState,
  } = useConversation({ sessionId });

  const { data: availableChatModels } = useGetChatModelsQuery();
  const [selectedChatModel, setSelectedChatModel] =
    useState<ModelOption | null>(null);

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

  const sendMessage = useCallback(
    (message: string) => {
      if (selectedChatModel) {
        baseSendMessage(message, selectedChatModel);
      } else {
        baseSendMessage(message);
      }
    },
    [baseSendMessage, selectedChatModel]
  );

  const citations = useMemo(
    () => extractCitationsFromMessages(messages),
    [messages]
  );

  if (!sessionId) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="text-muted-foreground">Invalid session ID</div>
      </div>
    );
  }

  const headerElement = (
    <ConversationContextSection
      contextSerialized={chatState?.context_serialized}
    />
  );

  const inputAreaFooter = (
    <div className="flex items-center justify-between gap-2 w-full">
      {estimatedInputTokens !== undefined && (
        <div className="text-xs text-muted-foreground">
          ~{estimatedInputTokens?.toLocaleString() ?? '?'} tokens
        </div>
      )}
      {selectedChatModel && availableChatModels && (
        <div className="flex justify-end ml-auto">
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
      )}
    </div>
  );

  return (
    <div className="flex h-screen flex-col bg-background">
      <div className="flex flex-1 overflow-hidden">
        <div className="flex w-1/2 flex-col border-r border-border p-3">
          <ChatArea
            isReadonly={!!errorMessage}
            messages={messages}
            onSendMessage={sendMessage}
            isSendingMessage={isLoading}
            headerElement={headerElement}
            byoFlexDiv={true}
            inputAreaFooter={inputAreaFooter}
            inputErrorMessage={errorMessage}
          />
        </div>

        <div className="flex w-1/2 flex-col overflow-hidden">
          <ConversationCitationViewer citations={citations} />
        </div>
      </div>
    </div>
  );
}
