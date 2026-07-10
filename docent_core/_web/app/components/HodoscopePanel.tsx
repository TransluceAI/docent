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
import { navToAgentRun } from '@/lib/nav';

import {
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
import { HodoscopeEmbeddingMap } from './HodoscopeEmbeddingMap';

const DEFAULT_LIMIT = 500;
const DEFAULT_MAX_ACTIONS = 5000;
const DEFAULT_SEED = 42;
const AUTO_GROUP = '__auto__';

const statusLabel: Record<string, string> = {
  pending: 'Pending',
  running: 'Running',
  complete: 'Complete',
  error: 'Error',
  canceled: 'Canceled',
};

export function HodoscopePanel({
  hasWritePermission,
}: {
  hasWritePermission: boolean;
}) {
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const router = useRouter();

  const [groupBy, setGroupBy] = useState(AUTO_GROUP);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [maxActions, setMaxActions] = useState(DEFAULT_MAX_ACTIONS);
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
        max_actions: maxActions,
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
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border/80 bg-card shadow-sm">
      <header className="border-b border-border/70 bg-muted/10 px-4 py-3">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-blue-border bg-blue-bg text-blue-text shadow-sm">
                <Radar className="h-4 w-4" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold">Hodoscope Embedding</h2>
                  {currentAnalysis ? (
                    <Badge
                      variant={
                        currentAnalysis.status === 'error'
                          ? 'destructive'
                          : 'secondary'
                      }
                      className="h-5 rounded-full px-2 text-[10px]"
                    >
                      {statusLabel[currentAnalysis.status] ??
                        currentAnalysis.status}
                    </Badge>
                  ) : null}
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {projection
                    ? `${projection.projection_method.toUpperCase()} · ${projection.points.length} actions · ${projection.groups.length} groups`
                    : currentAnalysis?.stage
                      ? `${currentAnalysis.stage} · ${currentAnalysis.point_count} actions`
                      : 'Explore behavioral neighborhoods across agent trajectories'}
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <div className="w-48">
              <Label className="text-[11px] text-muted-foreground">
                Group by
              </Label>
              <Select value={groupBy} onValueChange={setGroupBy}>
                <SelectTrigger
                  aria-label="Group Hodoscope points by"
                  className="mt-1 h-8 border-border/70 bg-background text-xs"
                >
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
              <Label
                htmlFor="hodoscope-max-runs"
                className="text-[11px] text-muted-foreground"
              >
                Max runs
              </Label>
              <Input
                id="hodoscope-max-runs"
                className="mt-1 h-8 border-border/70 bg-background text-xs"
                min={1}
                max={500}
                type="number"
                value={limit}
                onChange={(event) =>
                  setLimit(
                    Math.min(500, Math.max(1, Number(event.target.value) || 1))
                  )
                }
              />
            </div>

            <div className="w-24">
              <Label
                htmlFor="hodoscope-max-points"
                className="text-[11px] text-muted-foreground"
              >
                Max points
              </Label>
              <Input
                id="hodoscope-max-points"
                className="mt-1 h-8 border-border/70 bg-background text-xs"
                min={500}
                max={5000}
                type="number"
                value={maxActions}
                onChange={(event) =>
                  setMaxActions(
                    Math.min(
                      5000,
                      Math.max(500, Number(event.target.value) || 500)
                    )
                  )
                }
              />
            </div>

            <div className="w-28">
              <Label className="text-[11px] text-muted-foreground">
                Next projection
              </Label>
              <Select
                value={projectionMethod}
                onValueChange={(value) =>
                  setProjectionMethod(value as HodoscopeProjectionMethod)
                }
              >
                <SelectTrigger
                  aria-label="Choose the next Hodoscope projection method"
                  className="mt-1 h-8 border-border/70 bg-background text-xs"
                >
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
              disabled={
                !currentAnalysis || currentAnalysis.status !== 'complete'
              }
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

        {isActive && currentAnalysis?.progress !== null ? (
          <div
            className="mt-3 h-1 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-label="Hodoscope analysis progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={currentAnalysis?.progress ?? 0}
          >
            <div
              className="h-full rounded-full bg-blue-text transition-[width] motion-reduce:transition-none"
              style={{ width: `${currentAnalysis?.progress ?? 0}%` }}
            />
          </div>
        ) : null}
      </header>

      {currentAnalysis?.error ? (
        <div className="mx-3 mt-3 flex items-start gap-2 rounded-lg border border-red-border bg-red-bg px-3 py-2 text-xs text-red-text">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words">{currentAnalysis.error}</span>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 p-3">
        {isFetchingProjection ? (
          <div className="flex h-full min-h-48 items-center justify-center rounded-xl border border-border/70 bg-muted/10 text-muted-foreground">
            <div className="flex items-center gap-2 text-xs">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading embedding
            </div>
          </div>
        ) : projection?.points.length ? (
          <HodoscopeEmbeddingMap
            projection={projection}
            selectedPointId={selectedPointId}
            onSelectedPointChange={setSelectedPointId}
            onOpenPoint={navToPoint}
            layoutStorageKey={`docent-hodoscope-${collectionId ?? 'unknown'}-v1`}
          />
        ) : (
          <div className="flex h-full min-h-48 flex-col items-center justify-center rounded-xl border border-dashed border-border bg-muted/10 px-6 text-center">
            <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl border border-border bg-background shadow-sm">
              <Radar className="h-5 w-5 text-muted-foreground" />
            </div>
            <h3 className="text-sm font-semibold">No embedding yet</h3>
            <p className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
              Run Hodoscope to summarize trajectory actions and project their
              behavioral neighborhoods into this interactive map.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
