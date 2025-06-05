'use client';

import { useEffect } from 'react';
import Link from 'next/link';

import { BASE_DOCENT_PATH } from '@/app/constants';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import { UserProfile } from '../components/auth/UserProfile';
import { apiRestClient } from '../services/apiService';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { fetchJobs } from '../store/jobsSlice';

export default function JobsPage() {
  const dispatch = useAppDispatch();

  useEffect(() => {
    dispatch(fetchJobs());
  }, []);

  const jobs = useAppSelector((state) => state.jobs.jobs);

  const cancelJob = (id: string) => async () => {
    await apiRestClient.post(`/${id}/cancel_compute_search`);
  };

  return (
    <div className="container mx-auto py-4 px-3 max-w-screen-xl">
      <div className="space-y-1 mb-4">
        <div className="flex justify-between items-center">
          <div>
            <div className="text-lg font-semibold tracking-tight">Searches</div>
          </div>
          <div className="flex items-center gap-2">
            <UserProfile />
          </div>
        </div>
      </div>

      <Separator className="my-4" />

      <Table>
        <TableHeader className="bg-gray-50 sticky top-0">
          <TableRow>
            <TableHead className="w-[5%] py-2.5 font-medium text-xs text-gray-500">
              FrameGrid ID
            </TableHead>
            <TableHead className="w-[5%] py-2.5 font-medium text-xs text-gray-500">
              Started at
            </TableHead>
            <TableHead className="w-[5%] py-2.5 font-medium text-xs text-gray-500">
              Status
            </TableHead>
            <TableHead className="w-[5%] py-2.5 font-medium text-xs text-gray-500">
              Progress
            </TableHead>
            <TableHead className="w-[5%] py-2.5 font-medium text-xs text-gray-500">
              Action
            </TableHead>
            <TableHead className="w-[40%] py-2.5 font-medium text-xs text-gray-500">
              Query
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map(([job, query]) => (
            <TableRow>
              <TableCell>
                <Link
                  href={`${BASE_DOCENT_PATH}/${query.fg_id}`}
                  className="text-blue-600 hover:underline"
                >
                  <span className="font-mono text-gray-600 text-xs">
                    {query.fg_id.split('-')[0]}
                  </span>
                </Link>
              </TableCell>
              <TableCell>{job.created_at}</TableCell>
              <TableCell>{job.status}</TableCell>
              <TableCell>progress</TableCell>
              <TableCell>
                {job.status === 'running' ? (
                  <Button onClick={cancelJob(job.id)}>cancel</Button>
                ) : null}
              </TableCell>
              <TableCell>{query.search_query}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
