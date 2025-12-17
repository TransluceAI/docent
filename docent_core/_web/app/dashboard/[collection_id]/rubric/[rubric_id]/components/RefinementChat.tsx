'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChatArea } from '../../../components/chat/ChatArea';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import { ProgressBar } from '@/app/components/ProgressBar';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { Tags } from 'lucide-react';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import {
  useCancelRefinementJobMutation,
  useGetRefinementSessionStateQuery,
  useListenToRefinementJobQuery,
  usePostMessageToRefinementSessionMutation,
  useRetryLastMessageMutation,
  useStartRefinementSessionMutation,
} from '@/app/api/refinementApi';
import { useRefinementTab } from '@/providers/use-refinement-tab';
import { RefinementAgentSession } from '@/app/store/refinementSlice';
import { skipToken } from '@reduxjs/toolkit/query';
import { useRubricVersion } from '@/providers/use-rubric-version';
import { useGetLabelsInLabelSetQuery } from '@/app/api/labelApi';
import { useLabelSets } from '@/providers/use-label-sets';
import { useParams } from 'next/navigation';

interface RefinementChatProps {
  sessionId?: string;
  isOnResultRoute?: boolean;
}

export default function RefinementChat({
  sessionId,
  isOnResultRoute,
}: RefinementChatProps) {
  const { collection_id: collectionId, rubric_id: rubricId } = useParams<{
    collection_id: string;
    rubric_id: string;
  }>();
  const hasWritePermission = useHasCollectionWritePermission();
  const { refinementJobId, setRefinementJobId } = useRefinementTab();

  // Judge run labels
  const { activeLabelSet } = useLabelSets(rubricId);
  const { data: labels = [] } = useGetLabelsInLabelSetQuery(
    activeLabelSet ? { collectionId, labelSetId: activeLabelSet.id } : skipToken
  );
  const hasLabels = labels.length > 0;
  const [_showLabelsInContext, setShowLabelsInContext] = useState(true);
  const showLabelsInContext = _showLabelsInContext && hasLabels;

  // Start or get active refinement job
  const [startRefinementSession] = useStartRefinementSessionMutation();
  useEffect(() => {
    if (!sessionId) return;
    startRefinementSession({ collectionId, sessionId })
      .unwrap()
      .then((res) => {
        if (res?.job_id) {
          setRefinementJobId(res.job_id);
        }
      })
      .catch(() => {});
  }, [collectionId, sessionId, startRefinementSession, setRefinementJobId]);

  // Handle sending messages to the refinement session
  const [postMessage] = usePostMessageToRefinementSessionMutation();
  const onSendMessage = useCallback(
    (message: string) => {
      if (!sessionId) return;
      postMessage({
        collectionId,
        sessionId,
        message,
        labelSetId:
          showLabelsInContext && activeLabelSet ? activeLabelSet.id : null,
      })
        .unwrap()
        .then((res) => {
          if (res?.job_id) setRefinementJobId(res.job_id);
        })
        .catch(() => {});
    },
    [
      collectionId,
      sessionId,
      showLabelsInContext,
      activeLabelSet,
      postMessage,
      setRefinementJobId,
    ]
  );

  // Handle canceling the refinement session and cleaning up local state
  const [cancelRefinementSession] = useCancelRefinementJobMutation();
  const onCancelMessage = useCallback(async () => {
    if (!sessionId) return;
    setRefinementJobId(null);
    await cancelRefinementSession({ collectionId, sessionId })
      .unwrap()
      .catch(() => {
        toast.error('Failed to cancel refinement session');
      });
  }, [collectionId, sessionId, cancelRefinementSession, setRefinementJobId]);

  const [retryLastMessage] = useRetryLastMessageMutation();
  const onRetry = async () => {
    if (!sessionId) return;

    await retryLastMessage({ collectionId, sessionId })
      .unwrap()
      .then((res) => {
        if (res?.job_id) setRefinementJobId(res.job_id);
      })
      .catch(() => {
        toast.error('Failed to retry last message');
      });
  };

  // Start listening to the job state via SSE when we have a jobId
  const {
    data: { isSSEConnected, rSession } = {
      isSSEConnected: false,
      rSession: null,
    },
  } = useListenToRefinementJobQuery(
    refinementJobId ? { collectionId, jobId: refinementJobId } : skipToken
  );

  // Get the session state from DB if there was no active job to grab it from
  const { data: initialState } = useGetRefinementSessionStateQuery(
    !rSession && sessionId ? { collectionId, sessionId } : skipToken
  );

  // Persist the latest non-null session to prevent UI flicker when a new SSE
  // connection is established and the query briefly returns null before the
  // first message arrives.
  const [persistedSession, setPersistedSession] =
    useState<RefinementAgentSession | null>(null);

  // Keep a state to prevent flickering when sending a message
  useEffect(() => {
    if (rSession) {
      setPersistedSession(rSession);
    } else if (initialState) {
      setPersistedSession(initialState);
    }
  }, [rSession, initialState]);

  // Listen for rubric version changes on the refinement session
  // NOTE(cadentj): This will also switch to the latest version when the refinement chat component loads
  // E.g. if click on a result in v3 where the latest version is v6, and then tab to refinement it will switch to v6
  const { refetchLatestVersion } = useRubricVersion();
  const lastSeenRubricVersionRef = useRef<number | null>(null);
  useEffect(() => {
    const currentVersion = persistedSession?.rubric_version ?? null;
    if (
      currentVersion !== null &&
      currentVersion !== lastSeenRubricVersionRef.current
    ) {
      lastSeenRubricVersionRef.current = currentVersion;
      refetchLatestVersion();
    }
  }, [refetchLatestVersion, persistedSession?.rubric_version]);

  // Whether to show the summary progress bar
  const showSummaryProgressBar = useMemo(() => {
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

  return (
    <div className="flex-1 flex flex-col space-y-3 h-full">
      {showSummaryProgressBar && (
        <div className="flex items-center gap-2 px-16">
          <div className="flex-1">
            <ProgressBar current={rSession?.n_summaries || 0} total={10} />
          </div>
        </div>
      )}
      <ChatArea
        key={sessionId || 'refinement-chat'}
        isReadonly={!hasWritePermission}
        messages={persistedSession?.messages ?? []}
        onSendMessage={onSendMessage}
        onCancelMessage={onCancelMessage}
        onRetry={onRetry}
        isSendingMessage={isSSEConnected || !sessionId}
        byoFlexDiv={true}
        __showThinkingSpacerAfterFirstMessage={true}
        scrollContainerClassName={!isOnResultRoute ? 'px-16' : undefined}
        inputAreaClassName={!isOnResultRoute ? 'px-16' : undefined}
        inputErrorMessage={persistedSession?.error_message}
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
