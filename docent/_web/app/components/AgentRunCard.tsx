'use client';
import { navToAgentRun } from '@/lib/nav';
import { useRouter } from 'next/navigation';
import { useAppSelector } from '../store/hooks';
import { AgentRunMetadata } from './AgentRunMetadata';
import { SearchResultWithCitations } from '../types/frameTypes';
import { renderTextWithCitations } from '@/lib/renderCitations';
import { useMemo, useState } from 'react';
import { RegexSnippet } from '../types/experimentViewerTypes';

interface AgentRunCardProps {
  agentRunId: string;
}

export default function AgentRunCard({ agentRunId }: AgentRunCardProps) {
  const router = useRouter();
  // Frame slice
  const frameGridId = useAppSelector((state) => state.frame.frameGridId);
  const agentRunMetadata = useAppSelector(
    (state) => state.frame.agentRunMetadata
  );

  // Search slice
  const curSearchQuery = useAppSelector((state) => state.search.curSearchQuery);
  const searchResultMap = useAppSelector(
    (state) => state.search.searchResultMap
  );

  // Experiment viewer slice
  const { regexSnippets } = useAppSelector((state) => state.experimentViewer);

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
    <div className="flex flex-col p-1 border rounded text-xs bg-white/80 hover:bg-gray-50 min-w-0 overflow-x-hidden">
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
            frameGridId
          )
        }
      >
        <div className="flex justify-between items-center">
          <span className="text-gray-600">
            Agent Run <span className="font-mono">{agentRunId}</span>
          </span>
          <div className="flex gap-2">
            <span
              className="text-blue-600 font-medium hover:text-blue-700"
              onMouseDown={(e) => {
                navToAgentRun(
                  e,
                  router,
                  window,
                  agentRunId,
                  undefined,
                  undefined,
                  frameGridId,
                  curSearchQuery
                );
              }}
            >
              View
            </span>
          </div>
        </div>
        {/* Display metadata if available */}
        {agentRunMetadata && agentRunMetadata[agentRunId] && (
          <AgentRunMetadata agentRunId={agentRunId} />
        )}
      </div>

      <RegexSnippetsSection regexSnippets={regexSnippets?.[agentRunId]} />

      {/* Replace the inline attribute section with the new component */}
      {searchResults && curSearchQuery && (
        <SearchResultsSection
          curSearchQuery={curSearchQuery}
          searchResults={searchResults}
        />
      )}
    </div>
  );
}

const RegexSnippetsSection: React.FC<{
  regexSnippets?: RegexSnippet[];
}> = ({ regexSnippets }) => {
  if (!regexSnippets || regexSnippets.length === 0) {
    return null;
  }

  return (
    <div className="border-indigo-100 border-t pt-1 mt-1 space-y-1">
      <div className="flex items-center">
        <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
        <span className="text-xs font-medium text-indigo-700">
          Regex matches
        </span>
      </div>

      {regexSnippets?.map((snippetData, index) => (
        <HighlightedSnippet key={index} snippetData={snippetData} />
      ))}
    </div>
  );
};

const HighlightedSnippet: React.FC<{ snippetData: RegexSnippet }> = ({
  snippetData,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  try {
    // Defensive coding to handle missing or malformed data
    if (!snippetData || typeof snippetData !== 'object') {
      return (
        <p className="text-xs text-red-600">Error: Invalid snippet data</p>
      );
    }

    const { snippet, match_start, match_end } = snippetData;

    // Check if we have all required properties with valid types
    if (
      typeof snippet !== 'string' ||
      typeof match_start !== 'number' ||
      typeof match_end !== 'number'
    ) {
      return (
        <p className="text-xs text-red-600">Error: Invalid snippet format</p>
      );
    }

    // Verify match positions are within bounds
    if (
      match_start < 0 ||
      match_end > snippet.length ||
      match_start >= match_end
    ) {
      return <p className="text-xs">{snippet}</p>;
    }

    const before = snippet.substring(0, match_start);
    const matched = snippet.substring(match_start, match_end);
    const after = snippet.substring(match_end);

    return (
      <div
        className="bg-indigo-50 p-2 rounded-md border border-transparent hover:border-indigo-200 max-w-full cursor-pointer transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div
          className={`overflow-y-auto ${isExpanded ? '' : 'max-h-20'}`}
          style={{
            scrollbarWidth: 'thin',
            scrollbarColor: '#a5b3e6 #e0e7ff',
          }}
        >
          <span className="text-xs text-indigo-900 break-words whitespace-pre-wrap">
            {before}
            <span className="px-0.5 py-0.25 bg-indigo-200 text-indigo-800 rounded">
              {matched}
            </span>
            {after}
          </span>
        </div>
      </div>
    );
  } catch (error) {
    return <p className="text-xs text-red-600">Error rendering snippet</p>;
  }
};

interface SearchResultsSectionProps {
  curSearchQuery: string;
  searchResults: SearchResultWithCitations[];
}

export const SearchResultsSection: React.FC<SearchResultsSectionProps> = ({
  curSearchQuery,
  searchResults,
}) => {
  if (searchResults.length === 0) {
    return null;
  }

  return (
    <div className="pt-1 mt-1 border-t border-indigo-100 text-xs space-y-1">
      <div className="flex items-center mb-1">
        <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
        <span className="text-xs font-medium text-indigo-700">
          Search results
        </span>
      </div>

      {/* Render only the attributes for the current query */}
      {searchResults.map((searchResult, idx) => (
        <SearchResultCard
          key={idx}
          curSearchQuery={curSearchQuery}
          searchResult={searchResult}
        />
      ))}
    </div>
  );
};

export const SearchResultCard: React.FC<{
  curSearchQuery: string;
  searchResult: SearchResultWithCitations;
}> = ({ curSearchQuery, searchResult }) => {
  const router = useRouter();
  const frameGridId = useAppSelector((state) => state.frame.frameGridId);

  const resultText = searchResult.value;
  if (!resultText) {
    return null;
  }
  const agentRunId = searchResult.agent_run_id;
  const citations = searchResult.citations || [];
  // const currentVote = voteState?.[dataId]?.[attributeText];

  return (
    <div
      className="group bg-indigo-50 rounded-md p-1 text-xs text-indigo-900 leading-snug mt-1 hover:bg-indigo-100 transition-colors cursor-pointer border border-transparent hover:border-indigo-200"
      onMouseDown={(e) => {
        const firstCitation = citations.length > 0 ? citations[0] : null;
        navToAgentRun(
          e,
          router,
          window,
          agentRunId,
          firstCitation?.transcript_idx ?? undefined,
          firstCitation?.block_idx,
          frameGridId,
          curSearchQuery
        );
      }}
    >
      <div className="flex flex-col">
        <div className="flex items-start justify-between gap-2">
          <p className="mb-0.5 flex-1">
            {renderTextWithCitations(
              resultText,
              citations,
              agentRunId,
              router,
              window,
              curSearchQuery,
              frameGridId
            )}
          </p>
        </div>
        <div className="flex items-center gap-1 text-[10px] text-indigo-600 mt-1">
          <span className="opacity-70">{curSearchQuery}</span>
        </div>
      </div>
    </div>
  );
};
