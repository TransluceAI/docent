'use client';

import { useParams, useRouter, useSearchParams } from 'next/navigation';
import React, { useEffect, Suspense, useState, useRef } from 'react';

import Breadcrumbs from '../../components/Breadcrumbs';
import ResponsiveCheck from '../../components/ResponsiveCheck';
import { initSession, setHasInitSearchQuery } from '../../store/frameSlice';
import { useAppDispatch, useAppSelector } from '../../store/hooks';
import { computeSearch } from '@/app/store/searchSlice';

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
  const router = useRouter();
  const searchParams = useSearchParams();
  const dimensionsMap = useAppSelector((state) => state.frame.dimensionsMap);

  const [initSearchQuery, setInitSearchQuery] = useState<string | undefined>(
    undefined
  );

  // Check if the URL contains a searchQuery parameter
  const searchParamsCheckedRef = useRef(false);
  useEffect(() => {
    if (searchParamsCheckedRef.current) return;

    const searchQuery = searchParams.get('searchQuery');
    if (searchQuery) {
      setInitSearchQuery(searchQuery);
      dispatch(setHasInitSearchQuery(true));
      console.log('Found searchQuery in URL:', searchQuery);

      // Create a new URLSearchParams object without the searchQuery
      const newSearchParams = new URLSearchParams(searchParams.toString());
      newSearchParams.delete('searchQuery');

      // Update the URL without adding to history
      router.replace(
        `${window.location.pathname}?${newSearchParams.toString()}`
      );
    } else {
      dispatch(setHasInitSearchQuery(false));
      console.log('No searchQuery found in URL');
    }

    searchParamsCheckedRef.current = true;
  }, [searchParams, router, dispatch]);

  // If the URL comes with an searchQuery, we need to request the search
  const alreadyRequestedInitSearch = useRef(false);
  useEffect(() => {
    if (
      !alreadyRequestedInitSearch.current &&
      fgId &&
      initSearchQuery &&
      dimensionsMap
    ) {
      dispatch(
        computeSearch({
          searchQuery: initSearchQuery,
        })
      );
      alreadyRequestedInitSearch.current = true;
    }
  }, [initSearchQuery, dispatch, fgId, dimensionsMap]);

  return (
    <div className="flex flex-col h-screen w-screen p-3 pt-2 space-y-2 min-h-0 min-w-0">
      <Suspense fallback={<div className="h-6">Loading breadcrumbs...</div>}>
        <Breadcrumbs />
      </Suspense>
      <ResponsiveCheck>{children}</ResponsiveCheck>
    </div>
  );
}
