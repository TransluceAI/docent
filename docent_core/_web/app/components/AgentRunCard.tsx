'use client';
import { navToAgentRun } from '@/lib/nav';
import { useRouter } from 'next/navigation';
import { useAppSelector } from '../store/hooks';
import { AgentRunMetadata } from './AgentRunMetadata';
import { useMemo } from 'react';
import { cn } from '@/lib/utils';
// import { SearchResultsList } from './SearchResults';

interface AgentRunCardProps {
  agentRunId: string;
}

export default function AgentRunCard({ agentRunId }: AgentRunCardProps) {
  const router = useRouter();
  // Collection slice
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const agentRunMetadata = useAppSelector(
    (state) => state.collection.agentRunMetadata
  );

  // Search slice
  const curSearchQuery = useAppSelector((state) => state.search.curSearchQuery);
  const searchResultMap = useAppSelector(
    (state) => state.search.searchResultMap
  );

  // Hover state
  const hoveredAgentRunId = useAppSelector(
    (state) => state.experimentViewer.hoveredAgentRunId
  );
  const isHighlighted = hoveredAgentRunId === agentRunId;



  // Get search results
  const searchResults = useMemo(() => {
    if (!curSearchQuery) return null;
    const results = searchResultMap?.[agentRunId]?.[curSearchQuery].filter(
      (attr) => attr.value !== null
    );
    if (results === undefined || results.length === 0) return null;
    return results;
  }, [curSearchQuery, searchResultMap, agentRunId]);

  return (
    <div
      className={cn(
        'flex flex-col p-1 border rounded text-xs min-w-0 overflow-x-hidden transition-all duration-200',
        isHighlighted
          ? 'bg-indigo-bg border-indigo-border shadow-md'
          : 'bg-secondary/30 hover:bg-secondary border-border'
      )}
    >
      <div
        className="cursor-pointer"
        onMouseDown={(e) =>
          navToAgentRun(
            e,
            router,
            window,
            agentRunId,
            undefined,
            undefined,
            collectionId
          )
        }
      >
        <div className="flex justify-between pb-0.5 items-center">
          <span className="text-primary">
            Agent Run <span className="font-mono">{agentRunId}</span>
          </span>
          <div className="flex gap-2">
            <span
              className="text-blue-text font-medium hover:text-blue-text/80"
              onMouseDown={(e) => {
                navToAgentRun(
                  e,
                  router,
                  window,
                  agentRunId,
                  undefined,
                  undefined,
                  collectionId,
                  curSearchQuery
                );
              }}
            >
              View
            </span>
          </div>
        </div>
        <div>
          {/* Display metadata if available */}
          {agentRunMetadata && agentRunMetadata[agentRunId] && (
            <AgentRunMetadata agentRunId={agentRunId} />
          )}
        </div>
      </div>

      {/* <RegexSnippetsSection regexSnippets={regexSnippets?.[agentRunId]} /> */}

      {/* {searchResults && curSearchQuery && (
        <SearchResultsList
          curSearchQuery={curSearchQuery}
          searchResults={searchResults}
        />
      )} */}
    </div>
  );
}

// const RegexSnippetsSection: React.FC<{
//   regexSnippets?: RegexSnippet[];
// }> = ({ regexSnippets }) => {
//   if (!regexSnippets || regexSnippets.length === 0) {
//     return null;
//   }

//   return (
//     <div className="border-indigo-100 border-t pt-1 mt-1 space-y-1">
//       <div className="flex items-center">
//         <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
//         <span className="text-xs font-medium text-primary">
//           Regex matches
//         </span>
//       </div>

//       {regexSnippets?.map((snippetData, index) => (
//         <HighlightedSnippet key={index} snippetData={snippetData} />
//       ))}
//     </div>
//   );
// };

// const HighlightedSnippet: React.FC<{ snippetData: RegexSnippet }> = ({
//   snippetData,
// }) => {
//   const [isExpanded, setIsExpanded] = useState(false);
//   try {
//     // Defensive coding to handle missing or malformed data
//     if (!snippetData || typeof snippetData !== 'object') {
//       return (
//         <p className="text-xs text-destructive">Error: Invalid snippet data</p>
//       );
//     }

//     const { snippet, match_start, match_end } = snippetData;

//     // Check if we have all required properties with valid types
//     if (
//       typeof snippet !== 'string' ||
//       typeof match_start !== 'number' ||
//       typeof match_end !== 'number'
//     ) {
//       return (
//         <p className="text-xs text-destructive">Error: Invalid snippet format</p>
//       );
//     }

//     // Verify match positions are within bounds
//     if (
//       match_start < 0 ||
//       match_end > snippet.length ||
//       match_start >= match_end
//     ) {
//       return <p className="text-xs">{snippet}</p>;
//     }

//     const before = snippet.substring(0, match_start);
//     const matched = snippet.substring(match_start, match_end);
//     const after = snippet.substring(match_end);

//     return (
//       <div
//         className="bg-indigo-50 p-2 rounded-md border border-transparent hover:border-indigo-200 max-w-full cursor-pointer transition-colors"
//         onClick={() => setIsExpanded(!isExpanded)}
//       >
//         <div
//           className={`overflow-y-auto ${isExpanded ? '' : 'max-h-20'}`}
//           style={{
//             scrollbarWidth: 'thin',
//             scrollbarColor: '#a5b3e6 #e0e7ff',
//           }}
//         >
//           <span className="text-xs text-indigo-900 break-words whitespace-pre-wrap">
//             {before}
//             <span className="px-0.5 py-0.25 bg-indigo-200 text-primary rounded">
//               {matched}
//             </span>
//             {after}
//           </span>
//         </div>
//       </div>
//     );
//   } catch (error) {
//     return <p className="text-xs text-destructive">Error rendering snippet</p>;
//   }
// };
