'use client';

import {
  redirect,
  useParams,
  usePathname,
  useRouter,
  useSearchParams,
} from 'next/navigation';
import React, { useEffect, Suspense } from 'react';
import { SidebarProvider } from '@/components/ui/sidebar';

import CollectionBreadcrumbs from '../../components/Breadcrumbs';
import { setCollectionId } from '../../store/collectionSlice';
import { useAppDispatch } from '../../store/hooks';
import { useGetCollectionNameQuery } from '../../api/collectionApi';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/button';
import { useUserContext } from '@/app/contexts/UserContext';
import { LabelSetsProvider } from '@/providers/use-label-sets';
import { CollectionSidebar } from '@/components/CollectionSidebar';
import { CitationNavigationProvider } from '@/providers/CitationNavigationProvider';

function getSectionTitle(
  pathname: string,
  collectionId: string
): string | null {
  const prefix = `/dashboard/${collectionId}/`;
  if (!pathname.startsWith(prefix)) return null;

  const subpath = pathname.slice(prefix.length).split('/')[0];
  const sectionMap: Record<string, string> = {
    rubric: 'Rubrics',
    labels: 'Label Sets',
    jobs: 'Jobs',
    chat: 'Chat',
    charts: 'Charts',
    agent_run: 'Agent Run',
  };
  return sectionMap[subpath] || null;
}

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

  // Fetch collection name for page title
  const { data: collectionData } = useGetCollectionNameQuery(collectionId);
  const pathname = usePathname();
  const sectionTitle = getSectionTitle(pathname, collectionId);
  const collectionName = collectionData?.name || collectionId;
  const pageTitle = sectionTitle
    ? `${collectionName} | ${sectionTitle}`
    : `${collectionName} | Docent`;

  // Set the collection ID in the store
  useEffect(() => {
    if (collectionId) {
      dispatch(setCollectionId(collectionId));
    }
  }, [collectionId, dispatch]);

  return (
    <SidebarProvider defaultOpen={false}>
      <PageTitle title={pageTitle} />
      <LabelSetsProvider collectionId={collectionId}>
        <CitationNavigationProvider>
          <CollectionSidebar />
          <div className="flex flex-col pr-2 pb-2 h-screen w-full bg-sidebar min-h-0 min-w-[900px]">
            <div className="items-center flex flex-shrink-0 my-2">
              <Suspense
                fallback={<div className="h-7">Loading breadcrumbs...</div>}
              >
                <CollectionBreadcrumbs />
              </Suspense>
            </div>
            {children}
          </div>
        </CitationNavigationProvider>
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
        <div className="text-xl font-semibold text-primary">Access Denied</div>
        <div className="text-muted-foreground text-md">
          You don&apos;t have permission to view this resource
        </div>
      </div>
      <Button size="default" onClick={handleLoginRedirect}>
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
        <div className="text-xl font-semibold text-primary">Not Found</div>
        <div className="text-muted-foreground text-md">
          The resource you are looking for does not exist.
        </div>
      </div>
      <Button size="default" onClick={() => router.push('/')}>
        Back home
      </Button>
    </div>
  );
}
