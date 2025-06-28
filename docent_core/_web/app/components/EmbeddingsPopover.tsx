'use client';

import { useState, useEffect, useRef } from 'react';
import { useSelector } from 'react-redux';
import { Database, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { toast } from '@/hooks/use-toast';

import { RootState } from '../store/store';
import { ProgressBar } from './ProgressBar';
import { apiRestClient } from '../services/apiService';
import { useHasFramegridWritePermission } from '@/lib/permissions/hooks';
import { cn } from '@/lib/utils';

const EmbeddingsPopover: React.FC = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [hasEmbeddings, setHasEmbeddings] = useState(false);
  const [isQueued, setIsQueued] = useState(false);
  const [isOpen, setIsOpen] = useState(false);

  const { frameGridId } = useSelector((state: RootState) => state.frame);
  const { embeddingProgress, isListening: isListeningToEmbeddings } =
    useSelector((state: RootState) => state.embed);

  const hasWritePermission = useHasFramegridWritePermission();

  // Derived states for cleaner logic
  const isEmbeddingInProgress = embeddingProgress && isListeningToEmbeddings;
  const canComputeEmbeddings = hasWritePermission &&
    !isLoading &&
    !isEmbeddingInProgress &&
    !isQueued &&
    !hasEmbeddings;

  // Check embeddings status
  const checkEmbeddingsStatus = async () => {
    if (!frameGridId) return;

    try {
      const [embeddingsResponse, queuedResponse] = await Promise.all([
        apiRestClient.post(`/${frameGridId}/fg_has_embeddings`),
        apiRestClient.post(`/${frameGridId}/has_embedding_job`)
      ]);

      setHasEmbeddings(embeddingsResponse.data);
      setIsQueued(queuedResponse.data);

      // Clear loading state if nothing is in progress
      if (!embeddingsResponse.data && !queuedResponse.data && !isEmbeddingInProgress) {
        setIsLoading(false);
      }
    } catch (error) {
      console.error('Failed to check embeddings status:', error);
      setIsLoading(false);
      // Don't change queued state on error - let it reflect last known state
    }
  };

  // Check status on mount and when frameGridId changes
  useEffect(() => {
    checkEmbeddingsStatus();
  }, [frameGridId]);

  // Track previous value of isListeningToEmbeddings to detect transitions
  const prevIsListeningToEmbeddings = useRef(isListeningToEmbeddings);

  // Update embeddings status when computation completes
  useEffect(() => {
    // Check if isListeningToEmbeddings went from true -> false
    if (
      prevIsListeningToEmbeddings.current === true &&
      isListeningToEmbeddings === false
    ) {
      // Embeddings computation completed
      setHasEmbeddings(true);
      setIsLoading(false);
      setIsQueued(false);
    }

    // Update the ref for next comparison
    prevIsListeningToEmbeddings.current = isListeningToEmbeddings;
  }, [isListeningToEmbeddings]);

  // Clear queued state when embedding progress starts
  useEffect(() => {
    if (isEmbeddingInProgress && isQueued) {
      setIsQueued(false);
    }
  }, [isEmbeddingInProgress, isQueued]);

  const handleRecomputeEmbeddings = async () => {
    if (!canComputeEmbeddings || !frameGridId) return;

    setIsLoading(true);
    try {
      await apiRestClient.post(`/${frameGridId}/compute_embeddings`);

      // Update states to reflect new computation
      setHasEmbeddings(false);
      setIsQueued(true);
      setIsLoading(false); // Loading complete, now it's queued

      toast({
        title: 'Embeddings computation started',
        description: 'Embeddings are being recomputed in the background',
        variant: 'default',
      });
    } catch (error) {
      toast({
        title: 'Failed to start embeddings computation',
        description: 'Could not start embeddings computation',
        variant: 'destructive',
      });
      setIsLoading(false);
      // Don't set queued on error
    }
  };

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open);
    if (open) {
      checkEmbeddingsStatus();
    }
  };

  // Render status content
  const renderStatusContent = () => {
    if (isEmbeddingInProgress || isQueued || isLoading) {
      return (
        <div className="border rounded-sm bg-blue-50 border-blue-200 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-xs font-medium text-blue-800">
              Computing Embeddings
            </div>
            <div className="text-xs text-blue-700">
              {embeddingProgress?.indexing_phase || 'Queued'}
            </div>
          </div>

          {embeddingProgress && (
            <>
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs text-blue-700">
                  <span>Embedding Progress</span>
                  <span>{embeddingProgress.embedding_progress}%</span>
                </div>
                <ProgressBar
                  current={embeddingProgress.embedding_progress}
                  total={100}
                />
              </div>

              {embeddingProgress.indexing_progress > 0 && (
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs text-blue-700">
                    <span>Indexing Progress</span>
                    <span>{embeddingProgress.indexing_progress}%</span>
                  </div>
                  <ProgressBar
                    current={embeddingProgress.indexing_progress}
                    total={100}
                  />
                </div>
              )}
            </>
          )}
        </div>
      );
    }

    if (!hasEmbeddings) {
      return (
        <div className="border rounded-sm bg-red-50 border-red-200 p-3">
          <div className="text-xs font-medium text-red-800 mb-1">
            Embeddings Missing
          </div>
          <div className="text-xs text-red-700">
            Some runs are missing embeddings. If new agent runs are being added,
            embeddings will be computed automatically.
          </div>
        </div>
      );
    }

    return (
      <div className="border rounded-sm bg-green-50 border-green-200 p-2">
        <div className="text-xs font-medium text-green-800 mb-1">
          Embeddings Available
        </div>
        <div className="text-xs text-green-700">
          Embeddings are available for all runs.
        </div>
      </div>
    );
  };

  return (
    <Popover open={isOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn(
            'gap-2 px-2 h-7 text-gray-700 hover:bg-gray-50',
            isEmbeddingInProgress &&
              'text-blue-700 hover:bg-blue-100 bg-blue-50 border-blue-200'
          )}
          title={!hasEmbeddings ? 'Embeddings missing - click to manage' : 'Manage embeddings'}
        >
          <Database className="h-4 w-4" />
          Index{isEmbeddingInProgress && ` ${embeddingProgress.embedding_progress}%`}
          {isEmbeddingInProgress && (
            <div className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
          )}
        </Button>
      </PopoverTrigger>

      <PopoverContent className="w-96 p-3 space-y-3">
        <div className="space-y-1">
          <h3 className="text-sm font-medium">Indexing</h3>
          <p className="text-xs text-muted-foreground">
            Compute embedding indices to speed up time to first results.
          </p>
        </div>

        <div className="space-y-3">
          {renderStatusContent()}

          <Button
            onClick={handleRecomputeEmbeddings}
            disabled={!canComputeEmbeddings}
            className="w-full gap-2 h-7"
            size="sm"
          >
            <RefreshCw className={cn('h-3 w-3', isLoading && 'animate-spin')} />
            {isEmbeddingInProgress ? 'Computing...' : 'Compute Embeddings'}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default EmbeddingsPopover;
