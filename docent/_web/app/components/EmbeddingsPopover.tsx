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
  const [hasMissingEmbeddings, setHasMissingEmbeddings] = useState(false);

  const { frameGridId } = useSelector((state: RootState) => state.frame);
  const { embeddingProgress, isListening: isListeningToEmbeddings } =
    useSelector((state: RootState) => state.embed);

  const hasWritePermission = useHasFramegridWritePermission();

  // Function to check for missing embeddings
  const checkForMissingEmbeddings = async () => {
    if (!frameGridId) return;

    try {
      const hasEmbeddingsResponse = await apiRestClient.post(
        `/${frameGridId}/fg_has_embeddings`
      );
      const hasEmbeddings = hasEmbeddingsResponse.data;
      setHasMissingEmbeddings(!hasEmbeddings);
    } catch (error) {
      console.error('Failed to check embeddings status:', error);
    }
  };

  // Check for missing embeddings when frameGridId changes
  useEffect(() => {
    checkForMissingEmbeddings();
  }, [frameGridId]);

  const handleRecomputeEmbeddings = async () => {
    if (!frameGridId || !hasWritePermission) return;

    setIsLoading(true);
    try {
      await apiRestClient.post(`/${frameGridId}/compute_embeddings`);
      // Reset the missing embeddings state since we just started computation
      setHasMissingEmbeddings(false);
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
    } finally {
      setIsLoading(false);
    }
  };

  const isEmbeddingInProgress = embeddingProgress && isListeningToEmbeddings;

  // Track previous value of isListeningToEmbeddings to detect transitions
  const prevIsListeningToEmbeddings = useRef(isListeningToEmbeddings);

  useEffect(() => {
    // Check if isListeningToEmbeddings went from true -> false
    if (
      prevIsListeningToEmbeddings.current === true &&
      isListeningToEmbeddings === false
    ) {
      // Embeddings computation completed, so we have embeddings now
      setHasMissingEmbeddings(false);
    }

    // Update the ref for next comparison
    prevIsListeningToEmbeddings.current = isListeningToEmbeddings;
  }, [isListeningToEmbeddings]);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn(
            'gap-2 px-2 h-7',
            hasMissingEmbeddings
              ? 'text-red-700  bg-red-50 hover:bg-red-100 border-red-200'
              : 'text-gray-700  hover:bg-gray-50',
            isEmbeddingInProgress &&
              'text-blue-700 hover:bg-blue-100 bg-blue-50 border-blue-200'
          )}
          title={
            hasMissingEmbeddings
              ? 'Embeddings missing - click to manage'
              : 'Manage embeddings'
          }
        >
          <Database className="h-4 w-4" />
          Index{' '}
          {isEmbeddingInProgress
            ? `${embeddingProgress.embedding_progress}%`
            : ''}
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
          {isEmbeddingInProgress ? (
            <div className="border rounded-sm bg-blue-50 border-blue-200 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-xs font-medium text-blue-800">
                  Computing Embeddings
                </div>
                <div className="text-xs text-blue-700">
                  {embeddingProgress.indexing_phase}
                </div>
              </div>
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
              {embeddingProgress.indexing_phase !== 'not_required' &&
                embeddingProgress.indexing_progress > 0 && (
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
            </div>
          ) : hasMissingEmbeddings ? (
            <div className="border rounded-sm bg-red-50 border-red-200 p-3">
              <div className="text-xs font-medium text-red-800 mb-1">
                Embeddings Missing
              </div>
              <div className="text-xs text-red-700">
                Some runs are missing embeddings. Click the button below to
                compute them.
              </div>
            </div>
          ) : (
            <div className="border rounded-sm bg-green-50 border-green-200 p-2">
              <div className="text-xs font-medium text-green-800 mb-1">
                Embeddings Available
              </div>
              <div className="text-xs text-green-700">
                Embeddings are available for all runs.
              </div>
            </div>
          )}

          {/* Recompute Button */}
          <Button
            onClick={handleRecomputeEmbeddings}
            disabled={!hasWritePermission || isLoading || isEmbeddingInProgress}
            className="w-full gap-2 h-7"
            size="sm"
          >
            {isLoading ? (
              <RefreshCw className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            {isEmbeddingInProgress
              ? 'Computing...'
              : hasMissingEmbeddings
                ? 'Compute Embeddings'
                : 'Recompute Embeddings'}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default EmbeddingsPopover;
