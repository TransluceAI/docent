'use client';

import React, { useEffect } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';

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

import { UserProfile } from '../../components/auth/UserProfile';
import { apiRestClient } from '../../services/apiService';
import { initSession, setHasInitSearchQuery } from '../../store/frameSlice';
import { useAppDispatch, useAppSelector } from '../../store/hooks';

export default function JobsPage() {
  const params = useParams();
  const framegridId = params.framegrid_id as string;
  console.log('jobs', framegridId);
  const dispatch = useAppDispatch();

  // Fetch state from the server
  const fetchRef = React.useRef(false); // Prevent double fetch
  useEffect(() => {
    if (!framegridId || fetchRef.current) {
      return;
    }
    fetchRef.current = true;
    dispatch(initSession(framegridId));
  }, [framegridId, dispatch]);
  const searches = useAppSelector((state) => state.search.searchesWithStats);

  const cancelJob = (id: string) => async () => {
    await apiRestClient.post(`/${id}/cancel_compute_search`);
  };

  const resumeJob = (id: string) => async () => {
    await apiRestClient.post(`/${id}/resume_compute_search`);
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
          {(searches || []).map((search) => {
            console.log(search);
            const done = search.num_judgments_computed;
            const total = search.num_total;
            const completionPercentage = total > 0 ? Math.min((done / total) * 100, 100) : 0;
            const isComplete = false;
            return (
              <TableRow>
                <TableCell>{search.job.created_at}</TableCell>
                <TableCell>{search.job.status}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    <div
                      className="relative w-12 h-1.5 bg-gray-100 rounded-full overflow-hidden flex-shrink-0"
                      title={`${done} of ${total} processed`}
                    >
                      <div
                        className={`absolute top-0 left-0 h-full ${isComplete ? 'bg-indigo-500' : 'bg-blue-500'}`}
                        style={{
                          width: `${completionPercentage}%`,
                        }}
                      ></div>
                    </div>
                    <span className="text-[9px] text-gray-500 whitespace-nowrap">
                      {Math.round(completionPercentage)}% computed
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  {search.job.status === 'running' ? (
                    <Button onClick={cancelJob(search.job.id)}>cancel</Button>
                  ) : search.job.status === 'canceled' ? (
                    <Button onClick={resumeJob(search.search_id)}>resume</Button>
                  ) : null}
                </TableCell>
                <TableCell>{search.search_query}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
