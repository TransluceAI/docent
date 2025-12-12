'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
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
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import { formatTokenCount } from '@/lib/utils';

interface ConversationViewProps {
  sessionId: string | null;
}

export function ConversationView({ sessionId }: ConversationViewProps) {
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
      <div className="flex h-full min-h-[60vh] items-center justify-center bg-background">
        <div className="text-muted-foreground">Invalid session ID</div>
      </div>
    );
  }

  const headerElement = (
    <ConversationContextSection
      contextSerialized={chatState?.context_serialized}
      sessionId={sessionId}
      itemTokenEstimates={chatState?.item_token_estimates}
    />
  );

  const inputAreaFooter = (
    <div className="flex items-center justify-between gap-2 w-full">
      {estimatedInputTokens !== undefined && (
        <div className="text-xs text-muted-foreground">
          {formatTokenCount(estimatedInputTokens)} tokens
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
    <div className="flex h-full min-h-[70vh] flex-col bg-background">
      <ResizablePanelGroup direction="horizontal" className="flex-1 min-h-0">
        <ResizablePanel defaultSize={60} minSize={35} className="min-w-0">
          <div className="flex h-full min-h-0 flex-col border-r border-border p-3">
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
        </ResizablePanel>

        <ResizableHandle className="!mx-0 !px-0" />

        <ResizablePanel defaultSize={40} minSize={20} className="min-w-0">
          <div className="flex h-full min-h-0 flex-col overflow-hidden">
            <ConversationCitationViewer citations={citations} />
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
