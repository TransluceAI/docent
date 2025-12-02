'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  useGetUsageSummaryQuery,
  ByokKeyUsage,
  FreeUsageResponse,
} from '@/app/api/settingsApi';
import { useGetModelApiKeysQuery, ModelApiKey } from '@/app/api/settingsApi';
import { MaskedApiKey } from '@/app/settings/components/MaskedApiKey';
import { getProviderLabel } from '@/app/settings/utils/providers';
import { AlertTriangle } from 'lucide-react';
import Link from 'next/link';
import { ReactNode } from 'react';

const SEGMENT_COLORS = [
  'bg-blue-text',
  'bg-purple-text',
  'bg-green-text',
  'bg-yellow-text',
  'bg-orange-text',
  'bg-indigo-text',
  'bg-red-text',
];

function formatCents(cents: number): string {
  return `${(cents / 100).toFixed(2)} USD`;
}

function formatWindow(seconds?: number): string {
  if (!seconds) return '';
  const hours = Math.round(seconds / 3600);
  return `Last ${hours} hour${hours === 1 ? '' : 's'}`;
}

function ModelCostList({
  models,
  emptyMessage,
}: {
  models: { model: string; total_cents: number }[];
  emptyMessage: string;
}) {
  if (models.length === 0) {
    return <div className="text-sm text-muted-foreground">{emptyMessage}</div>;
  }
  return (
    <div className="grid gap-2">
      {models.map((m) => (
        <div key={m.model} className="flex justify-between text-sm">
          <div className="text-primary">{m.model}</div>
          <div className="text-muted-foreground">
            ${formatCents(m.total_cents)}
          </div>
        </div>
      ))}
    </div>
  );
}

function UsageCard({
  title,
  titleExtra,
  windowSeconds,
  children,
}: {
  title: string;
  titleExtra?: ReactNode;
  windowSeconds?: number;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <div className="flex items-center space-x-3">
          <CardTitle>{title}</CardTitle>
          {titleExtra}
        </div>
        <span className="text-sm text-muted-foreground">
          {formatWindow(windowSeconds)}
        </span>
      </CardHeader>
      <CardContent className="space-y-3">{children}</CardContent>
    </Card>
  );
}

function UsageLimitExceededAlert() {
  return (
    <Alert variant="destructive">
      <AlertTriangle className="h-4 w-4" />
      <AlertDescription>
        You have exceeded your free usage limit. Consider{' '}
        <Link href="/settings/model-providers" className="underline">
          using your own API keys
        </Link>{' '}
        or email{' '}
        <a
          style={{ textDecoration: 'underline' }}
          href="mailto:docent@transluce.org"
        >
          docent@transluce.org
        </a>{' '}
        to inquire about custom usage limits.
      </AlertDescription>
    </Alert>
  );
}

function FreeUsageCard({
  freeUsage,
  windowSeconds,
}: {
  freeUsage: FreeUsageResponse | undefined;
  windowSeconds?: number;
}) {
  if (!freeUsage) {
    return (
      <UsageCard title="Free usage" windowSeconds={windowSeconds}>
        <div className="text-muted-foreground text-sm">Loading...</div>
      </UsageCard>
    );
  }

  if (!freeUsage.has_cap) {
    return (
      <UsageCard title="Free usage" windowSeconds={windowSeconds}>
        <div className="text-muted-foreground text-sm mb-2">
          Your account is not subject to usage limits.
        </div>
        <div className="text-primary text-3xl font-regular">
          ${formatCents(freeUsage.total_cents)}
        </div>
        <ModelCostList models={freeUsage.models} emptyMessage="No usage yet." />
      </UsageCard>
    );
  }

  const progress = freeUsage.fraction_used ?? 0;

  return (
    <UsageCard title="Free usage" windowSeconds={windowSeconds}>
      <div className="space-y-3">
        <div className="flex justify-between text-3xl font-medium">
          <span>{(progress * 100).toFixed(2)}%</span>
        </div>
        <div className="w-full h-2 bg-secondary rounded overflow-hidden flex">
          {freeUsage.models.length === 0 || progress === 0 ? (
            <div className="h-2 w-0" />
          ) : (
            freeUsage.models.map((m, idx) => (
              <div
                key={m.model}
                className={SEGMENT_COLORS[idx % SEGMENT_COLORS.length]}
                style={{ width: `${(m.fraction_used ?? 0) * 100}%` }}
              />
            ))
          )}
        </div>
        <div className="grid gap-2">
          {freeUsage.models.map((m, idx) => (
            <div
              key={m.model}
              className="flex items-center justify-between text-sm"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`inline-block h-3 w-3 rounded-sm ${SEGMENT_COLORS[idx % SEGMENT_COLORS.length]}`}
                />
                <div className="text-primary">{m.model}</div>
              </div>
              <div className="text-muted-foreground">
                {((m.fraction_used ?? 0) * 100).toFixed(2)}%
              </div>
            </div>
          ))}
        </div>
      </div>
    </UsageCard>
  );
}

function ByokKeyCard({
  usage,
  modelKey,
  windowSeconds,
}: {
  usage: ByokKeyUsage;
  modelKey?: ModelApiKey;
  windowSeconds?: number;
}) {
  const provider = modelKey?.provider
    ? getProviderLabel(modelKey.provider)
    : 'Model provider';
  const masked =
    modelKey?.masked_api_key ?? `Key ${usage.api_key_id.slice(0, 8)}…`;

  return (
    <UsageCard
      title={`${provider} API key`}
      titleExtra={<MaskedApiKey apiKey={masked} />}
      windowSeconds={windowSeconds}
    >
      <div className="text-primary text-3xl font-regular">
        ${formatCents(usage.total_cents)}
      </div>
      <ModelCostList
        models={usage.models}
        emptyMessage="No usage for this key yet."
      />
      <div className="text-xs text-muted-foreground">
        Docent usage limits do not apply to your own API keys. Costs shown here
        are approximate; check the model provider&apos;s billing website for
        true costs.
      </div>
    </UsageCard>
  );
}

export default function UsageSettingsPage() {
  const { data: summary } = useGetUsageSummaryQuery();
  const { data: modelKeys } = useGetModelApiKeysQuery();
  const freeUsage = summary?.free;
  const byokUsage = summary?.byok;

  const overCap = freeUsage?.has_cap && (freeUsage.fraction_used ?? 0) >= 1;

  const keysById: Record<string, ByokKeyUsage | undefined> = {};
  for (const k of byokUsage?.keys ?? []) keysById[k.api_key_id] = k;

  const displayKeys = (modelKeys ?? [])
    .map((mk) => ({ usage: keysById[mk.id], modelKey: mk }))
    .filter(
      (k): k is { usage: ByokKeyUsage; modelKey: ModelApiKey } =>
        k.usage !== undefined
    );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Usage</h1>
        <p className="text-muted-foreground">
          Usage of free AI models on Docent is subject to daily limits.
        </p>
      </div>

      {overCap && <UsageLimitExceededAlert />}

      <FreeUsageCard
        freeUsage={freeUsage}
        windowSeconds={summary?.window_seconds}
      />

      {displayKeys.map((k) => (
        <ByokKeyCard
          key={k.usage.api_key_id}
          usage={k.usage}
          modelKey={k.modelKey}
          windowSeconds={summary?.window_seconds}
        />
      ))}
    </div>
  );
}
