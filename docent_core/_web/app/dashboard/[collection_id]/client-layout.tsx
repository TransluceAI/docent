'use client';

import { useParams, useRouter } from 'next/navigation';
import React, { useEffect, Suspense } from 'react';

import Breadcrumbs from '../../components/Breadcrumbs';
import ResponsiveCheck from '../../components/ResponsiveCheck';
import { initSession } from '../../store/collectionSlice';
import { useAppDispatch } from '../../store/hooks';
import { Button } from '@/components/ui/button';
import { useUserContext } from '@/app/contexts/UserContext';

export default function DocentDashboardClientLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const dispatch = useAppDispatch();
  const params = useParams();
  const collectionId = params.collection_id as string;

  // Fetch state from the server
  const fetchRef = React.useRef(false); // Prevent double fetch
  useEffect(() => {
    if (!collectionId || fetchRef.current) {
      return;
    }
    fetchRef.current = true;
    dispatch(initSession(collectionId));
  }, [collectionId, dispatch]);

  return (
    <div className="flex flex-col h-screen w-screen p-3 pt-2 space-y-2 min-h-0 min-w-[900px]">
      <Suspense fallback={<div className="h-7">Loading breadcrumbs...</div>}>
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
    router.push(`/signup?redirect=${encodedRedirect}`);
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-secondary space-y-3">
      <div className="text-center">
        <div className="text-base font-semibold text-primary">
          Access Denied
        </div>
        <div className="text-muted-foreground text-sm">
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
    <div className="min-h-screen flex flex-col items-center justify-center bg-secondary space-y-3">
      <div className="text-center">
        <div className="text-base font-semibold text-primary">Not Found</div>
        <div className="text-muted-foreground text-sm">
          The resource you are looking for does not exist.
        </div>
      </div>
      <Button size="sm" onClick={() => router.push('/')}>
        Back home
      </Button>
    </div>
  );
}
