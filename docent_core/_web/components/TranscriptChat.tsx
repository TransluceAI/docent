'use client';

import { useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  ChatArea,
  SuggestedMessage,
} from '@/app/dashboard/[collection_id]/components/chat/ChatArea';
import { ChatHeader } from '@/app/dashboard/[collection_id]/components/chat/ChatHeader';
import { NavigateToCitation } from '@/components/CitationRenderer';
import { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { useTranscriptChat } from '@/app/hooks/use-transcript-chat';
import { cn } from '@/lib/utils';
import JudgeResultDetail from './JudgeResultDetail';

export interface TranscriptChatProps {
  runId: string;
  collectionId?: string;

  // Result-specific props
  judgeResult?: JudgeResultWithCitations | null;
  resultContext?: {
    rubricId: string;
    resultId: string;
  };

  // Navigation and citation handling
  onNavigateToCitation?: NavigateToCitation;

  // UI customization
  suggestedMessages?: SuggestedMessage[];
  title?: string;

  // Layout
  className?: string;
}

const defaultSuggestedMessages: SuggestedMessage[] = [
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
  onNavigateToCitation,
  title = 'Transcript Chat',
  className = 'flex flex-col h-full space-y-2',
}: TranscriptChatProps) {
  const params = useParams();
  const router = useRouter();

  // Use provided collectionId or extract from params
  const collectionId = propCollectionId || (params.collection_id as string);

  const {
    sessionId,
    messages,
    isLoading,
    sendMessage: onSendMessage,
    resetChat,
  } = useTranscriptChat({ runId, collectionId, judgeResult });

  // Handle citation navigation
  const handleNavigateToCitation: NavigateToCitation = useCallback(
    ({ citation, newTab }) => {
      if (onNavigateToCitation) {
        onNavigateToCitation({ citation, newTab });
      } else if (resultContext) {
        // Default navigation for result context
        router.push(
          `/dashboard/${collectionId}/rubric/${resultContext.rubricId}/result/${resultContext.resultId}`,
          { scroll: false } as any
        );
      }
    },
    [onNavigateToCitation, resultContext, router, collectionId]
  );

  // Determine which suggested messages to use
  const finalSuggestedMessages = judgeResult
    ? resultSpecificSuggestedMessages
    : defaultSuggestedMessages;

  const headerElement = (
    <ChatHeader
      title={title}
      onReset={resetChat}
      canReset={sessionId !== null && messages.length > 0}
    />
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
          isReadonly={false}
          messages={messages}
          onSendMessage={onSendMessage}
          isLoading={isLoading}
          headerElement={
            <>
              {headerElement}
              {judgeResult && (
                <JudgeResultDetail
                  judgeResult={judgeResult}
                  handleNavigateToCitation={handleNavigateToCitation}
                />
              )}
            </>
          }
          hideAssistantAvatar={true}
          suggestedMessages={finalSuggestedMessages}
          onNavigateToCitation={handleNavigateToCitation}
          byoFlexDiv={true}
        />
      ) : (
        headerElement
      )}
    </div>
  );
}
