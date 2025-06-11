'use client';

import { CornerDownLeft, Loader2 } from 'lucide-react';
import React, { useEffect, useState } from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  createTaSession,
  resetTaSession,
  sendTaMessage,
} from '@/app/store/transcriptSlice';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Textarea } from '@/components/ui/textarea';
import { toast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';


interface TaPanelProps {
  onShowAgentRun?: (agentRunId: string, blockId: number) => void;
}

export default function TaPanel({ onShowAgentRun }: TaPanelProps) {
  const dispatch = useAppDispatch();

  const curAgentRun = useAppSelector((state) => state.transcript.curAgentRun);
  const taAgentRunId = useAppSelector((state) => state.transcript.taAgentRunId);
  const taSessionId = useAppSelector((state) => state.transcript.taSessionId);
  const taMessages = useAppSelector((state) => state.transcript.taMessages);
  const loadingTaResponse = useAppSelector(
    (state) => state.transcript.loadingTaResponse
  );

  const [inputValue, setInputValue] = useState('');

  // Handle sending a message
  const handleSendMessage = () => {
    // Validate message
    if (!taSessionId) {
      toast({
        title: 'Error',
        description: 'No active TA session',
        variant: 'destructive',
      });
      return;
    }

    if (inputValue.trim() === '') {
      toast({
        title: 'Error',
        description: 'Please enter a message',
        variant: 'destructive',
      });
      return;
    }

    // Send message
    dispatch(sendTaMessage(inputValue));
    setInputValue('');
  };

  // Initialize the TA session when datapoint changes
  useEffect(() => {
    if (curAgentRun?.id) {
      const currentAgentRunId = curAgentRun.id;

      // Check if the datapoint has changed from the one we're chatting about
      if (taAgentRunId !== currentAgentRunId) {
        // Clear the messages when datapoint changes
        dispatch(resetTaSession());

        // Create a new TA session with the current datapoint
        const success = dispatch(createTaSession(currentAgentRunId));
        if (!success) {
          toast({
            title: 'Error',
            description: 'Failed to create TA session',
            variant: 'destructive',
          });
        }
      }
    }
  }, [curAgentRun?.id, taAgentRunId, dispatch]);

  return (
    <div className="flex flex-col h-full space-y-2">
      <div className="font-semibold text-sm">Transcript Chat</div>
      <ScrollArea className="flex-1 h-full bg-gray-50 rounded-lg border border-card-border p-2">
        {taMessages?.map((message, index) => (
          <div
            key={index}
            className={cn(
              'flex w-full mt-2',
              message.role === 'user' ? 'justify-end' : 'justify-start'
            )}
          >
            <div
              className={cn(
                'rounded-md px-3 py-2 max-w-[85%]',
                message.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-white border shadow-sm'
              )}
            >
              <div className="text-sm leading-normal whitespace-pre-wrap">
                {message.role === 'assistant' &&
                message.citations &&
                message.citations.length > 0 ? (
                  <>
                    {message.citations.reduce((acc, citation, i) => {
                      const parts = [];

                      // Add text before the citation
                      if (i === 0) {
                        parts.push(
                          <span key={`text-start-${i}`}>
                            {message.content.slice(0, citation.start_idx)}
                          </span>
                        );
                      } else {
                        parts.push(
                          <span key={`text-between-${i}`}>
                            {message.content.slice(
                              message.citations![i - 1].end_idx,
                              citation.start_idx
                            )}
                          </span>
                        );
                      }

                      // Add the citation
                      parts.push(
                        <button
                          key={`citation-${i}`}
                          onClick={() => {
                            onShowAgentRun?.(
                              curAgentRun?.id ?? '',
                              citation.block_idx
                            );
                          }}
                          className="text-blue-600 hover:text-blue-800 hover:underline font-semibold px-0.5"
                          title={`Show block ${citation.block_idx} from datapoint ${curAgentRun?.id}`}
                        >
                          {message.content.slice(
                            citation.start_idx,
                            citation.end_idx
                          )}
                        </button>
                      );

                      // Add remaining text after the last citation
                      if (i === message.citations!.length - 1) {
                        parts.push(
                          <span key={`text-end-${i}`}>
                            {message.content.slice(citation.end_idx)}
                          </span>
                        );
                      }

                      return [...acc, ...parts];
                    }, [] as JSX.Element[])}
                  </>
                ) : (
                  <span>{message.content}</span>
                )}
              </div>
            </div>
          </div>
        ))}
        {loadingTaResponse && (
          <div className="flex w-full mt-2 justify-start">
            <div className="rounded-md px-3 py-2 bg-white border shadow-sm">
              <div className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                <span className="text-sm text-muted-foreground">
                  Thinking...
                </span>
              </div>
            </div>
          </div>
        )}
      </ScrollArea>
      <div>
        <form
          className="relative overflow-hidden rounded-md border bg-background focus-within:ring-1 focus-within:ring-ring"
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
        >
          <fieldset disabled={!taSessionId || loadingTaResponse}>
            <Textarea
              placeholder={
                taSessionId
                  ? 'Ask a question about the transcripts...'
                  : 'Apply a base frame to start chatting...'
              }
              className="min-h-[2.5rem] resize-none border-0 p-2 shadow-none focus-visible:ring-0 text-sm"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
            />
            <div className="flex items-center justify-end p-2 space-x-2">
              <Button
                type="submit"
                size="sm"
                className="gap-1 h-8 text-sm"
                disabled={
                  inputValue === '' || !taSessionId || loadingTaResponse
                }
              >
                Send
                <CornerDownLeft className="size-3" />
              </Button>
            </div>
          </fieldset>
        </form>
      </div>
    </div>
  );
}
