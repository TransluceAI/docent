'use client';
import { navToAgentRun } from '@/lib/nav';
import { useRouter } from 'next/navigation';
import { useAppSelector, useAppDispatch } from '../store/hooks';
import { SearchResultWithCitations } from '../types/collectionTypes';
import { renderTextWithCitations } from '@/lib/renderCitations';
import { openAgentRunInDashboard } from '../store/transcriptSlice';
import { setHoveredAgentRunId } from '../store/experimentViewerSlice';
import { useMemo } from 'react';


export function SearchResultsSection() {
    // Search slice
    const curSearchQuery = useAppSelector((state) => state.search.curSearchQuery);
    const searchResultMap = useAppSelector(
        (state) => state.search.searchResultMap
    );

    // const currentSearchHitCount = useAppSelector(
    //     (state) => state.search.currentSearchHitCount
    // );

    // Get all search results from all agent runs
    const searchResults = useMemo(() => {
        if (!curSearchQuery || !searchResultMap) return null;

        const allResults: SearchResultWithCitations[] = [];

        // Iterate through all agent runs in the search result map
        Object.values(searchResultMap).forEach((agentRunResults) => {
            if (agentRunResults && agentRunResults[curSearchQuery]) {
                const results = agentRunResults[curSearchQuery].filter(
                    (attr) => attr.value !== null
                );
                allResults.push(...results);
            }
        });

        if (allResults.length === 0) return null;
        return allResults;
    }, [curSearchQuery, searchResultMap]);


    return (
        <>
            {curSearchQuery && (
                <SearchResultsList
                    curSearchQuery={curSearchQuery}
                    searchResults={searchResults ?? []}
                    usePreview={true}
                />
            )}
        </>
    )

}

interface SearchResultsListProps {
    curSearchQuery: string;
    searchResults: SearchResultWithCitations[];
    usePreview?: boolean;
}

export const SearchResultsList = ({
    curSearchQuery,
    searchResults,
    usePreview = true,
}: SearchResultsListProps) => {
    if (searchResults.length === 0) {
        return null;
    }

    // const currentSearchHitCount = useAppSelector(
    //     (state) => state.search.currentSearchHitCount
    // );

    return (
        <div className="pt-1 mt-1 border-t border-border text-xs">
            {/* Fixed header */}
            <div className="flex items-center mb-1 justify-between shrink-0">
                <div className="flex items-center">
                <div className="h-2 w-2 rounded-full bg-indigo-500 mr-1.5"></div>
                <span className="text-xs font-medium text-primary">
                    Search results
                </span>
                </div>
                <span className="text-xs text-muted-foreground">
                    {searchResults.length} hits for current query
                </span>
            </div>

            {/* Scrollable results container */}
            <div className="h-96 overflow-y-auto space-y-1 custom-scrollbar">
                {searchResults.map((searchResult, idx) => (
                    <SearchResultCard
                        key={idx}
                        curSearchQuery={curSearchQuery}
                        searchResult={searchResult}
                        usePreview={usePreview}
                    />
                ))}
            </div>
        </div>
    );
};

interface SearchResultCardProps {
    curSearchQuery: string;
    searchResult: SearchResultWithCitations;
    usePreview: boolean;
}

export const SearchResultCard = ({ curSearchQuery, searchResult, usePreview }: SearchResultCardProps) => {
    const router = useRouter();
    const dispatch = useAppDispatch();
    const collectionId = useAppSelector((state) => state.collection.collectionId);

    const resultText = searchResult.value;
    if (!resultText) {
        return null;
    }
    const agentRunId = searchResult.agent_run_id;
    const citations = searchResult.citations || [];
    // const currentVote = voteState?.[dataId]?.[attributeText];

    return (
        <div
            className="group bg-indigo-bg rounded-md p-1 text-xs text-primary leading-snug mt-1 hover:border-indigo-border transition-colors cursor-pointer border border-transparent"
            onMouseEnter={() => dispatch(setHoveredAgentRunId(agentRunId))}
            onMouseLeave={() => dispatch(setHoveredAgentRunId(undefined))}
            onMouseDown={(e) => {
                e.stopPropagation();
                const firstCitation = citations.length > 0 ? citations[0] : null;

                if (e.metaKey || e.ctrlKey || e.button === 1 || !usePreview) {
                    // Open in new tab - use original navigation
                    navToAgentRun(
                        e,
                        router,
                        window,
                        agentRunId,
                        firstCitation?.transcript_idx ?? undefined,
                        firstCitation?.block_idx,
                        collectionId,
                        curSearchQuery
                    );
                } else if (e.button === 0 && usePreview) {
                    // Open in dashboard - use new mechanism
                    dispatch(
                        openAgentRunInDashboard({
                            agentRunId,
                            blockIdx: firstCitation?.block_idx,
                            transcriptIdx: firstCitation?.transcript_idx ?? undefined,
                        })
                    );
                }
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
                            collectionId,
                            dispatch
                        )}
                    </p>
                </div>
                {/* <div className="flex items-center gap-1 text-[10px] text-primary mt-1">
                    <span className="opacity-70">{curSearchQuery}</span>
                </div> */}
            </div>
        </div>
    );
};
