'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  useGetUsageSummaryQuery,
  ByokModelBreakdown,
  ByokKeyUsage,
  FreeUsageResponse,
} from '@/app/api/settingsApi';
import { useGetModelApiKeysQuery, ModelApiKey } from '@/app/api/settingsApi';
import { MaskedApiKey } from '@/app/settings/components/MaskedApiKey';
import { getProviderLabel } from '@/app/settings/utils/providers';
import { AlertTriangle } from 'lucide-react';
import Link from 'next/link';

function formatWindow(seconds: number): string {
  const hours = Math.round(seconds / 3600);
  return `Last ${hours} hour${hours === 1 ? '' : 's'}`;
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
  const segmentColors = [
    'bg-blue-text',
    'bg-purple-text',
    'bg-green-text',
    'bg-yellow-text',
    'bg-orange-text',
    'bg-indigo-text',
    'bg-red-text',
  ];

  if (freeUsage && !freeUsage.has_cap) {
    return (
      <Card>
        <CardHeader className="flex flex-row justify-between items-center">
          <CardTitle>Free usage</CardTitle>
          {windowSeconds && (
            <span className="text-sm text-muted-foreground">
              {formatWindow(windowSeconds)}
            </span>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-muted-foreground text-sm mb-2">
            Your account is not subject to usage limits.
          </div>
          <div className="text-primary text-3xl font-regular">
            ${(freeUsage.total_cents / 100).toFixed(2)} USD
          </div>
          {freeUsage.models.length > 0 ? (
            <div className="grid gap-2">
              {freeUsage.models.map((m) => (
                <div key={m.model} className="flex justify-between text-sm">
                  <div className="text-primary">{m.model}</div>
                  <div className="text-muted-foreground">
                    {(m.total_cents / 100).toFixed(2)} USD
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">No usage yet.</div>
          )}
        </CardContent>
      </Card>
    );
  }

  const progress = freeUsage?.fraction_used ?? 0;

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <CardTitle>Free usage</CardTitle>
        {windowSeconds && (
          <span className="text-sm text-muted-foreground">
            {formatWindow(windowSeconds)}
          </span>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {freeUsage ? (
          <div className="space-y-3">
            <div className="flex justify-between text-3xl font-medium">
              <span>{(progress * 100).toFixed(2)}%</span>
            </div>
            <div className="w-full h-2 bg-secondary rounded overflow-hidden flex">
              {freeUsage.models.length === 0 || progress === 0 ? (
                <div className="h-2 w-0" />
              ) : (
                freeUsage.models.map((m, idx) => {
                  const pct = (m.fraction_used ?? 0) * 100;
                  const color = segmentColors[idx % segmentColors.length];
                  return (
                    <div
                      key={m.model}
                      className={`${color}`}
                      style={{ width: `${pct}%` }}
                    />
                  );
                })
              )}
            </div>

            <div className="grid gap-2">
              {freeUsage.models.map((m, idx) => {
                const color = segmentColors[idx % segmentColors.length];
                return (
                  <div
                    key={m.model}
                    className="flex items-center justify-between text-sm"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block h-3 w-3 rounded-sm ${color}`}
                      />
                      <div className="text-primary">{m.model}</div>
                    </div>
                    <div className="text-muted-foreground">
                      {((m.fraction_used ?? 0) * 100).toFixed(2)}%
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="text-muted-foreground text-sm">Loading...</div>
        )}
      </CardContent>
    </Card>
  );
}

function ByokKeyCard({
  apiKeyId,
  totalCents,
  models,
  modelKey,
  windowSeconds,
}: {
  apiKeyId: string;
  totalCents: number;
  models: ByokModelBreakdown[];
  modelKey?: ModelApiKey;
  windowSeconds?: number;
}) {
  const provider = modelKey?.provider
    ? getProviderLabel(modelKey.provider)
    : 'Model provider';
  const masked = modelKey?.masked_api_key ?? `Key ${apiKeyId.slice(0, 8)}…`;

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <div className="flex items-center space-x-3">
          <CardTitle>{provider} API key</CardTitle>
          <MaskedApiKey apiKey={masked} />
        </div>
        {windowSeconds && (
          <span className="text-sm text-muted-foreground">
            {formatWindow(windowSeconds)}
          </span>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex justify-between text-sm">
          <div className="text-primary text-3xl font-regular">
            ${(totalCents / 100).toFixed(2)} USD
          </div>
        </div>
        {models.length > 0 ? (
          <div className="grid gap-2">
            {models.map((m) => (
              <div key={m.model} className="flex justify-between text-sm">
                <div className="text-primary">{m.model}</div>
                <div className="text-muted-foreground">
                  {(m.total_cents / 100).toFixed(2)} USD
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            No usage for this key yet.
          </div>
        )}
        <div className="text-xs text-muted-foreground">
          Docent usage limits do not apply to your own API keys. Costs shown
          here are approximate; check the model provider&apos;s billing website
          for true costs.
        </div>
      </CardContent>
    </Card>
  );
}

export default function UsageSettingsPage() {
  const { data: summary } = useGetUsageSummaryQuery();
  const { data: modelKeys } = useGetModelApiKeysQuery();
  const freeUsage = summary?.free;
  const byokUsage = summary?.byok;

  const overCap = freeUsage?.has_cap && (freeUsage.fraction_used ?? 0) >= 1;

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

      {(() => {
        const keysById: Record<string, ByokKeyUsage | undefined> = {};
        if (byokUsage) {
          for (const k of byokUsage.keys) keysById[k.api_key_id] = k;
        }

        const displayKeys = (modelKeys || [])
          .map((mk: ModelApiKey) => ({
            ...keysById[mk.id],
            modelKey: mk,
          }))
          .filter(
            (k): k is ByokKeyUsage & { modelKey: ModelApiKey } =>
              k.api_key_id !== undefined
          );

        return displayKeys.map((k) => (
          <ByokKeyCard
            key={k.api_key_id}
            apiKeyId={k.api_key_id}
            totalCents={k.total_cents}
            models={k.models}
            modelKey={k.modelKey}
            windowSeconds={summary?.window_seconds}
          />
        ));
      })()}
    </div>
  );
}
