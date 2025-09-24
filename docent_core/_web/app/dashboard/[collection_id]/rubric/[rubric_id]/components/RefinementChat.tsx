'use client';

import { useMemo, useState } from 'react';
import { ChatArea } from '../../../components/chat/ChatArea';
import useRefinementChat from '@/app/hooks/use-refinement-chat';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import { ProgressBar } from '@/app/components/ProgressBar';
import { Button } from '@/components/ui/button';
import { toast } from '@/hooks/use-toast';
import { Tags } from 'lucide-react';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { useGetJudgeRunLabelsQuery } from '@/app/api/rubricApi';
import { useRetryLastMessageMutation } from '@/app/api/refinementApi';
import { useRefinementTab } from '@/providers/use-refinement-tab';

interface RefinementChatProps {
  collectionId: string;
  sessionId?: string;
  rubricId: string;
  isOnResultRoute?: boolean;
}

export default function RefinementChat({
  collectionId,
  sessionId,
  rubricId,
  isOnResultRoute,
}: RefinementChatProps) {
  const hasWritePermission = useHasCollectionWritePermission();
  const [showLabelsInContext, setShowLabelsInContext] = useState(true);
  const { setRefinementJobId } = useRefinementTab();

  // Judge run labels
  const { data: labels } = useGetJudgeRunLabelsQuery({
    collectionId,
    rubricId,
  });
  const hasLabels = (labels?.length ?? 0) > 0;

  const shouldShowLabelsInContext = showLabelsInContext && hasLabels;

  const [retryLastMessage] = useRetryLastMessageMutation();

  const {
    rSession,
    onSendMessage,
    onCancelMessage,
    messages,
    isSSEConnected,
    inputErrorMessage,
  } = useRefinementChat({
    collectionId,
    sessionId,
    rubricId,
    showLabelsInContext: shouldShowLabelsInContext,
  });

  const showInitialProgress = useMemo(() => {
    if (!rSession) return false;
    if (rSession.messages.length >= 2) return false;
    return rSession?.n_summaries > 0 && rSession?.n_summaries < 10;
  }, [rSession]);

  const LabelToggle = () => {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className={cn(
              'h-6 gap-2 text-xs border rounded-lg',
              !showLabelsInContext && 'border-dashed bg-transparent opacity-70'
            )}
            disabled={!hasLabels}
            onClick={(e) => {
              e.preventDefault();
              if (!hasLabels) return;
              setShowLabelsInContext((v) => !v);
            }}
          >
            <Tags
              className={cn('size-3', showLabelsInContext && 'text-blue-text')}
            />
            Labels
          </Button>
        </TooltipTrigger>
        <TooltipContent className="max-w-48 text-center">
          <p>
            {hasLabels
              ? 'Toggle whether the agent sees labels in context.'
              : 'No labels found.'}
          </p>
        </TooltipContent>
      </Tooltip>
    );
  };

  const onRetry = async () => {
    if (!sessionId) return;

    await retryLastMessage({ collectionId, sessionId })
      .unwrap()
      .then((res) => {
        if (res?.job_id) setRefinementJobId(res.job_id);
      })
      .catch(() => {
        toast({
          title: 'Error',
          description: 'Failed to retry last message',
          variant: 'destructive',
        });
      });
  };

  return (
    <div className="flex-1 flex flex-col space-y-3 h-full">
      {showInitialProgress && (
        <div className="flex items-center gap-2 2xl:px-64 xl:px-16 md:px-16">
          <div className="flex-1">
            <ProgressBar current={rSession?.n_summaries || 0} total={10} />
          </div>
        </div>
      )}
      <ChatArea
        key={sessionId || 'refinement-chat'}
        isReadonly={!hasWritePermission}
        messages={messages}
        onSendMessage={onSendMessage}
        onCancelMessage={onCancelMessage}
        onRetry={onRetry}
        isSendingMessage={isSSEConnected || !sessionId}
        byoFlexDiv={true}
        __showThinkingSpacerAfterFirstMessage={true}
        scrollContainerClassName={
          !isOnResultRoute ? '2xl:px-64 xl:px-16 md:px-16' : undefined
        }
        inputAreaClassName={
          !isOnResultRoute ? '2xl:px-64 xl:px-16 md:px-16' : undefined
        }
        inputErrorMessage={inputErrorMessage}
        inputAreaFooter={undefined}
        headerElement={
          <div className="flex flex-col">
            <div className="text-sm font-semibold">Refinement Chat</div>
            <div className="text-xs text-muted-foreground">
              Chat with an agent to refine the rubric (⌘J)
            </div>
          </div>
        }
        inputHeaderElement={hasLabels ? <LabelToggle /> : null}
      />
    </div>
  );
}
