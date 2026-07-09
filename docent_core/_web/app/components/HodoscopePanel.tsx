'use client';

import {
  Download,
  Loader2,
  Play,
  Radar,
  Square,
  TriangleAlert,
} from 'lucide-react';
import { skipToken } from '@reduxjs/toolkit/query';
import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { navToAgentRun } from '@/lib/nav';

import {
  HodoscopeProjection,
  HodoscopeProjectionMethod,
  HodoscopeProjectionPoint,
  useCancelHodoscopeAnalysisMutation,
  useGetHodoscopeProjectionQuery,
  useLazyGetHodoscopeArtifactQuery,
  useListHodoscopeAnalysesQuery,
  useStartHodoscopeAnalysisMutation,
} from '../api/hodoscopeApi';
import { useGetAgentRunMetadataFieldsQuery } from '../api/collectionApi';
import { useAppSelector } from '../store/hooks';

const DEFAULT_LIMIT = 500;
const DEFAULT_SEED = 42;
const AUTO_GROUP = '__auto__';

const GROUP_COLORS = [
  'hsl(var(--blue-text))',
  'hsl(var(--green-text))',
  'hsl(var(--orange-text))',
  'hsl(var(--purple-text))',
  'hsl(var(--cyan-text))',
  'hsl(var(--red-text))',
  'hsl(var(--indigo-text))',
];

const statusLabel: Record<string, string> = {
  pending: 'Pending',
  running: 'Running',
  complete: 'Complete',
  error: 'Error',
  canceled: 'Canceled',
};

function normalizePoints(points: HodoscopeProjectionPoint[]) {
  if (points.length === 0) {
    return new Map<string, { x: number; y: number }>();
  }

  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;

  return new Map(
    points.map((point) => [
      point.id,
      {
        x: 8 + ((point.x - minX) / spanX) * 84,
        y: 92 - ((point.y - minY) / spanY) * 84,
      },
    ])
  );
}

function getGroupColor(group: string, groups: string[]) {
  const idx = Math.max(0, groups.indexOf(group));
  return GROUP_COLORS[idx % GROUP_COLORS.length];
}

function projectionStateText(projection?: HodoscopeProjection) {
  if (!projection) {
    return 'No map data yet';
  }

  return `${projection.points.length} actions across ${projection.groups.length} groups`;
}

export function HodoscopePanel({
  hasWritePermission,
}: {
  hasWritePermission: boolean;
}) {
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const router = useRouter();

  const [groupBy, setGroupBy] = useState(AUTO_GROUP);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [projectionMethod, setProjectionMethod] =
    useState<HodoscopeProjectionMethod>('tsne');
  const [selectedPointId, setSelectedPointId] = useState<string | null>(null);

  const { data: metadataFieldsData } = useGetAgentRunMetadataFieldsQuery(
    collectionId!,
    { skip: !collectionId }
  );

  const {
    data: analyses = [],
    isFetching: isFetchingAnalyses,
    refetch: refetchAnalyses,
  } = useListHodoscopeAnalysesQuery(
    collectionId ? { collectionId } : skipToken,
    {
      pollingInterval: 0,
    }
  );

  const latestAnalysis = analyses[0];
  const isActive =
    latestAnalysis?.status === 'pending' ||
    latestAnalysis?.status === 'running';

  const { data: pollingAnalyses = [] } = useListHodoscopeAnalysesQuery(
    collectionId && isActive ? { collectionId } : skipToken,
    {
      pollingInterval: 2000,
    }
  );

  const currentAnalysis = pollingAnalyses[0] ?? latestAnalysis;
  const canLoadProjection = Boolean(
    collectionId && currentAnalysis?.id && currentAnalysis.status === 'complete'
  );

  const { data: projection, isFetching: isFetchingProjection } =
    useGetHodoscopeProjectionQuery(
      canLoadProjection && collectionId && currentAnalysis
        ? { collectionId, analysisId: currentAnalysis.id }
        : skipToken
    );

  const [startAnalysis, startState] = useStartHodoscopeAnalysisMutation();
  const [cancelAnalysis, cancelState] = useCancelHodoscopeAnalysisMutation();
  const [getArtifact, artifactState] = useLazyGetHodoscopeArtifactQuery();

  const fieldOptions = useMemo(() => {
    const names = metadataFieldsData?.fields?.map((field) => field.name) ?? [];
    const preferred = [
      'metadata.model_name_or_path',
      'metadata.model',
      'model_name_or_path',
      'model',
    ];

    return Array.from(new Set([...preferred, ...names])).sort((a, b) => {
      const aIdx = preferred.indexOf(a);
      const bIdx = preferred.indexOf(b);
      if (aIdx !== -1 || bIdx !== -1) {
        return (aIdx === -1 ? 99 : aIdx) - (bIdx === -1 ? 99 : bIdx);
      }
      return a.localeCompare(b);
    });
  }, [metadataFieldsData]);

  const groupNames = useMemo(
    () => projection?.groups.map((group) => group.name) ?? [],
    [projection]
  );

  const normalizedPoints = useMemo(
    () => normalizePoints(projection?.points ?? []),
    [projection]
  );

  const selectedPoint = useMemo(() => {
    if (!projection?.points.length) {
      return null;
    }
    return (
      projection.points.find((point) => point.id === selectedPointId) ??
      projection.points[0]
    );
  }, [projection, selectedPointId]);

  const representatives = useMemo(
    () =>
      [...(projection?.points ?? [])]
        .sort((a, b) => a.fps_rank - b.fps_rank)
        .slice(0, 6),
    [projection]
  );

  const handleRun = async () => {
    if (!collectionId) {
      return;
    }

    await startAnalysis({
      collectionId,
      config: {
        name: 'Hodoscope analysis',
        group_by: groupBy === AUTO_GROUP ? null : groupBy,
        limit,
        seed: DEFAULT_SEED,
        projection_method: projectionMethod,
      },
    }).unwrap();
    setSelectedPointId(null);
    void refetchAnalyses();
  };

  const handleCancel = async () => {
    if (!collectionId || !currentAnalysis) {
      return;
    }

    await cancelAnalysis({
      collectionId,
      analysisId: currentAnalysis.id,
    }).unwrap();
    void refetchAnalyses();
  };

  const handleDownload = async () => {
    if (!collectionId || !currentAnalysis) {
      return;
    }

    const artifact = await getArtifact({
      collectionId,
      analysisId: currentAnalysis.id,
    }).unwrap();
    const blob = new Blob([JSON.stringify(artifact, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `hodoscope-${currentAnalysis.id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const navToPoint = (point: HodoscopeProjectionPoint) => {
    if (!collectionId) {
      return;
    }

    navToAgentRun(
      router,
      window,
      point.agent_run_id,
      point.transcript_idx,
      point.first_block_idx ?? undefined,
      collectionId
    );
  };

  const busy =
    startState.isLoading ||
    cancelState.isLoading ||
    artifactState.isFetching ||
    isFetchingAnalyses;

  return (
    <section className="border-y border-blue-border py-4">
      <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Radar className="h-4 w-4 text-blue-text" />
            <div className="text-sm font-semibold">Hodoscope</div>
            {currentAnalysis ? (
              <Badge
                variant={
                  currentAnalysis.status === 'error'
                    ? 'destructive'
                    : 'secondary'
                }
              >
                {statusLabel[currentAnalysis.status] ?? currentAnalysis.status}
              </Badge>
            ) : null}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {currentAnalysis?.stage
              ? `${currentAnalysis.stage} · ${currentAnalysis.point_count} points`
              : projectionStateText(projection)}
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <div className="w-52">
            <Label className="text-xs">Group by</Label>
            <Select value={groupBy} onValueChange={setGroupBy}>
              <SelectTrigger className="mt-1 h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={AUTO_GROUP}>Auto detect model</SelectItem>
                {fieldOptions.map((field) => (
                  <SelectItem key={field} value={field}>
                    {field}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="w-24">
            <Label className="text-xs">Max runs</Label>
            <Input
              className="mt-1 h-8"
              min={1}
              max={5000}
              type="number"
              value={limit}
              onChange={(event) =>
                setLimit(Math.max(1, Number(event.target.value) || 1))
              }
            />
          </div>

          <div className="w-32">
            <Label className="text-xs">Projection</Label>
            <Select
              value={projectionMethod}
              onValueChange={(value) =>
                setProjectionMethod(value as HodoscopeProjectionMethod)
              }
            >
              <SelectTrigger className="mt-1 h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="tsne">t-SNE</SelectItem>
                <SelectItem value="pca">PCA</SelectItem>
                <SelectItem value="umap">UMAP</SelectItem>
                <SelectItem value="trimap">TriMap</SelectItem>
                <SelectItem value="pacmap">PaCMAP</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {isActive ? (
            <Button
              className="h-8"
              size="sm"
              variant="outline"
              disabled={!hasWritePermission || busy}
              onClick={handleCancel}
            >
              {cancelState.isLoading ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Square className="mr-2 h-3.5 w-3.5" />
              )}
              Cancel
            </Button>
          ) : (
            <Button
              className="h-8"
              size="sm"
              disabled={!hasWritePermission || busy || !collectionId}
              onClick={handleRun}
            >
              {startState.isLoading ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="mr-2 h-3.5 w-3.5" />
              )}
              Run
            </Button>
          )}

          <Button
            className="h-8"
            size="sm"
            variant="outline"
            disabled={!currentAnalysis || currentAnalysis.status !== 'complete'}
            onClick={handleDownload}
          >
            {artifactState.isFetching ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="mr-2 h-3.5 w-3.5" />
            )}
            JSON
          </Button>
        </div>
      </div>

      {currentAnalysis?.error ? (
        <div className="mb-3 flex items-start gap-2 rounded-md border border-red-border bg-red-bg px-3 py-2 text-xs text-red-text">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words">{currentAnalysis.error}</span>
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-h-64 rounded-md border border-blue-border bg-background">
          {isFetchingProjection ? (
            <div className="flex h-64 items-center justify-center text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : projection?.points.length ? (
            <svg
              className="h-64 w-full"
              role="img"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
            >
              {projection.points.map((point) => {
                const normalized = normalizedPoints.get(point.id);
                if (!normalized) {
                  return null;
                }
                const isSelected = point.id === selectedPoint?.id;
                return (
                  <circle
                    key={point.id}
                    aria-label={point.summary}
                    cx={normalized.x}
                    cy={normalized.y}
                    r={isSelected ? 1.9 : 1.35}
                    fill={getGroupColor(point.group, groupNames)}
                    opacity={isSelected ? 1 : 0.72}
                    stroke="hsl(var(--background))"
                    strokeWidth={isSelected ? 0.7 : 0.35}
                    className="cursor-pointer transition-opacity hover:opacity-100"
                    onClick={() => navToPoint(point)}
                    onMouseEnter={() => setSelectedPointId(point.id)}
                  >
                    <title>{point.summary}</title>
                  </circle>
                );
              })}
            </svg>
          ) : (
            <div className="flex h-64 flex-col items-center justify-center px-4 text-center text-xs text-muted-foreground">
              <Radar className="mb-2 h-5 w-5" />
              Run Hodoscope to project action summaries for this collection.
            </div>
          )}
        </div>

        <div className="min-w-0 space-y-3">
          {projection?.groups.length ? (
            <div className="space-y-1">
              <div className="text-xs font-medium">Groups</div>
              <div className="flex flex-wrap gap-1.5">
                {projection.groups.map((group) => (
                  <Badge
                    key={group.name}
                    variant="outline"
                    className="max-w-full gap-1 truncate"
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{
                        backgroundColor: getGroupColor(group.name, groupNames),
                      }}
                    />
                    <span className="truncate">{group.name}</span>
                    <span className="text-muted-foreground">{group.count}</span>
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}

          {selectedPoint ? (
            <div className="rounded-md border border-blue-border p-3">
              <div className="mb-1 flex items-center justify-between gap-2">
                <Badge variant="secondary" className="truncate">
                  {selectedPoint.group}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  FPS {selectedPoint.fps_rank}
                </span>
              </div>
              <button
                className="line-clamp-3 text-left text-xs font-medium hover:text-blue-text"
                onClick={() => navToPoint(selectedPoint)}
              >
                {selectedPoint.summary}
              </button>
              <div className="mt-2 line-clamp-3 text-xs text-muted-foreground">
                {selectedPoint.task_context || selectedPoint.action_text}
              </div>
            </div>
          ) : null}

          <div className="space-y-1">
            <div className="text-xs font-medium">Representatives</div>
            <div className="max-h-48 space-y-1 overflow-auto pr-1">
              {representatives.length ? (
                representatives.map((point) => (
                  <button
                    key={point.id}
                    className={cn(
                      'flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-blue-bg',
                      selectedPoint?.id === point.id && 'bg-blue-bg'
                    )}
                    onClick={() => setSelectedPointId(point.id)}
                    onDoubleClick={() => navToPoint(point)}
                  >
                    <span
                      className="mt-1 h-2 w-2 shrink-0 rounded-full"
                      style={{
                        backgroundColor: getGroupColor(point.group, groupNames),
                      }}
                    />
                    <span className="min-w-0">
                      <span className="line-clamp-2">{point.summary}</span>
                      <span className="text-muted-foreground">
                        FPS {point.fps_rank}
                      </span>
                    </span>
                  </button>
                ))
              ) : (
                <div className="rounded-md border border-blue-border px-3 py-6 text-center text-xs text-muted-foreground">
                  No representative samples yet.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
