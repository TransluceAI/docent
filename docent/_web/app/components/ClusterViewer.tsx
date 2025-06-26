import { ChevronDown, ChevronRight } from 'lucide-react';
import React, { useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import { useAppSelector } from '../store/hooks';
import { SearchResultWithCitations } from '../types/frameTypes';
import { useHasFramegridWritePermission } from '@/lib/permissions/hooks';
import { StreamedSearchResultClusterAssignment } from '../types/experimentViewerTypes';
import { SearchResultsSection } from './AgentRunCard';

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

// const SearchResultList: React.FC<{
//   clusterId: string;
//   searchResults: SearchResultWithCitations[];
//   searchQuery: string;
// }> = ({ clusterId, searchResults, searchQuery }) => {
//   const fgId = useAppSelector((state) => state.frame.frameGridId);
//   const router = useRouter();

//   if (!searchResults || searchResults.length === 0) {
//     return (
//       <div className="mt-2">
//         <div className="text-xs text-gray-500 italic">
//           No search results in this cluster
//         </div>
//       </div>
//     );
//   }

//   return (
//     <div className="mt-2 space-y-1">
//       <div className="flex items-center mb-1">
//         <div className="h-2 w-2 rounded-full bg-blue-500 mr-1.5"></div>
//         <span className="text-xs font-medium text-blue-700">
//           Search results ({searchResults.length})
//         </span>
//       </div>

//       {searchResults.map((searchResult, i) => {
//         return (
//           <div
//             key={i}
//             className={`group bg-blue-50 rounded-md p-1.5 text-xs text-blue-900 leading-snug mt-1 hover:bg-blue-100 transition-colors cursor-pointer border border-transparent hover:border-blue-200`}
//             onClick={(e) =>
//               navToAgentRun(
//                 e,
//                 router,
//                 window,
//                 searchResult.agent_run_id,
//                 undefined,
//                 undefined,
//                 fgId
//               )
//             }
//           >
//             <p className="mb-0.5">
//               {renderTextWithCitations(
//                 searchResult.value || '',
//                 searchResult.citations || [],
//                 searchResult.agent_run_id,
//                 router,
//                 window,
//                 undefined,
//                 fgId
//               )}
//             </p>
//             <div className="flex items-center gap-1 text-[10px] text-blue-600 mt-1">
//               <span className="opacity-70">
//                 {searchQuery}
//                 {searchResult.search_result_idx !== null && (
//                   <>, idx: {searchResult.search_result_idx}</>
//                 )}
//               </span>
//               <span className="ml-1 opacity-70">
//                 agent_run_id: {searchResult.agent_run_id}
//               </span>
//             </div>
//           </div>
//         );
//       })}
//     </div>
//   );
// };

export default function ClusterViewer({ searchQuery }: ClusterViewerProps) {
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(
    new Set()
  );

  const fgId = useAppSelector((state) => state.frame.frameGridId);
  const searchResultMap = useAppSelector(
    (state) => state.search.searchResultMap
  );
  const clusteredSearchResults = useAppSelector(
    (state) => state.search.clusteredSearchResults
  );
  const activeClusterTaskId = useAppSelector(
    (state) => state.search.activeClusterTaskId
  );
  const hasWritePermission = useHasFramegridWritePermission();

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
  //   if (!fgId || !hasWritePermission) return;

  //   try {
  //     await apiRestClient.delete(`/${fgId}/delete_search_cluster/${clusterId}`);
  //     // Refresh clusters after deletion
  //     const clustersResponse = await apiRestClient.get(
  //       `/${fgId}/get_existing_search_clusters?search_query=${encodeURIComponent(searchQuery)}`
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
        <div className="text-xs text-gray-500 flex items-center gap-2">
          <div className="animate-spin rounded-full h-3 w-3 border-2 border-gray-300 border-t-gray-500" />
          Clustering in progress...
        </div>
      </div>
    );
  }

  if (clusters.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      {clusters.map((cluster) => {
        const clusterSearchResults = getClusterSearchResults(cluster.id);
        const hasResults = clusterSearchResults.length > 0;
        const isExpanded = expandedClusters.has(cluster.id);

        return (
          <div key={cluster.id} className="space-y-2">
            <div className="text-xs p-1.5 bg-white rounded border border-gray-200 flex items-center gap-1.5">
              {/* Expand/collapse button on the left */}
              {(hasResults || activeClusterTaskId) && (
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-5 w-5 flex-shrink-0"
                  onClick={() => toggleClusterExpansion(cluster.id)}
                >
                  {isExpanded ? (
                    <ChevronDown className="h-3 w-3 text-gray-500" />
                  ) : (
                    <ChevronRight className="h-3 w-3 text-gray-500" />
                  )}
                </Button>
              )}
              {/* Cluster count */}
              {(hasResults || activeClusterTaskId) && (
                <div className="flex-shrink-0 flex items-center">
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="text-xs px-1.5 py-0.5 rounded-sm bg-gray-100 text-gray-600 cursor-default flex items-center min-w-[2rem] justify-center">
                          {activeClusterTaskId &&
                          clusterSearchResults.length === 0 ? (
                            <div className="animate-spin rounded-full h-3 w-3 border-2 border-gray-300 border-t-gray-500" />
                          ) : (
                            <>
                              {clusterSearchResults.length}
                              {activeClusterTaskId && (
                                <div className="animate-spin ml-1 rounded-full h-2 w-2 border-[1.5px] border-gray-300 border-t-gray-500 inline-block" />
                              )}
                            </>
                          )}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="text-xs">
                        {activeClusterTaskId &&
                        clusterSearchResults.length === 0
                          ? 'Clustering in progress...'
                          : `${clusterSearchResults.length} search result${clusterSearchResults.length !== 1 ? 's' : ''} in this cluster`}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              )}
              {/* Cluster centroid */}
              <div className="flex-1 text-xs text-gray-700 ml-1">
                <div className="flex items-center gap-2">
                  {cluster.centroid}
                </div>
              </div>
            </div>

            {/* Expanded search results */}
            {isExpanded && hasResults && (
              <div className="pl-4">
                <SearchResultsSection
                  searchResults={clusterSearchResults}
                  curSearchQuery={searchQuery}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
