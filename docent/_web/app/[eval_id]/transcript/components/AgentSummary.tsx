import { useEffect, useMemo, useState, useRef, useCallback } from 'react';
import {
  Datapoint,
  LowLevelAction,
  HighLevelAction,
  ActionsSummary,
  ObservationCategory,
  ObservationType,
} from '@/app/types/transcriptTypes';
import { Citation } from '@/app/types/experimentViewerTypes';
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useAppDispatch, useAppSelector } from '@/app/store/hooks';
import {
  clearActionsSummary,
  getActionsSummary,
} from '@/app/store/transcriptSlice';

interface AgentSummaryProps {
  onCitationClick?: (datapointId: string, blockId?: number) => void;
  initialActionIndex?: number;
}

const TYPE_STYLES: Record<
  ObservationCategory,
  { icon: JSX.Element; color: string; bgColor: string; label: string }
> = {
  mistake: {
    icon: <AlertTriangle className="w-3.5 h-3.5" />,
    color: 'text-red-600',
    bgColor: 'bg-red-600',
    label: 'Mistake',
  },
  critical_insight: {
    icon: <Check className="w-3.5 h-3.5" />,
    color: 'text-green-600',
    bgColor: 'bg-green-600',
    label: 'Critical Insight',
  },
  near_miss: {
    icon: <ArrowLeftRight className="w-3.5 h-3.5" />,
    color: 'text-amber-600',
    bgColor: 'bg-amber-600',
    label: 'Near Miss',
  },
  weird_behavior: {
    icon: <SmilePlus className="w-3.5 h-3.5" />,
    color: 'text-purple-600',
    bgColor: 'bg-purple-600',
    label: 'Interesting Behavior',
  },
  cheating: {
    icon: <X className="w-3.5 h-3.5" />,
    color: 'text-orange-600',
    bgColor: 'bg-orange-600',
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
    <div className="bg-white text-gray-800 p-2 rounded-md text-sm border border-gray-200 shadow-sm">
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
          <div className="w-3 h-3 bg-gray-200 mr-1"></div>
          <span className="text-xs whitespace-nowrap">No observations</span>
        </div>
      </div>

      {/* Sequence visualization - make it responsive and full width */}
      <div className="w-full overflow-hidden mb-2">
        <div className="flex w-full bg-gray-100">
          {Array.from({ length: maxActionUnitIdx + 1 }).map((_, index) => {
            const moments = momentsByActionUnit[index] || [];
            const hasObservation = moments.length > 0;
            const color = hasObservation
              ? getBackgroundColorClass(moments[0].category)
              : 'bg-gray-200';

            return (
              <div
                key={index}
                className={`h-4 ${color} border-r border-white flex-1 min-w-[3px] cursor-pointer hover:opacity-90 hover:scale-[1.02] hover:shadow-sm transition-all`}
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
  onCitationClick,
  datapoint,
  expandedActions,
  setExpandedActions,
  setActionRef,
}: {
  action: HighLevelAction | LowLevelAction;
  isHighLevel?: boolean;
  lowLevelActions?: LowLevelAction[];
  observations?: ObservationType[];
  onCitationClick?: (datapointId: string, blockId?: number) => void;
  datapoint?: Datapoint | null;
  expandedActions?: Set<number>;
  setExpandedActions?: (callback: (prev: Set<number>) => Set<number>) => void;
  setActionRef?: (id: string, element: HTMLDivElement) => void;
}) => {
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
    if (isHighLevel) {
      // Toggle expansion for high-level actions
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

      // If high-level action has first_block_idx, navigate to it
      const highLevelAction = action as HighLevelAction;
      if (
        highLevelAction.first_block_idx !== null &&
        onCitationClick &&
        datapoint?.id
      ) {
        onCitationClick(datapoint.id, highLevelAction.first_block_idx);
      }
    } else if (
      citations &&
      citations.length > 0 &&
      onCitationClick &&
      datapoint?.id &&
      citations[0].block_idx !== undefined
    ) {
      onCitationClick(datapoint.id, citations[0].block_idx);
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
          className="text-blue-600 cursor-pointer hover:underline hover:bg-blue-50 font-medium transition-colors"
          onClick={(e) => {
            e.stopPropagation(); // Prevent the card click from triggering
            if (
              onCitationClick &&
              datapoint?.id &&
              citation.block_idx !== undefined
            ) {
              onCitationClick(datapoint.id, citation.block_idx);
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
      {/* Timeline dot - colorful if it has an interesting moment */}
      <div className="absolute left-[-22px] top-[10px] w-4 h-4 rounded-full flex items-center justify-center bg-white border-2 border-primary">
        <div className="w-1.5 h-1.5 bg-primary rounded-full" />
      </div>

      {/* Expand/collapse button for high-level actions */}
      {isHighLevel && relatedLowLevelActions.length > 0 && (
        <button
          className="absolute left-[-42.5px] top-[8px] w-5 h-5 flex items-center justify-center text-gray-500 hover:text-gray-700"
          onClick={(e) => {
            e.stopPropagation();
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
          }}
          aria-label={expanded ? 'Collapse' : 'Expand'}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
      )}

      <div
        className={`bg-white p-2  ${
          (action.citations && action.citations.length > 0) || isHighLevel
            ? 'cursor-pointer hover:bg-gray-50 hover:shadow-sm hover:scale-[1.005] transition-all duration-200'
            : ''
        } ${
          hasMoments
            ? 'rounded-sm border shadow-sm border-orange-200 shadow-[0_0_5px_rgba(251,146,60,0.15)] transition-all duration-300'
            : ''
        }`}
        onClick={() => handleCardClick(action.citations)}
      >
        <div className="flex items-center space-x-2">
          {/* Show badges for interesting moments if there are any */}
          {actionMoments.length > 0 && isHighLevel && (
            <span className="inline-flex">
              {actionMoments.slice(0, 3).map((moment, idx) => (
                <Tooltip key={idx}>
                  <TooltipTrigger asChild>
                    <span
                      className={`w-4 h-4 rounded-full ${TYPE_STYLES[moment.category].color} flex items-center justify-center border border-white cursor-help`}
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
                  className="w-4 h-4 rounded-full bg-gray-200 text-gray-600 flex items-center justify-center text-xs border border-white"
                  title="More interesting moments"
                >
                  +{actionMoments.length - 3}
                </span>
              )}
            </span>
          )}
          <div className="font-medium text-sm">
            {action.title}
            {isHighLevel && (
              <span className="text-xs text-gray-500 ml-2">
                {' ' + (action as HighLevelAction).action_unit_indices.length}{' '}
                sub-steps
              </span>
            )}
          </div>
        </div>
        <p
          className="text-gray-600 mt-1"
          style={{ fontSize: '0.85rem', lineHeight: '1.1rem' }}
        >
          {renderSummaryWithCitations(action.summary, action.citations)}
        </p>

        {/* Show interesting moments if any */}
        {hasMoments && (!isHighLevel || (isHighLevel && !expanded)) && (
          <div className="mt-2 pt-2 border-t border-gray-100">
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
                <div className="text-xs text-gray-600">
                  {moment.description}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Nested low-level actions */}
      {isHighLevel && expanded && relatedLowLevelActions.length > 0 && (
        <div className="ml-4 mt-2 pl-[24px] relative">
          {/* Vertical timeline line for nested items */}
          <div className="absolute left-[8px] top-2 bottom-2 w-[2px] bg-gray-200"></div>

          {relatedLowLevelActions.map((lowLevelAction) => (
            <ActionItem
              key={lowLevelAction.action_unit_idx}
              action={lowLevelAction}
              isHighLevel={false}
              onCitationClick={onCitationClick}
              datapoint={datapoint}
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
  onCitationClick,
  initialActionIndex,
}) => {
  const dispatch = useAppDispatch();

  const datapoint = useAppSelector((state) => state.transcript.curDatapoint);
  const actionsSummary = useAppSelector(
    (state) => state.transcript.actionsSummary
  );
  const loadingActionsSummaryForTranscriptId = useAppSelector(
    (state) => state.transcript.loadingActionsSummaryForTranscriptId
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
    if (!datapoint) {
      return;
    }

    // If the datapoint is still loading, clear the summaries; there should be no summaries for those
    if (datapoint.obj.metadata.is_loading_messages) {
      dispatch(clearActionsSummary());
    }
    // Request summary if we don't already have it loaded, and we're not loading it yet
    if (
      loadingActionsSummaryForTranscriptId !== datapoint.id &&
      actionsSummary?.datapoint_id != datapoint.id
    ) {
      dispatch(getActionsSummary(datapoint.id));
    }
  }, [
    datapoint,
    loadingActionsSummaryForTranscriptId,
    actionsSummary?.datapoint_id,
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
      <div className="h-4 bg-gray-200 rounded w-3/4"></div>
      <div className="h-4 bg-gray-200 rounded w-2/3"></div>
      <div className="h-4 bg-gray-200 rounded w-4/5"></div>
    </div>
  );

  // If we have no datapoint at all, don't show anything
  if (!datapoint) {
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
          <h4 className="text-sm font-semibold mb-2 flex items-center">
            Actions Taken by the Agent
            {loadingActionsSummaryForTranscriptId === datapoint?.id && (
              <Loader2 className="ml-2 h-4 w-4 animate-spin text-gray-500" />
            )}
          </h4>
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
            <div className="relative pl-[46px]">
              {/* Vertical timeline line */}
              <div className="absolute left-[31px] top-2 bottom-2 w-[2px] bg-gray-200"></div>

              {/* Hierarchical view of high-level actions */}
              {hasHighLevelActions &&
                actionsSummary.high_level.map((highLevelAction) => (
                  <ActionItem
                    key={highLevelAction.step_idx}
                    action={highLevelAction}
                    isHighLevel={true}
                    lowLevelActions={actionsSummary.low_level}
                    onCitationClick={onCitationClick}
                    datapoint={datapoint}
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
                    <div className="my-3 border-t border-gray-200 pt-3">
                      <h5 className="text-sm font-medium text-gray-600 mb-2">
                        Additional Low-Level Actions
                      </h5>
                    </div>
                  )}

                  {orphanedLowLevelActions.map((lowLevelAction) => (
                    <ActionItem
                      key={lowLevelAction.action_unit_idx}
                      action={lowLevelAction}
                      isHighLevel={false}
                      onCitationClick={onCitationClick}
                      datapoint={datapoint}
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
                        onCitationClick={onCitationClick}
                        datapoint={datapoint}
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
                  <div className="bg-white rounded-sm p-2 shadow-sm border border-gray-100 text-gray-600 text-sm">
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
