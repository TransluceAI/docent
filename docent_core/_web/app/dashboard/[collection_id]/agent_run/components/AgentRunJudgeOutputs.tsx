'use client';

import { ChevronDown, ChevronRight, Loader2, Pin, PinOff } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useGetAgentRunJudgeOutputsQuery } from '@/app/api/rubricApi';
import FailedResultCard from '../../components/FailedResultCard';
import { SchemaValueRenderer } from '../../components/SchemaValueRenderer';

interface AgentRunJudgeOutputsProps {
  collectionId: string;
  agentRunId: string;
}

const emptyLabelValues: Record<string, unknown> = {};

const noopSaveLabel = (_key: string, _value: unknown) => undefined;
const noopClearLabel = (_key: string) => undefined;
const noopRenderLabelSetMenu = (_onLabelSetCreated: (id: string) => void) =>
  null;

interface JudgeOutputsUiPrefs {
  pinnedRubricIds: string[];
  collapsedRubricKeys: string[];
}

const makeRubricCardKey = (rubricId: string, rubricVersion: number | string) =>
  `${rubricId}:${rubricVersion}`;

const getUiPrefsStorageKey = (collectionId: string) =>
  `docent-agent-run-judge-outputs-ui:${collectionId}`;

const readPrefsFromLocalStorage = (
  collectionId: string
): JudgeOutputsUiPrefs => {
  if (typeof window === 'undefined') {
    return { pinnedRubricIds: [], collapsedRubricKeys: [] };
  }

  const rawValue = window.localStorage.getItem(
    getUiPrefsStorageKey(collectionId)
  );
  if (!rawValue) {
    return { pinnedRubricIds: [], collapsedRubricKeys: [] };
  }

  try {
    const parsed = JSON.parse(rawValue) as Partial<JudgeOutputsUiPrefs>;
    const pinnedRubricIds = Array.isArray(parsed.pinnedRubricIds)
      ? parsed.pinnedRubricIds.filter(
          (rubricId): rubricId is string => typeof rubricId === 'string'
        )
      : [];
    const collapsedRubricKeys = Array.isArray(parsed.collapsedRubricKeys)
      ? parsed.collapsedRubricKeys.filter(
          (rubricKey): rubricKey is string => typeof rubricKey === 'string'
        )
      : [];

    return { pinnedRubricIds, collapsedRubricKeys };
  } catch {
    return { pinnedRubricIds: [], collapsedRubricKeys: [] };
  }
};

const writePrefsToLocalStorage = (
  collectionId: string,
  prefs: JudgeOutputsUiPrefs
) => {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    window.localStorage.setItem(
      getUiPrefsStorageKey(collectionId),
      JSON.stringify(prefs)
    );
  } catch {
    // Ignore localStorage write failures.
  }
};

const getRubricTitle = (rubricText: string) => {
  const firstNonEmptyLine = rubricText
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  return firstNonEmptyLine ?? 'Untitled rubric';
};

export default function AgentRunJudgeOutputs({
  collectionId,
  agentRunId,
}: AgentRunJudgeOutputsProps) {
  const [collapsedRubricKeys, setCollapsedRubricKeys] = useState<Set<string>>(
    () => new Set()
  );
  const [pinnedRubricIds, setPinnedRubricIds] = useState<Set<string>>(
    () => new Set()
  );
  const [hydratedCollectionId, setHydratedCollectionId] = useState<
    string | null
  >(null);

  const {
    data: judgeOutputs,
    isLoading,
    isError,
  } = useGetAgentRunJudgeOutputsQuery({ collectionId, agentRunId });

  useEffect(() => {
    const prefs = readPrefsFromLocalStorage(collectionId);
    setCollapsedRubricKeys(new Set(prefs.collapsedRubricKeys));
    setPinnedRubricIds(new Set(prefs.pinnedRubricIds));
    setHydratedCollectionId(collectionId);
  }, [collectionId]);

  useEffect(() => {
    if (hydratedCollectionId !== collectionId) {
      return;
    }

    writePrefsToLocalStorage(collectionId, {
      pinnedRubricIds: [...pinnedRubricIds],
      collapsedRubricKeys: [...collapsedRubricKeys],
    });
  }, [
    collectionId,
    collapsedRubricKeys,
    hydratedCollectionId,
    pinnedRubricIds,
  ]);

  const orderedJudgeOutputs = useMemo(() => {
    if (!judgeOutputs) {
      return [];
    }

    const pinned = judgeOutputs.filter((rubricOutputs) =>
      pinnedRubricIds.has(rubricOutputs.rubric_id)
    );
    const unpinned = judgeOutputs.filter(
      (rubricOutputs) => !pinnedRubricIds.has(rubricOutputs.rubric_id)
    );

    return [...pinned, ...unpinned];
  }, [judgeOutputs, pinnedRubricIds]);

  const toggleRubricCollapsed = (
    rubricId: string,
    rubricVersion: number | string
  ) => {
    const rubricKey = makeRubricCardKey(rubricId, rubricVersion);

    setCollapsedRubricKeys((prev) => {
      const next = new Set(prev);
      if (next.has(rubricKey)) {
        next.delete(rubricKey);
      } else {
        next.add(rubricKey);
      }
      return next;
    });
  };

  const toggleRubricPinned = (rubricId: string) => {
    setPinnedRubricIds((prev) => {
      const next = new Set(prev);
      if (next.has(rubricId)) {
        next.delete(rubricId);
      } else {
        next.add(rubricId);
      }
      return next;
    });
  };

  if (isLoading) {
    return (
      <div className="flex justify-center">
        <Loader2 size={16} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex justify-center text-xs text-red-text">
        Failed to load judge outputs for this agent run.
      </div>
    );
  }

  if (!judgeOutputs || judgeOutputs.length === 0) {
    return (
      <div className="flex justify-center text-xs text-muted-foreground">
        No judge outputs found for this agent run.
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto custom-scrollbar space-y-3">
      {orderedJudgeOutputs.map((rubricOutputs) => {
        const rubricCardKey = makeRubricCardKey(
          rubricOutputs.rubric_id,
          rubricOutputs.rubric_version
        );
        const isCollapsed = collapsedRubricKeys.has(rubricCardKey);
        const isPinned = pinnedRubricIds.has(rubricOutputs.rubric_id);

        return (
          <div
            key={rubricCardKey}
            className="border border-border rounded-md p-3 space-y-3"
          >
            <div className="flex items-start justify-between gap-3">
              <button
                type="button"
                className="min-w-0 flex-1 space-y-1 text-left"
                onClick={() =>
                  toggleRubricCollapsed(
                    rubricOutputs.rubric_id,
                    rubricOutputs.rubric_version
                  )
                }
              >
                <div className="flex items-center gap-1.5">
                  {isCollapsed ? (
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  )}
                  <div className="text-xs font-semibold text-primary truncate">
                    {getRubricTitle(rubricOutputs.rubric_text)}
                  </div>
                  {isPinned && (
                    <span className="rounded-sm bg-blue-bg px-1.5 py-0.5 text-[10px] font-medium text-blue-text">
                      Pinned
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Rubric {rubricOutputs.rubric_id.slice(0, 8)} v
                  {rubricOutputs.rubric_version} •{' '}
                  {rubricOutputs.results.length} output
                  {rubricOutputs.results.length === 1 ? '' : 's'}
                </div>
              </button>
              <button
                type="button"
                className={
                  isPinned
                    ? 'rounded-sm border border-blue-border bg-blue-bg p-1 text-blue-text hover:bg-blue-muted'
                    : 'rounded-sm border border-border p-1 text-muted-foreground hover:bg-secondary hover:text-primary'
                }
                onClick={(event) => {
                  event.stopPropagation();
                  toggleRubricPinned(rubricOutputs.rubric_id);
                }}
                aria-label={
                  isPinned ? 'Unpin rubric group' : 'Pin rubric group'
                }
              >
                {isPinned ? (
                  <PinOff className="h-3.5 w-3.5" />
                ) : (
                  <Pin className="h-3.5 w-3.5" />
                )}
              </button>
            </div>

            {!isCollapsed && (
              <div className="space-y-2">
                {rubricOutputs.results.map((result, idx) => (
                  <div
                    key={result.id}
                    className="border border-border rounded-sm p-2 space-y-2 bg-background"
                  >
                    {rubricOutputs.results.length > 1 && (
                      <div className="text-[11px] text-muted-foreground">
                        Rollout {idx + 1}
                      </div>
                    )}

                    {result.result_type === 'FAILURE' ? (
                      <FailedResultCard result={result} />
                    ) : (
                      <SchemaValueRenderer
                        schema={rubricOutputs.output_schema}
                        values={result.output}
                        labelValues={emptyLabelValues}
                        activeLabelSet={null}
                        onSaveLabel={noopSaveLabel}
                        onClearLabel={noopClearLabel}
                        showLabels={false}
                        canEditLabels={false}
                        renderLabelSetMenu={noopRenderLabelSetMenu}
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
