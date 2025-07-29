import { ChevronDown, ChevronRight } from 'lucide-react';
import React, { useState, useMemo } from 'react';

import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import { useAppSelector } from '../store/hooks';
import { SearchResultWithCitations } from '../types/collectionTypes';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import { StreamedSearchResultClusterAssignment } from '../types/experimentViewerTypes';
import { SearchResultsList } from './SearchResults';

interface SearchCluster {
  id: string;
  centroid: string;
  search_query: string;
}

interface SearchResultClusterAssignment {
  id: string;
  search_result_id: string;
  cluster_id: string;
  decision: boolean;
  reason: string;
  agent_run_id: string;
}

interface ClusterViewerProps {
  searchQuery: string;
}

export default function ClusterViewer({ searchQuery }: ClusterViewerProps) {
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(
    new Set()
  );

  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const searchResultMap = useAppSelector(
    (state) => state.search.searchResultMap
  );
  const clusteredSearchResults = useAppSelector(
    (state) => state.search.clusteredSearchResults
  );
  const activeClusterTaskId = useAppSelector(
    (state) => state.search.activeClusterTaskId
  );
  const hasWritePermission = useHasCollectionWritePermission();

  // Get all search results for the current search query
  const allSearchResults = useMemo(() => {
    if (!searchQuery || !searchResultMap) return [];

    const allResults: SearchResultWithCitations[] = [];

    // Iterate through all agent runs in the search result map
    Object.values(searchResultMap).forEach((agentRunResults) => {
      if (agentRunResults && agentRunResults[searchQuery]) {
        const results = agentRunResults[searchQuery].filter(
          (attr) => attr.value !== null
        );
        allResults.push(...results);
      }
    });

    return allResults;
  }, [searchQuery, searchResultMap]);

  // Get search result IDs that are assigned to clusters
  const assignedSearchResultIds = useMemo(() => {
    if (!clusteredSearchResults) return new Set<string>();

    const assignedIds = new Set<string>();

    for (const [centroid, assignments] of Object.entries(
      clusteredSearchResults
    )) {
      assignments.forEach(
        (assignment: StreamedSearchResultClusterAssignment) => {
          if (assignment.decision) {
            assignedIds.add(assignment.search_result_id);
          }
        }
      );
    }

    return assignedIds;
  }, [clusteredSearchResults]);

  // Get residual search results (not assigned to any cluster)
  const residualSearchResults = useMemo(() => {
    return allSearchResults.filter(
      (result) => !assignedSearchResultIds.has(result.id)
    );
  }, [allSearchResults, assignedSearchResultIds]);

  // Create clusters dynamically from streaming data
  const clusters: SearchCluster[] = React.useMemo(() => {
    if (!clusteredSearchResults) return [];

    const clusterMap = new Map<string, SearchCluster>();

    for (const [centroid, assignments] of Object.entries(
      clusteredSearchResults
    )) {
      if (assignments.length > 0) {
        // Use the first assignment to get cluster info
        const firstAssignment = assignments[0];
        clusterMap.set(firstAssignment.cluster_id, {
          id: firstAssignment.cluster_id,
          centroid: centroid,
          search_query: searchQuery,
        });
      }
    }

    return Array.from(clusterMap.values());
  }, [clusteredSearchResults, searchQuery]);

  const toggleClusterExpansion = (clusterId: string) => {
    const newExpanded = new Set(expandedClusters);
    if (newExpanded.has(clusterId)) {
      newExpanded.delete(clusterId);
    } else {
      newExpanded.add(clusterId);
    }
    setExpandedClusters(newExpanded);
  };

  // Get search results for a specific cluster
  const getClusterSearchResults = (
    clusterId: string
  ): SearchResultWithCitations[] => {
    if (!clusteredSearchResults) {
      return [];
    }

    const searchResults: SearchResultWithCitations[] = [];

    // Find the cluster by ID and get its assignments
    for (const [centroid, assignments] of Object.entries(
      clusteredSearchResults
    )) {
      const clusterAssignments = assignments.filter(
        (assignment: StreamedSearchResultClusterAssignment) =>
          assignment.cluster_id === clusterId && assignment.decision
      );

      // For each assignment, find the search result in the searchResultMap
      clusterAssignments.forEach(
        (assignment: StreamedSearchResultClusterAssignment) => {
          // Find the search result by iterating through all agent runs and search queries
          if (searchResultMap) {
            for (const agentRunId in searchResultMap) {
              for (const query in searchResultMap[agentRunId]) {
                const searchResult = searchResultMap[agentRunId][query].find(
                  (result: SearchResultWithCitations) =>
                    result.id === assignment.search_result_id
                );

                if (searchResult && searchResult.value) {
                  searchResults.push(searchResult);
                  break; // Found the result, no need to continue searching
                }
              }
            }
          }
        }
      );
    }

    return searchResults;
  };

  // const handleDeleteCluster = async (clusterId: string) => {
  //   if (!collectionId || !hasWritePermission) return;

  //   try {
  //     await apiRestClient.delete(`/${collectionId}/delete_search_cluster/${clusterId}`);
  //     // Refresh clusters after deletion
  //     const clustersResponse = await apiRestClient.get(
  //       `/${collectionId}/get_existing_search_clusters?search_query=${encodeURIComponent(searchQuery)}`
  //     );
  //     setClusters(clustersResponse.data || []);
  //   } catch (err) {
  //     console.error('Error deleting cluster:', err);
  //     setError('Failed to delete cluster');
  //   }
  // };

  // Show loading state when clustering is in progress but no clusters exist yet
  if (activeClusterTaskId && clusters.length === 0) {
    return (
      <div className="space-y-2">
        <div className="text-xs text-muted-foreground flex items-center gap-2">
          <div className="animate-spin rounded-full h-3 w-3 border-2 border-border border-t-gray-500" />
          Loading clusters...
        </div>
        {/* Show all search results while clustering is in progress */}
        {allSearchResults.length > 0 && (
          <div className="pt-1 mt-1 border-t border-border text-xs">
            <div className="flex items-center mb-1 justify-between shrink-0">
              <div className="flex items-center">
                <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
                <span className="text-xs font-medium text-primary">
                  Search results
                </span>
              </div>
              <span className="text-xs text-muted-foreground">
                {allSearchResults.length} hits for current query
              </span>
            </div>
            <div className="overflow-y-auto space-y-1 custom-scrollbar">
              <SearchResultsList
                searchResults={allSearchResults}
                curSearchQuery={searchQuery}
              />
            </div>
          </div>
        )}
      </div>
    );
  }

  // If no clusters exist, show all search results
  if (clusters.length === 0) {
    if (allSearchResults.length === 0) {
      return null;
    }

    return (
      <div className="space-y-2">
        <div className="pt-1 mt-1 border-t border-border text-xs">
          <div className="flex items-center mb-1 justify-between shrink-0">
            <div className="flex items-center">
              <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
              <span className="text-xs font-medium text-primary">
                Search results
              </span>
            </div>
            <span className="text-xs text-muted-foreground">
              {allSearchResults.length} hits for current query
            </span>
          </div>
          <div className="overflow-y-auto space-y-1 custom-scrollbar">
            <SearchResultsList
              searchResults={allSearchResults}
              curSearchQuery={searchQuery}
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {clusters.map((cluster) => {
        const clusterSearchResults = getClusterSearchResults(cluster.id);
        const hasResults = clusterSearchResults.length > 0;
        const isExpanded = expandedClusters.has(cluster.id);

        return (
          <div key={cluster.id} className="space-y-2">
            <div className="text-xs p-1.5 bg-background rounded border border-border flex items-center gap-1.5">
              {/* Expand/collapse button on the left */}

              <Button
                size="icon"
                variant="ghost"
                className="h-5 w-5 flex-shrink-0"
                onClick={() => toggleClusterExpansion(cluster.id)}
              >
                {isExpanded ? (
                  <ChevronDown className="h-3 w-3 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-3 w-3 text-muted-foreground" />
                )}
              </Button>

              {/* Cluster count */}

              <div className="flex-shrink-0 flex items-center">
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="text-xs px-1.5 py-0.5 rounded-sm bg-muted text-muted-foreground cursor-default flex items-center min-w-[2rem] justify-center">
                        {activeClusterTaskId &&
                        clusterSearchResults.length === 0 ? (
                          <div className="animate-spin rounded-full h-3 w-3 border-2 border-border border-t-gray-500" />
                        ) : (
                          <>
                            {clusterSearchResults.length}
                            {activeClusterTaskId && (
                              <div className="animate-spin ml-1 rounded-full h-2 w-2 border-[1.5px] border-border border-t-gray-500 inline-block" />
                            )}
                          </>
                        )}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="text-xs">
                      {activeClusterTaskId && clusterSearchResults.length === 0
                        ? 'Clustering in progress...'
                        : `${clusterSearchResults.length} search result${clusterSearchResults.length !== 1 ? 's' : ''} in this cluster`}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>

              {/* Cluster centroid */}
              <div className="flex-1 text-xs text-primary ml-1">
                <div className="flex items-center gap-2">
                  {cluster.centroid}
                </div>
              </div>
            </div>

            {/* Expanded search results */}
            {isExpanded && hasResults && (
              <div className="pl-4">
                <SearchResultsList
                  searchResults={clusterSearchResults}
                  curSearchQuery={searchQuery}
                />
              </div>
            )}
          </div>
        );
      })}

      {/* Residuals section - show search results not assigned to any cluster */}
      {residualSearchResults.length > 0 && (
        <div className="space-y-2">
          <div className="pt-1 mt-1 border-t border-border text-xs">
            <div className="flex items-center mb-1 justify-between shrink-0">
              <div className="flex items-center">
                <div className="h-2 w-2 rounded-full bg-gray-500 mr-1.5"></div>
                <span className="text-xs font-medium text-primary">
                  Other search results
                </span>
              </div>
              <span className="text-xs text-muted-foreground">
                {residualSearchResults.length} unclustered result
                {residualSearchResults.length !== 1 ? 's' : ''}
              </span>
            </div>
            <div className="overflow-y-auto space-y-1 custom-scrollbar">
              <SearchResultsList
                searchResults={residualSearchResults}
                curSearchQuery={searchQuery}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
