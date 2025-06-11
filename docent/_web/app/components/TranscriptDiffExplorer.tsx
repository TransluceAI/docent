import {
  useAppDispatch,
  useAppSelector,
  createAppSelector,
} from '../store/hooks';
import {
  interpolateAgentBadges,
  TranscriptDiffSummary,
} from './TranscriptDiffSummary';
import { cn } from '@/lib/utils';
import { useEffect, useMemo } from 'react';
import { getAgentRunMetadata } from '../store/frameSlice';
import DiffsClusters from './DiffsClusters';

const selectDiffs = createAppSelector(
  [
    (state) => state.diff.transcriptDiffsByKey,
    (state) => state.diff.diffsReport,
  ],
  (diffsMap, diffsReport) => {
    if (!diffsReport) {
      return [];
    }
    return Object.values(diffsMap).filter(
      (diff) => diff.diffs_report_id === diffsReport.id
    );
  }
);

export const TranscriptDiffExplorer = () => {
  const dispatch = useAppDispatch();
  const diffsReport = useAppSelector((state) => state.diff.diffsReport);

  const diffs = useAppSelector(selectDiffs);
  const frame = useAppSelector((state) => state.frame);

  const selectedCluster = useAppSelector((state) => state.diff.selectedCluster);
  const filteredClaimIds = useAppSelector(
    (state) => state.diff.filteredClaimIds
  );

  // Calculate total and filtered counts
  const counts = useMemo(() => {
    const totalDiffs = diffs.length;
    const totalClaims = diffs.reduce(
      (sum, diff) => sum + diff.claims.length,
      0
    );

    let filteredDiffs = totalDiffs;
    let filteredClaims = totalClaims;

    if (filteredClaimIds) {
      filteredDiffs = diffs.filter((diff) =>
        diff.claims.some((claim) => filteredClaimIds.includes(claim.id))
      ).length;
      filteredClaims = diffs.reduce(
        (sum, diff) =>
          sum +
          diff.claims.filter((claim) => filteredClaimIds.includes(claim.id))
            .length,
        0
      );
    }

    return {
      totalDiffs,
      totalClaims,
      filteredDiffs,
      filteredClaims,
    };
  }, [diffs, filteredClaimIds]);

  // Only show the diffs UI if both experiment IDs are set and there are diffs
  const showDiffs = Object.keys(diffs).length > 0;

  const allAgentRunIds = useMemo(() => {
    const agentRunIds = new Set<string>();
    diffs.forEach((diff) => {
      agentRunIds.add(diff.agent_run_1_id);
      agentRunIds.add(diff.agent_run_2_id);
    });
    return Array.from(agentRunIds);
  }, [diffs]);

  useEffect(() => {
    if (!frame.frameGridId) {
      console.log('No frame grid ID available');
      return;
    }
    dispatch(getAgentRunMetadata(allAgentRunIds));
  }, [allAgentRunIds, frame.frameGridId, dispatch]);
  if (!diffsReport) return null;

  return (
    <>
      <div className="$Header">
        <h2
          className={cn(
            'text-xs font-semibold uppercase tracking-wide',
            'text-gray-500 dark:text-gray-400'
          )}
        >
          Transcript Diffs Report
        </h2>
        <h1
          className={cn(
            'text-2xl font-bold mb-4',
            'text-gray-900 dark:text-gray-100'
          )}
        >
          {diffsReport.name}
        </h1>
      </div>
      <div className="flex w-full min-h-screen bg-gray-50 dark:bg-gray-900/60">
        <div className="$SidePanel sticky top-0 self-start h-[100vh]">
          <DiffsClusters />
        </div>
        {/* Main content panel */}
        <div className="$MainContent flex-1 space-y-4 p-4 max-w-4xl">
          <div
            className={cn(
              '$FilterBubble sticky top-0 z-20',
              'p-4',
              'bg-gray-100 dark:bg-gray-800/60',
              'border border-gray-200 dark:border-gray-700',
              'text-gray-900 dark:text-gray-100',
              'space-y-3'
            )}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600 dark:text-gray-300">
                  {selectedCluster ? (
                    <>
                      Showing{' '}
                      <span className="font-semibold">
                        {counts.filteredClaims} differences
                      </span>{' '}
                      across{' '}
                      <span className="font-semibold">
                        {counts.filteredDiffs} tasks{' '}
                      </span>{' '}
                      related to theme{' '}
                      <span className="font-semibold text-blue-800 dark:text-blue-200">
                        {selectedCluster.name}
                      </span>
                    </>
                  ) : (
                    <>
                      Showing{' '}
                      <span className="font-semibold">
                        {counts.totalClaims} differences
                      </span>{' '}
                      across{' '}
                      <span className="font-semibold">
                        {counts.totalDiffs} tasks
                      </span>
                      .
                    </>
                  )}
                </p>
              </div>
            </div>

            {selectedCluster && (
              <div
                className={cn(
                  'bg-blue-50 dark:bg-blue-900/30',
                  'border border-blue-200 dark:border-blue-800',
                  'text-blue-900 dark:text-blue-100',
                  'p-2 rounded-sm'
                )}
              >
                <p className="text-sm mb-1">
                  Theme Details: {selectedCluster.name}
                </p>
                <p className="text-xxs text-blue-800 dark:text-blue-200">
                  {selectedCluster.description}
                </p>
              </div>
            )}
            <div className="text-xs text-gray-500 dark:text-gray-400">
              {' '}
              Comparing {interpolateAgentBadges('Agent 1')} and{' '}
              {interpolateAgentBadges('Agent 2')}.
            </div>
          </div>

          {showDiffs ? (
            <div className="$DiffsList">
              {/* Summary counts */}
              <div className="flex flex-col space-y-4 overflow-y-scroll">
                {diffs.map((diff) => (

                    <TranscriptDiffSummary
                      key={diff.id}
                      diffKey={`${diff.agent_run_1_id}___${diff.agent_run_2_id}`}
                    />

                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
};
