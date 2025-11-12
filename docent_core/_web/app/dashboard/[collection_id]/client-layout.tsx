'use client';

import {
  redirect,
  useParams,
  useRouter,
  useSearchParams,
} from 'next/navigation';
import React, { useEffect, Suspense } from 'react';
import { SidebarProvider } from '@/components/ui/sidebar';

import CollectionBreadcrumbs from '../../components/Breadcrumbs';
import { setCollectionId } from '../../store/collectionSlice';
import { useAppDispatch } from '../../store/hooks';
import { Button } from '@/components/ui/button';
import { useUserContext } from '@/app/contexts/UserContext';
import { LabelSetsProvider } from '@/providers/use-label-sets';
import { CollectionSidebar } from '@/components/CollectionSidebar';

export default function DocentDashboardClientLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const dispatch = useAppDispatch();
  const params = useParams();
  const collectionId = params.collection_id as string;

  const searchParams = useSearchParams();
  const rubricId =
    searchParams.get('rubricId') || searchParams.get('activeRubricId');
  if (rubricId) {
    redirect(`/dashboard/${collectionId}/rubric/${rubricId}`);
  }

  // Set the collection ID in the store
  useEffect(() => {
    if (collectionId) {
      dispatch(setCollectionId(collectionId));
    }
  }, [collectionId, dispatch]);

  return (
    <SidebarProvider defaultOpen={false}>
      <LabelSetsProvider collectionId={collectionId}>
        <CollectionSidebar />
        <div className="flex flex-col pr-3 h-screen w-full bg-sidebar min-h-0 min-w-[900px]">
          <div className="items-center justify-center flex flex-shrink-0 my-2">
            <Suspense
              fallback={<div className="h-7">Loading breadcrumbs...</div>}
            >
              <CollectionBreadcrumbs />
            </Suspense>
          </div>
          {children}
        </div>
      </LabelSetsProvider>
    </SidebarProvider>
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
