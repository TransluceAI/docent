import {
  AlertTriangle,
  ArrowLeftRight,
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  SmilePlus,
  X,
} from 'lucide-react';
import { useEffect, useState, useRef, useCallback } from 'react';

import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import { getActionsSummary } from '@/app/store/transcriptSlice';
import { Citation } from '@/app/types/experimentViewerTypes';
import {
  LowLevelAction,
  HighLevelAction,
  ActionsSummary,
  ObservationCategory,
  ObservationType,
} from '@/app/types/transcriptTypes';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { useCitationNavigation } from '@/app/dashboard/[collection_id]/rubric/[rubric_id]/NavigateToCitationContext';

interface AgentSummaryProps {
  agentRunId: string;
  initialActionIndex?: number;
}

const TYPE_STYLES: Record<
  ObservationCategory,
  { icon: JSX.Element; color: string; bgColor: string; label: string }
> = {
  mistake: {
    icon: <AlertTriangle className="w-3.5 h-3.5" />,
    color: 'text-red-text',
    bgColor: 'bg-red-text',
    label: 'Mistake',
  },
  critical_insight: {
    icon: <Check className="w-3.5 h-3.5" />,
    color: 'text-green-text',
    bgColor: 'bg-green-text',
    label: 'Critical Insight',
  },
  near_miss: {
    icon: <ArrowLeftRight className="w-3.5 h-3.5" />,
    color: 'text-blue-text',
    bgColor: 'bg-blue-text',
    label: 'Near Miss',
  },
  weird_behavior: {
    icon: <SmilePlus className="w-3.5 h-3.5" />,
    color: 'text-purple-text',
    bgColor: 'bg-purple-text',
    label: 'Interesting Behavior',
  },
  cheating: {
    icon: <X className="w-3.5 h-3.5" />,
    color: 'text-orange-text',
    bgColor: 'bg-orange-text',
    label: 'Cheating',
  },
};

// Agent Behavior Sequence Component
const BehaviorSequence: React.FC<{
  observations?: ObservationType[];
  actionsSummary?: ActionsSummary | null;
  onActionClick?: (actionIndex: number) => void;
}> = ({ observations = [], actionsSummary, onActionClick }) => {
  // If there are no observations, don't render anything
  if (!observations || observations.length === 0) {
    return null;
  }

  // Get the maximum action unit index to determine sequence length
  const maxActionUnitIdx =
    actionsSummary?.low_level?.reduce(
      (max, action) => Math.max(max, action.action_unit_idx),
      0
    ) || 0;

  // Organize moments by action unit index
  const momentsByActionUnit: Record<number, ObservationType[]> = {};

  if (observations && observations.length > 0) {
    observations.forEach((observation) => {
      if (!momentsByActionUnit[observation.action_unit_idx]) {
        momentsByActionUnit[observation.action_unit_idx] = [];
      }
      momentsByActionUnit[observation.action_unit_idx].push(observation);
    });
  }

  // Map text color classes to background color classes
  const getBackgroundColorClass = (category: ObservationCategory): string => {
    return TYPE_STYLES[category].bgColor;
  };

  return (
    <div className="bg-background text-primary p-2 rounded-md text-sm border border-border shadow-sm">
      <h3 className="text-sm font-medium mb-1">Notable moments</h3>

      {/* Legend */}
      <div className="flex flex-wrap gap-1 mb-2">
        {Object.entries(TYPE_STYLES).map(([category, style]) => (
          <div key={category} className="flex items-center mr-1 mb-1">
            <div
              className={`w-3 h-3 ${getBackgroundColorClass(category as ObservationCategory)} mr-1`}
            ></div>
            <span className="text-xs whitespace-nowrap">{style.label}</span>
          </div>
        ))}
        <div className="flex items-center mr-1 mb-1">
          <div className="w-3 h-3 bg-secondary border mr-1"></div>
          <span className="text-xs whitespace-nowrap">No observations</span>
        </div>
      </div>

      {/* Sequence visualization - make it responsive and full width */}
      <div className="w-full overflow-hidden">
        <div className="flex w-full bg-muted">
          {Array.from({ length: maxActionUnitIdx + 1 }).map((_, index) => {
            const moments = momentsByActionUnit[index] || [];
            const hasObservation = moments.length > 0;
            const color = hasObservation
              ? getBackgroundColorClass(moments[0].category)
              : 'bg-accent';

            return (
              <div
                key={index}
                className={cn(
                  `h-4 ${color} flex-1 min-w-[3px] cursor-pointer hover:opacity-70 hover:shadow-sm transition-all`,
                  index !== maxActionUnitIdx && 'border-r'
                )}
                title={
                  hasObservation
                    ? `Action Unit ${index}: ${TYPE_STYLES[moments[0].category].label} - ${moments[0].description}`
                    : `Action Unit ${index}`
                }
                onClick={() => onActionClick?.(index)}
              ></div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

// Modify the ActionItem component to receive actionRefs directly
const ActionItem = ({
  action,
  isHighLevel = false,
  lowLevelActions = [],
  observations = [],
  agentRunId,
  expandedActions,
  setExpandedActions,
  setActionRef,
}: {
  action: HighLevelAction | LowLevelAction;
  isHighLevel?: boolean;
  lowLevelActions?: LowLevelAction[];
  observations?: ObservationType[];
  agentRunId?: string;
  expandedActions?: Set<number>;
  setExpandedActions?: (callback: (prev: Set<number>) => Set<number>) => void;
  setActionRef?: (id: string, element: HTMLDivElement) => void;
}) => {
  const citationNav = useCitationNavigation();
  // Replace local expanded state with shared state from parent
  const highLevelAction = isHighLevel ? (action as HighLevelAction) : null;
  const actionId =
    isHighLevel && highLevelAction
      ? highLevelAction.step_idx
      : (action as LowLevelAction).action_unit_idx;
  const expanded = (isHighLevel && expandedActions?.has(actionId)) || false;

  // Create a unique ref ID that differentiates between high and low level actions
  const refId = isHighLevel ? `high-${actionId}` : `low-${actionId}`;

  // Function to handle card click - navigate to first citation if available
  const handleCardClick = (citations: Citation[]) => {
    if (isHighLevel && relatedLowLevelActions.length > 0) {
      // Toggle expansion for high-level actions that have sub-actions
      if (setExpandedActions && actionId !== undefined) {
        setExpandedActions((prev) => {
          const next = new Set(prev);
          if (next.has(actionId)) {
            next.delete(actionId);
          } else {
            next.add(actionId);
          }
          return next;
        });
      }
    }

    // Navigate to citation if available
    if (isHighLevel) {
      const highLevelAction = action as HighLevelAction;
      if (highLevelAction.first_block_idx !== null && agentRunId) {
        // Navigate to the first block of this high-level action
        citationNav?.navigateToCitation({
          citation: {
            start_idx: 0,
            end_idx: 0,
            transcript_idx: undefined,
            block_idx: highLevelAction.first_block_idx,
            metadata_key: undefined,
            start_pattern: undefined,
          },
          source: 'agent_summary',
        });
      }
    } else if (
      citations &&
      citations.length > 0 &&
      agentRunId &&
      citations[0].block_idx !== undefined
    ) {
      citationNav?.navigateToCitation({
        citation: citations[0],
        source: 'agent_summary',
      });
    }
  };

  // Function to render summary text with highlighted citations
  const renderSummaryWithCitations = (
    summary: string,
    citations: Citation[]
  ) => {
    if (!citations || citations.length === 0) {
      return summary;
    }

    // Sort citations by start_idx to process them in order
    const sortedCitations = [...citations].sort(
      (a, b) => a.start_idx - b.start_idx
    );

    // Create an array of text segments and citation spans
    const segments: JSX.Element[] = [];
    let lastIndex = 0;

    sortedCitations.forEach((citation, index) => {
      // Add text before the citation
      if (citation.start_idx > lastIndex) {
        segments.push(
          <span key={`text-${index}`}>
            {summary.substring(lastIndex, citation.start_idx)}
          </span>
        );
      }

      // Add the citation as a clickable span
      segments.push(
        <span
          key={`citation-${index}`}
          className="text-primary cursor-pointer hover:underline hover:bg-blue-muted font-medium transition-colors"
          onClick={(e) => {
            e.stopPropagation(); // Prevent the card click from triggering
            if (agentRunId && citation.block_idx !== undefined) {
              citationNav?.navigateToCitation({
                citation,
                source: 'agent_summary',
              });
            }
          }}
        >
          {summary.substring(citation.start_idx, citation.end_idx)}
        </span>
      );

      lastIndex = citation.end_idx;
    });

    // Add any remaining text after the last citation
    if (lastIndex < summary.length) {
      segments.push(<span key="text-end">{summary.substring(lastIndex)}</span>);
    }

    return segments;
  };

  // Get related low-level actions if this is a high-level action
  const relatedLowLevelActions = isHighLevel
    ? lowLevelActions.filter((la) =>
        (action as HighLevelAction).action_unit_indices.includes(
          la.action_unit_idx
        )
      )
    : [];

  // Find interesting moments for this action unit
  const findMomentsForAction = (
    action: HighLevelAction | LowLevelAction
  ): ObservationType[] => {
    if (isHighLevel) {
      // For high-level actions, collect moments from all related low-level actions
      return observations.filter((moment) =>
        (action as HighLevelAction).action_unit_indices.includes(
          moment.action_unit_idx
        )
      );
    } else {
      // For low-level actions, just get moments for this specific action unit
      return observations.filter(
        (moment) =>
          moment.action_unit_idx === (action as LowLevelAction).action_unit_idx
      );
    }
  };

  const actionMoments = findMomentsForAction(action);
  const hasMoments = actionMoments.length > 0;

  return (
    <div
      className="relative mb-2 last:mb-0"
      ref={(node) => {
        if (node && setActionRef) {
          setActionRef(refId, node);
        }
      }}
    >
      {/* Timeline dot for low-level actions only */}
      {/* {!isHighLevel && (
        <div
          className={`absolute top-[10px] w-3 h-3 rounded-full left-[-21.5px] ${
            hasMoments ? colors.bg : 'bg-muted-foreground'
          }`}
        />
      )} */}

      <div
        className={`bg-background px-3 py-2 ${
          (action.citations && action.citations.length > 0) || isHighLevel
            ? 'cursor-pointer hover:bg-secondary hover:shadow-sm transition-all duration-200'
            : ''
        } ${
          hasMoments
            ? `rounded-sm border-l-4 border-l-yellow-500/70 bg-yellow-50/30 dark:bg-yellow-950/20 shadow-sm transition-all duration-300`
            : ''
        }`}
        onClick={() => handleCardClick(action.citations)}
      >
        <div className="flex items-center space-x-2">
          {/* Expand indicator for high-level actions with children */}
          {isHighLevel && relatedLowLevelActions.length > 0 && (
            <div className="flex items-center">
              {expanded ? (
                <ChevronDown className="w-4 h-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="w-4 h-4 text-muted-foreground" />
              )}
            </div>
          )}

          <div className="font-medium text-sm">{action.title}</div>

          {isHighLevel && (
            <span className="text-xs text-muted-foreground">
              {(action as HighLevelAction).action_unit_indices.length} sub-steps
            </span>
          )}

          {/* Show badges for interesting moments if there are any */}
          {actionMoments.length > 0 && isHighLevel && (
            <span className="inline-flex gap-x-0.5">
              {actionMoments.slice(0, 3).map((moment, idx) => (
                <Tooltip key={idx}>
                  <TooltipTrigger asChild>
                    <span
                      className={`w-4 h-4 rounded-full ${TYPE_STYLES[moment.category].color} flex items-center justify-center cursor-help`}
                    >
                      {TYPE_STYLES[moment.category].icon}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent className="text-xs">
                    Contains {TYPE_STYLES[moment.category].label}
                  </TooltipContent>
                </Tooltip>
              ))}
              {actionMoments.length > 3 && (
                <span
                  className="w-4 h-4 rounded-full bg-accent text-muted-foreground flex items-center justify-center text-xs"
                  title="More interesting moments"
                >
                  +{actionMoments.length - 3}
                </span>
              )}
            </span>
          )}
        </div>

        <p
          className="text-muted-foreground mt-1"
          style={{ fontSize: '0.85rem', lineHeight: '1.1rem' }}
        >
          {renderSummaryWithCitations(action.summary, action.citations)}
        </p>

        {/* Show interesting moments if any */}
        {hasMoments && (!isHighLevel || (isHighLevel && !expanded)) && (
          <div className="mt-2 pt-2 border-t border-border">
            {actionMoments.map((moment, idx) => (
              <div key={idx} className="flex items-start mb-1 last:mb-0">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div
                      className={`flex-shrink-0 mr-1.5 ${TYPE_STYLES[moment.category].color} cursor-help`}
                    >
                      {TYPE_STYLES[moment.category].icon}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent className="text-xs">
                    {TYPE_STYLES[moment.category].label}
                  </TooltipContent>
                </Tooltip>
                <div className="text-xs text-muted-foreground">
                  {moment.description}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Nested low-level actions */}
      {isHighLevel && expanded && relatedLowLevelActions.length > 0 && (
        <div className="ml-8 mt-2 relative">
          {relatedLowLevelActions.map((lowLevelAction) => (
            <ActionItem
              key={lowLevelAction.action_unit_idx}
              action={lowLevelAction}
              isHighLevel={false}
              agentRunId={agentRunId}
              observations={observations}
              expandedActions={expandedActions}
              setExpandedActions={setExpandedActions}
              setActionRef={setActionRef}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// Extend the FC type to include our static method
interface AgentSummaryComponent extends React.FC<AgentSummaryProps> {
  scrollToAction: (
    ref: React.RefObject<{ scrollToAction: (actionIndex: number) => void }>,
    actionIndex: number
  ) => void;
}

const AgentSummary: React.FC<AgentSummaryProps> = ({
  initialActionIndex,
  agentRunId,
}) => {
  const dispatch = useAppDispatch();

  const actionsSummary = useAppSelector(
    (state) => state.transcript?.actionsSummary
  );
  const loadingActionsSummaryForTranscriptId = useAppSelector(
    (state) => state.transcript?.loadingActionsSummaryForTranscriptId
  );

  // Add state to track expanded high-level actions
  const [expandedActions, setExpandedActions] = useState<Set<number>>(
    new Set()
  );
  // Update ref type to use string keys to differentiate high/low level actions
  const actionRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // Helper function to set action refs
  const setActionRef = useCallback((id: string, element: HTMLDivElement) => {
    actionRefs.current.set(id, element);
  }, []);

  // Scroll to action function
  const scrollToAction = useCallback(
    (actionIndex: number) => {
      if (!actionsSummary) return;

      // First try to find and scroll to the low-level action directly
      const lowLevelRefId = `low-${actionIndex}`;
      const lowLevelElement = actionRefs.current.get(lowLevelRefId);

      // Find which high-level action contains our target action index
      const containingHighLevelAction = actionsSummary.high_level?.find(
        (highLevelAction) =>
          highLevelAction.action_unit_indices.includes(actionIndex)
      );

      if (containingHighLevelAction) {
        // Expand this high-level action first
        setExpandedActions((prev) => {
          const next = new Set(prev);
          next.add(containingHighLevelAction.step_idx);
          return next;
        });

        // Wait for DOM to update after expansion, then try to scroll
        setTimeout(() => {
          // Try to find the low-level element again after expansion
          const expandedLowLevelElement = actionRefs.current.get(lowLevelRefId);
          expandedLowLevelElement?.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
          });
        }, 200); // Timeout to allow DOM to update
      } else if (lowLevelElement) {
        // If no containing high-level action but element exists, just scroll to it
        lowLevelElement.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
      }
    },
    [actionsSummary]
  );

  // Request summary
  useEffect(() => {
    if (!agentRunId) {
      return;
    }

    // Request summary if we don't already have it loaded, and we're not loading it yet
    if (
      loadingActionsSummaryForTranscriptId !== agentRunId &&
      actionsSummary?.agent_run_id != agentRunId
    ) {
      dispatch(getActionsSummary(agentRunId));
    }
  }, [
    agentRunId,
    loadingActionsSummaryForTranscriptId,
    actionsSummary?.agent_run_id,
    dispatch,
  ]);

  // Scroll to initial action index when summary loads
  useEffect(() => {
    if (actionsSummary && initialActionIndex !== undefined) {
      scrollToAction(initialActionIndex);
    }
  }, [actionsSummary, initialActionIndex, scrollToAction]);

  // Loading indicator component for reuse
  const LoadingIndicator = () => (
    <div className="animate-pulse space-y-1">
      <div className="h-4 bg-accent rounded w-3/4"></div>
      <div className="h-4 bg-accent rounded w-2/3"></div>
      <div className="h-4 bg-accent rounded w-4/5"></div>
    </div>
  );

  // If we have no agentRun at all, don't show anything
  if (!agentRunId) {
    return null;
  }

  // Find low-level actions that aren't associated with any high-level action
  const getOrphanedLowLevelActions = () => {
    if (!actionsSummary?.low_level || !actionsSummary?.high_level) {
      return actionsSummary?.low_level || [];
    }

    // Collect all action_unit_idx values that are included in high-level actions
    const includedActionUnitIds = new Set<number>();
    actionsSummary.high_level.forEach((highLevelAction) => {
      highLevelAction.action_unit_indices.forEach((idx) => {
        includedActionUnitIds.add(idx);
      });
    });

    // Return low-level actions that aren't included in any high-level action
    return actionsSummary.low_level.filter(
      (lowLevelAction) =>
        !includedActionUnitIds.has(lowLevelAction.action_unit_idx)
    );
  };

  const orphanedLowLevelActions = getOrphanedLowLevelActions();
  const hasHighLevelActions =
    actionsSummary?.high_level && actionsSummary.high_level.length > 0;
  const hasOrphanedLowLevelActions = orphanedLowLevelActions.length > 0;

  return (
    <TooltipProvider>
      <ScrollArea className="h-full" ref={scrollAreaRef}>
        <div className="space-y-2">
          <div className="flex flex-col">
            <h4 className="text-sm flex items-center font-semibold">
              Actions Taken by the Agent
              {loadingActionsSummaryForTranscriptId === agentRunId && (
                <Loader2 className="ml-2 h-4 w-4 animate-spin text-muted-foreground" />
              )}
            </h4>
            <span className="text-xs text-muted-foreground">
              Click on an action to see an analysis of notable moments. Expand
              blocks to see a breakdown.
            </span>
          </div>
          {/* Add Behavior Sequence component with observations */}
          {actionsSummary &&
            actionsSummary.observations &&
            actionsSummary.observations.length > 0 && (
              <BehaviorSequence
                observations={actionsSummary.observations}
                actionsSummary={actionsSummary}
                onActionClick={scrollToAction}
              />
            )}
          {actionsSummary ? (
            <div className="relative pb-2">
              {/* Hierarchical view of high-level actions */}
              {hasHighLevelActions &&
                actionsSummary.high_level.map((highLevelAction) => (
                  <ActionItem
                    key={highLevelAction.step_idx}
                    action={highLevelAction}
                    isHighLevel={true}
                    lowLevelActions={actionsSummary.low_level}
                    agentRunId={agentRunId}
                    observations={actionsSummary.observations}
                    expandedActions={expandedActions}
                    setExpandedActions={setExpandedActions}
                    setActionRef={setActionRef}
                  />
                ))}

              {/* Show orphaned low-level actions */}
              {hasOrphanedLowLevelActions && (
                <>
                  {hasHighLevelActions && (
                    <div className="my-3 border-t border-border pt-3">
                      <h5 className="text-sm font-medium text-muted-foreground mb-2">
                        Additional Low-Level Actions
                      </h5>
                    </div>
                  )}

                  {orphanedLowLevelActions.map((lowLevelAction) => (
                    <ActionItem
                      key={lowLevelAction.action_unit_idx}
                      action={lowLevelAction}
                      isHighLevel={false}
                      agentRunId={agentRunId}
                      observations={actionsSummary.observations}
                      expandedActions={expandedActions}
                      setExpandedActions={setExpandedActions}
                      setActionRef={setActionRef}
                    />
                  ))}
                </>
              )}

              {/* Show all low-level actions if there are no high-level actions */}
              {!hasHighLevelActions &&
                !hasOrphanedLowLevelActions &&
                actionsSummary.low_level.length > 0 && (
                  <>
                    {actionsSummary.low_level.map((lowLevelAction) => (
                      <ActionItem
                        key={lowLevelAction.action_unit_idx}
                        action={lowLevelAction}
                        isHighLevel={false}
                        agentRunId={agentRunId}
                        observations={actionsSummary.observations}
                        expandedActions={expandedActions}
                        setExpandedActions={setExpandedActions}
                        setActionRef={setActionRef}
                      />
                    ))}
                  </>
                )}

              {/* Show message if no actions are available */}
              {!hasHighLevelActions &&
                !loadingActionsSummaryForTranscriptId &&
                actionsSummary.low_level.length === 0 && (
                  <div className="bg-background rounded-sm p-2 shadow-sm border border-border text-muted-foreground text-sm">
                    No actions available for this agent run.
                  </div>
                )}
            </div>
          ) : (
            <LoadingIndicator />
          )}
        </div>
      </ScrollArea>
    </TooltipProvider>
  );
};

// Add a method to the component for external access to scrollToAction
(AgentSummary as AgentSummaryComponent).scrollToAction = (
  ref: React.RefObject<{ scrollToAction: (actionIndex: number) => void }>,
  actionIndex: number
) => {
  ref.current?.scrollToAction(actionIndex);
};

export default AgentSummary as AgentSummaryComponent;
