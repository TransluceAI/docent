import { useState, useEffect, useRef, useCallback } from 'react';
import { CollectionCounts } from '../api/collectionApi';
import { BASE_URL } from '@/app/constants';

const BATCH_SIZE = 20;

interface UseCollectionCountsResult {
  counts: Record<string, CollectionCounts>;
  isLoading: boolean;
  refetch: () => void;
}

export function useCollectionCounts(
  collectionIds: string[]
): UseCollectionCountsResult {
  const [counts, setCounts] = useState<Record<string, CollectionCounts>>({});
  const [isLoading, setIsLoading] = useState(false);
  const fetchedRef = useRef<Set<string>>(new Set());
  const [refetchTrigger, setRefetchTrigger] = useState(0);

  const refetch = useCallback(() => {
    // Clear the fetched set to force a re-fetch
    fetchedRef.current.clear();
    setCounts({});
    setRefetchTrigger((prev) => prev + 1);
  }, []);

  useEffect(() => {
    if (collectionIds.length === 0) return;

    // Filter to only IDs we haven't fetched yet
    const newIds = collectionIds.filter((id) => !fetchedRef.current.has(id));
    if (newIds.length === 0) return;

    // AbortController to cancel in-flight requests on cleanup
    const abortController = new AbortController();

    const fetchBatches = async () => {
      setIsLoading(true);

      // Split into chunks
      const chunks: string[][] = [];
      for (let i = 0; i < newIds.length; i += BATCH_SIZE) {
        chunks.push(newIds.slice(i, i + BATCH_SIZE));
      }

      try {
        // Fetch chunks sequentially to keep DB load constant
        for (const chunk of chunks) {
          const res = await fetch(`${BASE_URL}/rest/collections/counts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ collection_ids: chunk }),
            signal: abortController.signal,
          });

          if (!res.ok) throw new Error(`HTTP ${res.status}`);

          const result = (await res.json()) as Record<string, CollectionCounts>;

          // Mark these IDs as fetched
          chunk.forEach((id) => fetchedRef.current.add(id));

          // Update counts incrementally so UI shows results as they come in
          setCounts((prev) => ({ ...prev, ...result }));
        }
      } catch (error) {
        // Ignore abort errors - they're expected on cleanup
        if (error instanceof Error && error.name === 'AbortError') return;
        console.error('Failed to fetch collection counts:', error);
      } finally {
        // Only set loading to false if not aborted
        if (!abortController.signal.aborted) {
          setIsLoading(false);
        }
      }
    };

    fetchBatches();

    // Cleanup: abort any in-flight requests when deps change or unmount
    return () => {
      abortController.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(collectionIds), refetchTrigger]);

  return { counts, isLoading, refetch };
}
