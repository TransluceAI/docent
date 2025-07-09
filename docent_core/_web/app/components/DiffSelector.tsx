import React, { useState } from 'react';
import {
  useGetAllDiffQueriesQuery,
  useListenForDiffResultsQuery,
} from '@/app/api/diffApi';
import { useAppSelector } from '@/app/store/hooks';
import { Button } from '@/components/ui/button';

const DiffSelector: React.FC = () => {
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const [selectedQueryId, setSelectedQueryId] = useState<string | null>(null);
  const [isCancelled, setIsCancelled] = useState<boolean>(false);

  const {
    data: diffQueries,
    isLoading,
    refetch,
  } = useGetAllDiffQueriesQuery(
    { collectionId: collectionId! },
    { skip: !collectionId }
  );

  // Start listening for diff results when a query is selected
  const { data } = useListenForDiffResultsQuery(
    { collectionId: collectionId!, queryId: selectedQueryId! },
    { skip: !collectionId || !selectedQueryId || isCancelled }
  );
  const isSSEConnected = data?.isSSEConnected;

  const handleGetQueries = () => {
    if (collectionId) {
      refetch();
    }
  };

  const handleQueryClick = (queryId: string) => {
    setSelectedQueryId(queryId);
    setIsCancelled(false); // Reset cancel state when selecting a new query
    console.log('Started listening for diff results for query:', queryId);
  };

  const handleCancelConnection = () => {
    setIsCancelled(true);
    console.log('Cancelled SSE connection for query:', selectedQueryId);
  };

  return (
    <div className="space-y-2">
      <div>
        <div className="text-sm font-semibold">Diffing</div>
        <div className="text-xs text-muted-foreground">
          Get all diff queries for this collection
        </div>
      </div>

      <Button
        onClick={handleGetQueries}
        disabled={!collectionId || isLoading}
        size="sm"
        className="text-xs"
      >
        {isLoading ? 'Loading...' : 'Get Diff Queries'}
      </Button>

      {diffQueries && diffQueries.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium">
            Found {diffQueries.length} diff queries:
          </div>
          <div className="space-y-1">
            {diffQueries.map((query) => (
              <div
                key={query.id}
                className={`text-xs p-2 rounded cursor-pointer transition-colors ${
                  selectedQueryId === query.id
                    ? 'bg-blue-bg border border-blue-border'
                    : 'bg-secondary hover:bg-secondary/80'
                }`}
                onClick={() => handleQueryClick(query.id)}
              >
                <div className="font-mono text-xs">{query.id}</div>
                {query.focus && (
                  <div className="text-muted-foreground">
                    Focus: {query.focus}
                  </div>
                )}
                {selectedQueryId === query.id && (
                  <div className="text-blue-text text-xs mt-1 flex items-center justify-between">
                    <span>
                      {isSSEConnected ? 'Connected' : 'Not connected'}
                    </span>
                    {isSSEConnected && (
                      <Button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCancelConnection();
                        }}
                        size="sm"
                        variant="outline"
                        className="text-xs h-6 px-2 ml-2"
                      >
                        Cancel
                      </Button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {diffQueries && diffQueries.length === 0 && (
        <div className="text-xs text-muted-foreground">
          No diff queries found for this collection.
        </div>
      )}
    </div>
  );
};

export default DiffSelector;
