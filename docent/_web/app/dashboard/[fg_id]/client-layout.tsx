'use client';

import { useParams, useRouter, useSearchParams } from 'next/navigation';
import React, { useEffect, Suspense, useRef } from 'react';

import Breadcrumbs from '../../components/Breadcrumbs';
import ResponsiveCheck from '../../components/ResponsiveCheck';
import {
  getDimensions,
  initSession,
  setHasInitSearchQuery,
} from '../../store/frameSlice';
import { useAppDispatch } from '../../store/hooks';
import { handleSearchUpdate, setSearchQuery } from '@/app/store/searchSlice';
import { apiRestClient } from '@/app/services/apiService';
import { Button } from '@/components/ui/button';
import { useUserContext } from '@/app/contexts/UserContext';

export default function DocentDashboardClientLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const dispatch = useAppDispatch();
  const params = useParams();
  const fgId = params.fg_id as string;

  // Fetch state from the server
  const fetchRef = React.useRef(false); // Prevent double fetch
  useEffect(() => {
    if (!fgId || fetchRef.current) {
      return;
    }
    fetchRef.current = true;
    console.log(`Starting eval with ID from URL: ${fgId}`);
    dispatch(initSession(fgId));
  }, [fgId, dispatch]);

  /**
   * Handle shared persisted search
   */
  const searchParams = useSearchParams();

  // Check if the URL contains a searchQuery parameter
  const searchParamsCheckedRef = useRef(false);
  useEffect(() => {
    if (searchParamsCheckedRef.current) return;
    searchParamsCheckedRef.current = true;

    const searchQuery = searchParams.get('searchQuery');
    const filterId = searchParams.get('filterId');
    const viewId = searchParams.get('viewId');
    if (searchQuery === null || viewId === null) {
      dispatch(setHasInitSearchQuery(false));
      return;
    }
    dispatch(setHasInitSearchQuery(true));
    apiRestClient
      .post(`/${fgId}/apply_existing_filter`, {
        filter_id: filterId === 'null' ? null : filterId,
        search_query: searchQuery,
        view_id: viewId,
      })
      .then((response) => {
        const dimId = response.data;
        dispatch(setSearchQuery(searchQuery));
        dispatch(setHasInitSearchQuery(true));
        apiRestClient
          .get(
            `/${fgId}/get_existing_search_results?search_query=${searchQuery}`
          )
          .then((response) => {
            dispatch(handleSearchUpdate(response.data));
            if (dimId) {
              dispatch(getDimensions([dimId]));
            }
          });
      });
    return;
  }, [searchParams, dispatch]);

  return (
    <div className="flex flex-col h-screen w-screen p-3 pt-2 space-y-2 min-h-0 min-w-0">
      <Suspense fallback={<div className="h-6">Loading breadcrumbs...</div>}>
        <Breadcrumbs />
      </Suspense>
      <ResponsiveCheck>{children}</ResponsiveCheck>
    </div>
  );
}

export function PermissionDeniedPage() {
  const router = useRouter();
  const { user } = useUserContext();

  const handleLoginRedirect = () => {
    // Capture the current URL to redirect back after login
    const currentUrl = window.location.pathname + window.location.search;
    const encodedRedirect = encodeURIComponent(currentUrl);
    router.push(`/login?redirect=${encodedRedirect}`);
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 space-y-3">
      <div className="text-center">
        <div className="text-base font-semibold text-gray-900">
          Access Denied
        </div>
        <div className="text-gray-600 text-sm">
          You don&apos;t have permission to view this resource
        </div>
      </div>
      <Button size="sm" onClick={handleLoginRedirect}>
        {user === null || user.is_anonymous
          ? 'Login to your account'
          : 'Back home'}
      </Button>
    </div>
  );
}

export function NotFoundPage() {
  const router = useRouter();
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 space-y-3">
      <div className="text-center">
        <div className="text-base font-semibold text-gray-900">Not Found</div>
        <div className="text-gray-600 text-sm">
          The resource you are looking for does not exist.
        </div>
      </div>
      <Button size="sm" onClick={() => router.push('/')}>
        Back home
      </Button>
    </div>
  );
}
