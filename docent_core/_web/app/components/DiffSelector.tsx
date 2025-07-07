import React from 'react';
import { useGetAllDiffQueriesQuery } from '@/app/api/diffApi';
import { useAppSelector } from '@/app/store/hooks';
import { Button } from '@/components/ui/button';

const DiffSelector: React.FC = () => {
  const collectionId = useAppSelector((state) => state.collection.collectionId);

  const {
    data: diffQueries,
    isLoading,
    refetch,
  } = useGetAllDiffQueriesQuery(
    { collectionId: collectionId! },
    { skip: !collectionId }
  );

  const handleGetQueries = () => {
    if (collectionId) {
      refetch();
    }
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
              <div key={query.id} className="text-xs bg-secondary p-2 rounded">
                <div className="font-mono text-xs">{query.id}</div>
                {query.focus && (
                  <div className="text-muted-foreground">
                    Focus: {query.focus}
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
