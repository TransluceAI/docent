'use client';

import Breadcrumbs from '../components/Breadcrumbs';
import React, { useEffect, Suspense, useState, useRef } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';

import { useAppDispatch, useAppSelector } from '../store/hooks';
import {
  initSession,
  resetFrameSlice,
  setHasInitAttributeDimId,
} from '../store/frameSlice';
import ResponsiveCheck from '../components/ResponsiveCheck';
import { requestAttributes } from '../store/attributeFinderSlice';

export default function DocentLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const dispatch = useAppDispatch();
  const params = useParams();
  const evalId = params.eval_id as string;

  // Fetch state from the server
  const fetchRef = React.useRef(false); // Prevent double fetch
  useEffect(() => {
    if (!evalId || fetchRef.current) {
      return;
    }
    fetchRef.current = true;
    console.log(`Starting eval with ID from URL: ${evalId}`);
    dispatch(initSession(evalId));
  }, [evalId, dispatch]);

  /**
   * Handle shared persisted search
   */
  const router = useRouter();
  const searchParams = useSearchParams();

  const frameGridId = useAppSelector((state) => state.frame.frameGridId);
  const dimensionsMap = useAppSelector((state) => state.frame.dimensionsMap);

  const [initAttributeDimId, setInitAttributeDimId] = useState<
    string | undefined
  >(undefined);

  // Check if the URL contains an attributeDimId parameter
  const searchParamsCheckedRef = useRef(false);
  useEffect(() => {
    if (searchParamsCheckedRef.current) return;

    const attributeDimId = searchParams.get('attributeDimId');
    if (attributeDimId) {
      setInitAttributeDimId(attributeDimId);
      dispatch(setHasInitAttributeDimId(true));
      console.log('Found attributeDimId in URL:', attributeDimId);

      // Create a new URLSearchParams object without the attributeQuery
      const newSearchParams = new URLSearchParams(searchParams.toString());
      newSearchParams.delete('attributeDimId');

      // Update the URL without adding to history
      router.replace(
        `${window.location.pathname}?${newSearchParams.toString()}`
      );
    } else {
      dispatch(setHasInitAttributeDimId(false));
      console.log('No attributeDimId found in URL');
    }

    searchParamsCheckedRef.current = true;
  }, [searchParams, router, dispatch]);

  // If the URL comes with an attributeDimId, we need to request the attributes
  const alreadyRequestedInitAttribute = useRef(false);
  useEffect(() => {
    if (
      !alreadyRequestedInitAttribute.current &&
      frameGridId &&
      initAttributeDimId &&
      dimensionsMap
    ) {
      dispatch(
        requestAttributes({
          attribute: undefined,
          existingDimId: initAttributeDimId,
        })
      );
      alreadyRequestedInitAttribute.current = true;
    }
  }, [initAttributeDimId, dispatch, frameGridId, dimensionsMap]);

  return (
    <div className="flex flex-col h-screen p-3 pt-2 space-y-2">
      <Suspense fallback={<div className="h-6">Loading breadcrumbs...</div>}>
        <Breadcrumbs />
      </Suspense>
      <ResponsiveCheck>{children}</ResponsiveCheck>
    </div>
  );
}
