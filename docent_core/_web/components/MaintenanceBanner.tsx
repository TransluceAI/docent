'use client';

import { useEffect, useCallback, useRef } from 'react';
import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { toast } from 'sonner';
import { useLocalStorage } from 'usehooks-ts';
import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PERSISTENT_TOASTER_ID } from '@/components/ui/sonner';
import { useRequireUserContext } from '@/app/contexts/UserContext';

interface AffectedComponent {
  id: string;
  name: string;
  current_status: string;
}

interface Maintenance {
  id: string;
  name: string;
  status: 'maintenance_scheduled' | 'maintenance_in_progress';
  url: string;
  affected_components: AffectedComponent[];
  starts_at: string;
  ends_at: string;
  last_update_at: string;
  last_update_message: string;
}

interface StatusResponse {
  page_title: string;
  page_url: string;
  ongoing_incidents: unknown[];
  in_progress_maintenances: Maintenance[];
  scheduled_maintenances: Maintenance[];
}

const DISMISSED_MAINTENANCES_KEY = 'dismissed-maintenances';

const statusApi = createApi({
  reducerPath: 'statusApi',
  baseQuery: fetchBaseQuery({ baseUrl: 'https://status.transluce.org/api/v1' }),
  endpoints: (builder) => ({
    getStatus: builder.query<StatusResponse, void>({
      query: () => '/summary',
    }),
  }),
});

const { useGetStatusQuery } = statusApi;
export { statusApi };

function formatDateTime(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export function MaintenanceBanner() {
  const { user } = useRequireUserContext();
  const shownToastsRef = useRef<Set<string>>(new Set());

  const { data } = useGetStatusQuery();

  const [dismissedIds, setDismissedIds] = useLocalStorage<string[]>(
    `${DISMISSED_MAINTENANCES_KEY}_${user.id}`,
    [],
    { initializeWithValue: false }
  );

  const handleDismiss = useCallback(
    (toastId: string) => {
      setDismissedIds((prev) => [...prev, toastId]);
      toast.dismiss(toastId);
    },
    [setDismissedIds]
  );

  const showMaintenanceToast = useCallback(
    (maintenance: Maintenance, isInProgress: boolean) => {
      const toastId = `maintenance-${maintenance.id}`;

      // Skip if already dismissed or already shown
      if (
        dismissedIds.includes(toastId) ||
        shownToastsRef.current.has(toastId)
      ) {
        return;
      }

      shownToastsRef.current.add(toastId);

      const startTime = formatDateTime(maintenance.starts_at);
      const endTime = formatDateTime(maintenance.ends_at);

      const bgColor = isInProgress ? 'bg-red-bg' : 'bg-orange-bg';
      const borderColor = isInProgress
        ? 'border-red-border'
        : 'border-orange-border';
      const textColor = isInProgress ? 'text-red-text' : 'text-orange-text';

      toast.custom(
        () => (
          <div
            className={`w-full max-w-md p-4 ${bgColor} border ${borderColor} rounded-lg shadow-lg`}
          >
            <div className="flex flex-col gap-2">
              <div className="flex items-start justify-between gap-2">
                <p className={`font-semibold ${textColor}`}>
                  {isInProgress
                    ? 'Maintenance In Progress'
                    : 'Scheduled Maintenance'}
                </p>
                <button
                  onClick={() => handleDismiss(toastId)}
                  className="text-muted-foreground hover:text-primary transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <p className="text-sm text-primary">
                {maintenance.last_update_message}
              </p>
              <p className="text-sm text-muted-foreground">
                {isInProgress
                  ? `Expected end: ${endTime}`
                  : `${startTime} - ${endTime}`}
              </p>
              <div className="flex items-center justify-end gap-2 mt-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => window.open(maintenance.url, '_blank')}
                >
                  View Details
                </Button>
              </div>
            </div>
          </div>
        ),
        {
          id: toastId,
          duration: Infinity,
          toasterId: PERSISTENT_TOASTER_ID,
        }
      );
    },
    [dismissedIds, handleDismiss]
  );

  useEffect(() => {
    if (!data) return;

    // Show in-progress maintenances first (higher urgency)
    data.in_progress_maintenances.forEach((maintenance) => {
      showMaintenanceToast(maintenance, true);
    });

    // Show scheduled maintenances
    data.scheduled_maintenances.forEach((maintenance) => {
      showMaintenanceToast(maintenance, false);
    });
  }, [data, showMaintenanceToast]);

  // This component doesn't render anything - it just manages toasts
  return null;
}
