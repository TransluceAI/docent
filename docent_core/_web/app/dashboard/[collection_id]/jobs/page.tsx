'use client';

import React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import UuidPill from '@/components/UuidPill';

import { Separator } from '@/components/ui/separator';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';

import {
  useGetAgentRunIngestJobsQuery,
  AgentRunIngestJob,
} from '../../../api/collectionApi';

export default function JobsPage() {
  const params = useParams();
  const router = useRouter();
  const collectionId = params.collection_id as string;

  const {
    data: jobs = [],
    isLoading,
    error,
  } = useGetAgentRunIngestJobsQuery(collectionId, {
    skip: !collectionId,
  });

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
      <Badge variant={variants[status]} className="capitalize">
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
    return date.toLocaleString();
  };

  const handleRowClick = (jobId: string) => {
    router.push(`/dashboard/${collectionId}/jobs/${jobId}`);
  };

  if (isLoading && jobs.length === 0) {
    return (
      <div className="container mx-auto py-4 px-3 max-w-screen-xl">
        <div className="flex items-center justify-center py-8">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-4 px-3 max-w-screen-xl">
      <div className="space-y-1 mb-4">
        <div className="flex justify-between items-center">
          <div>
            <div className="text-lg font-semibold tracking-tight">
              Agent Run Ingestion Jobs
            </div>
            <div className="text-sm text-muted-foreground">
              View agent run ingestion jobs for this collection
            </div>
          </div>
        </div>
      </div>

      <Separator className="my-4" />

      {error && (
        <div className="text-red-500 text-sm mb-4 p-3 bg-red-50 rounded">
          Failed to load jobs
        </div>
      )}

      {jobs.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          No agent run ingestion jobs found for this collection.
        </div>
      ) : (
        <Table>
          <TableHeader className="bg-secondary sticky top-0">
            <TableRow>
              <TableHead className="py-2.5 font-medium text-xs text-muted-foreground">
                Job ID
              </TableHead>
              <TableHead className="py-2.5 font-medium text-xs text-muted-foreground">
                Created At
              </TableHead>
              <TableHead className="py-2.5 font-medium text-xs text-muted-foreground">
                Type
              </TableHead>
              <TableHead className="py-2.5 font-medium text-xs text-muted-foreground">
                Status
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job) => (
              <TableRow
                key={job.job_id}
                className="cursor-pointer hover:bg-muted/50"
                onClick={() => handleRowClick(job.job_id)}
              >
                <TableCell>
                  <span onClick={(e) => e.stopPropagation()}>
                    <UuidPill uuid={job.job_id} />
                  </span>
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {formatDate(job.created_at)}
                </TableCell>
                <TableCell>{formatJobType(job.type)}</TableCell>
                <TableCell>{getStatusBadge(job.status)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
