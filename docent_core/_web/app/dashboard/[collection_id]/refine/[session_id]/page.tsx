'use client';

import { Card } from '@/components/ui/card';
import ChatArea from '../../components/chat/ChatArea';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { skipToken } from '@reduxjs/toolkit/query';
import { useAppDispatch } from '@/app/store/hooks';
import {
  useStartRefinementSessionMutation,
  usePostMessageToRefinementSessionMutation,
  useListenToRefinementJobQuery,
  usePostRubricUpdateToRefinementSessionMutation,
} from '@/app/api/refinementApi';
import RubricEditor from '../../components/RubricEditor';
import { JudgeResultWithCitations, Rubric } from '@/app/store/rubricSlice';
import { RefinementAgentSession } from '@/app/store/refinementSlice';
import RefinementTimeline from '../../components/RefinementTimeline';
import { JudgeResultsList } from '../../components/JudgeResultsSection';
import { Button } from '@/components/ui/button';
import { useRouter } from 'next/navigation';
import { ProgressBar } from '@/app/components/ProgressBar';
import posthog from 'posthog-js';

export default function RefinePage() {
  const params = useParams();
  const dispatch = useAppDispatch();
  const router = useRouter();
  const collectionId = (params as any)?.collection_id as string | undefined;
  const sessionId = (params as any)?.session_id as string | undefined;

  const [curRsession, setCurRsession] = useState<RefinementAgentSession | null>(
    null
  );

  // const messages = useAppSelector((s) => s.refinement.messages);
  const [jobId, setJobId] = useState<string | null>(null);
  const [rubricId, setRubricId] = useState<string | null>(null);

  // Start the refinement session on page load
  const [startRefinementSession] = useStartRefinementSessionMutation();
  // useEffect is safe because the endpoint is idempotent
  useEffect(() => {
    if (!collectionId || !sessionId) return;
    startRefinementSession({ collectionId, sessionId })
      .unwrap()
      .then((res) => {
        if (res?.job_id) setJobId(res.job_id);
        if (res?.rubric_id) setRubricId(res.rubric_id);
      })
      .catch(() => {});
  }, [collectionId, sessionId, startRefinementSession]);

  // Handle sending messages to the refinement session
  const [postMessage] = usePostMessageToRefinementSessionMutation();
  const [postRubricUpdate] = usePostRubricUpdateToRefinementSessionMutation();
  const onSendMessage = useCallback(
    (message: string) => {
      if (!collectionId || !sessionId) return;
      postMessage({ collectionId, sessionId, message })
        .unwrap()
        .then((res) => {
          if (res?.job_id) setJobId(res.job_id);
          if (res?.rsession) setCurRsession(res.rsession);
        })
        .catch(() => {});
    },
    [collectionId, sessionId, postMessage]
  );

  // Start listening to the job state via SSE when we have a jobId
  const {
    data: { isSSEConnected, rsession } = {
      isSSEConnected: false,
      rsession: null,
    },
  } = useListenToRefinementJobQuery(
    jobId && collectionId ? { collectionId, jobId } : skipToken
  );
  useEffect(() => {
    if (rsession) setCurRsession(rsession);
  }, [rsession]);

  // Post-process the messages a little bit, determine when to increment rubric version
  const [showDiff, setShowDiff] = useState<boolean>(false);
  const [refinementRubricVersion, setRefinementRubricVersion] = useState<
    number | null
  >(null);

  // Keep a ref in sync so effects depending only on messages can read latest version
  const refinementRubricVersionRef = useRef<number | null>(
    refinementRubricVersion
  );
  useEffect(() => {
    refinementRubricVersionRef.current = refinementRubricVersion;
  }, [refinementRubricVersion]);

  const messages = curRsession?.messages ?? [];
  const processedMessages = useMemo(() => {
    const ans = messages.filter((message) => {
      if (
        message.role === 'tool' &&
        message.function === 'set_rubric' &&
        !message.error
      ) {
        // We know the content must be the version of the rubric
        // We don't want to render it and instead use it for something else
        return false;
      } else {
        return true;
      }
    });
    return ans;
  }, [messages]);

  // Update the rubric version when we receive a set_rubric message
  useEffect(() => {
    let maxVersion: number | null = null;
    for (const message of messages) {
      if (
        message.role === 'tool' &&
        message.function === 'set_rubric' &&
        !message.error
      ) {
        const version = Number(message.content);
        maxVersion = Math.max(version, maxVersion ?? 0);
      }
    }

    if (maxVersion === null) return;
    // Only update when the version actually increases or changes
    const currentVersion = refinementRubricVersionRef.current;
    if (
      currentVersion !== maxVersion &&
      !(currentVersion !== null && maxVersion < currentVersion)
    ) {
      setRefinementRubricVersion(maxVersion);
      if (maxVersion > 2) setShowDiff(true);
    }
  }, [messages]);

  const [hasChanges, setHasChanges] = useState<boolean>(false);

  const handleRubricSave = (rubric: Rubric) => {
    if (!collectionId || !sessionId) return;
    if (isSSEConnected) {
      throw new Error('Cannot save rubric while SSE is connected');
    }

    postRubricUpdate({ collectionId, sessionId, rubric })
      .unwrap()
      .then((res) => {
        if (res?.job_id) setJobId(res.job_id);
        if (res?.rsession) setCurRsession(res.rsession);
        setRefinementRubricVersion(rubric.version);
      })
      .catch(() => {});
  };

  /**
   * Judge results
   */
  const judgeResultsMap = useMemo(() => {
    const judgeResultsList = curRsession?.judge_results ?? [];
    return judgeResultsList.reduce(
      (acc, judgeResult) => {
        acc[judgeResult.id] = judgeResult;
        return acc;
      },
      {} as Record<string, JudgeResultWithCitations>
    );
  }, [curRsession]);

  const uniqueAgentRunsInJudgeResults = useMemo(
    () => new Set(Object.values(judgeResultsMap).map((r) => r.agent_run_id)),
    [judgeResultsMap]
  );

  return (
    <Card className="flex-1 flex h-full min-h-0 space-x-3 space-y-0">
      <div className="flex-1 flex flex-col space-y-3">
        {curRsession?.status && (
          <>
            <RefinementTimeline status={curRsession.status} />
            <div className="border-b border-border" />
          </>
        )}
        <ChatArea
          isReadonly={hasChanges}
          messages={processedMessages}
          onSendMessage={onSendMessage}
          isLoading={isSSEConnected}
          byoFlexDiv={true}
          __showThinkingSpacerAfterFirstMessage={true}
        />
      </div>
      <div className="border-r border-border" />
      <div className="flex-1 flex flex-col custom-scrollbar overflow-y-scroll space-y-3">
        {rubricId && (
          <div className="space-y-3">
            <RubricEditor
              rubricId={rubricId}
              rubricVersion={refinementRubricVersion}
              setRubricVersion={setRefinementRubricVersion}
              showDiff={showDiff}
              setShowDiff={setShowDiff}
              editable={!isSSEConnected} // Cannot edit if SSE is connected
              onSave={handleRubricSave}
              onCloseWithoutSave={() => {}}
              onHasUnsavedChangesUpdated={setHasChanges}
            />
            <div className="flex justify-end">
              <Button
                className="w-full"
                size="sm"
                disabled={isSSEConnected}
                onClick={() => {
                  // Log PostHog event with rubric details
                  posthog.capture('refinement_finalized', {
                    collection_id: collectionId,
                    session_id: sessionId,
                  });
                  router.push(
                    `/dashboard/${collectionId}?rubricId=${rubricId}`
                  );
                }}
              >
                Finalize and run rubric
              </Button>
            </div>
          </div>
        )}

        {/* Results section */}
        <div>
          <div className="text-sm font-semibold">Sample results</div>
          <div className="text-xs text-muted-foreground">
            These datapoints are used to inform the refinement process. They are{' '}
            <b>not</b> final judgements.
          </div>
        </div>
        {isSSEConnected && curRsession?.status === 'reading_data' && (
          <ProgressBar
            current={uniqueAgentRunsInJudgeResults.size}
            total={null}
          />
        )}
        <JudgeResultsList
          judgeResultsMap={judgeResultsMap}
          centroidsMap={{}}
          centroidAssignments={{}}
          isPollingAssignments={false}
        />
      </div>
    </Card>
  );
}
