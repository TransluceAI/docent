'use client';

import React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

import {
  useGetAgentRunIngestJobQuery,
  AgentRunIngestJob,
} from '../../../../api/collectionApi';

export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const collectionId = params.collection_id as string;
  const jobId = params.job_id as string;

  const [shouldPoll, setShouldPoll] = React.useState(true);

  const {
    data: job,
    isLoading,
    error,
  } = useGetAgentRunIngestJobQuery(
    { collectionId, jobId },
    {
      skip: !collectionId || !jobId,
      pollingInterval: shouldPoll ? 2000 : 0,
    }
  );

  // Stop polling when job completes or is canceled
  React.useEffect(() => {
    if (job && job.status !== 'pending' && job.status !== 'running') {
      setShouldPoll(false);
    }
  }, [job?.status]);

  const getStatusBadge = (status: AgentRunIngestJob['status']) => {
    const variants: Record<
      AgentRunIngestJob['status'],
      'default' | 'secondary' | 'destructive' | 'outline'
    > = {
      pending: 'secondary',
      running: 'default',
      completed: 'outline',
      canceled: 'destructive',
    };

    return (
      <Badge
        variant={variants[status]}
        className="capitalize text-sm px-3 py-1"
      >
        {status}
      </Badge>
    );
  };

  const formatJobType = (type: string) => {
    return type
      .replace(/_/g, ' ')
      .replace(/job$/i, '')
      .trim()
      .split(' ')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const handleBack = () => {
    router.push(`/dashboard/${collectionId}/jobs`);
  };

  if (isLoading) {
    return (
      <div className="container mx-auto py-4 px-3 max-w-screen-xl">
        <div className="flex items-center justify-center py-8">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto py-4 px-3 max-w-screen-xl">
        <Button variant="ghost" onClick={handleBack} className="mb-4">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Jobs
        </Button>
        <div className="text-red-500 text-sm p-3 bg-red-50 rounded">
          Failed to load job details
        </div>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="container mx-auto py-4 px-3 max-w-screen-xl">
        <Button variant="ghost" onClick={handleBack} className="mb-4">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Jobs
        </Button>
        <div className="text-center py-8 text-muted-foreground">
          Job not found
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-4 px-3 max-w-screen-xl">
      <Button variant="ghost" onClick={handleBack} className="mb-4">
        <ArrowLeft className="mr-2 h-4 w-4" />
        Back to Jobs
      </Button>

      <div className="space-y-1 mb-4">
        <div className="flex justify-between items-center">
          <div>
            <div className="text-lg font-semibold tracking-tight">
              Job Details
            </div>
            <div className="text-sm text-muted-foreground">
              Detailed information about this background job
            </div>
          </div>
        </div>
      </div>

      <Separator className="my-4" />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Job Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-1">
                Job ID
              </div>
              <div className="font-mono text-sm">{job.job_id}</div>
            </div>
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-1">
                Type
              </div>
              <div className="text-sm">{formatJobType(job.type)}</div>
            </div>
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-1">
                Status
              </div>
              <div>{getStatusBadge(job.status)}</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Timestamps</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-1">
                Created At
              </div>
              <div className="text-sm">{formatDate(job.created_at)}</div>
            </div>
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-1">
                Collection ID
              </div>
              <div className="font-mono text-sm">{job.collection_id}</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {(job.status === 'pending' || job.status === 'running') && (
        <div className="mt-4 px-3 py-2 bg-blue-50 rounded-lg border border-blue-200">
          <div className="text-sm text-blue-900">
            <span className="font-medium">
              {job.status === 'pending' ? 'Queued' : 'In Progress'}
            </span>
            {' - '}
            This job is currently being processed. This page will automatically
            update.
          </div>
        </div>
      )}

      {job.status === 'completed' && (
        <div className="mt-4 px-3 py-2 bg-green-50 rounded-lg border border-green-200">
          <div className="text-sm text-green-900">
            <span className="font-medium">Completed</span>
            {' - '}
            This job has finished successfully.
          </div>
        </div>
      )}

      {job.status === 'canceled' && (
        <div className="mt-4 px-3 py-2 bg-red-50 rounded-lg border border-red-200">
          <div className="text-sm text-red-900">
            <span className="font-medium">Failed</span>
            {' - '}
            This job encountered an error or was canceled.
          </div>
        </div>
      )}
    </div>
  );
}
