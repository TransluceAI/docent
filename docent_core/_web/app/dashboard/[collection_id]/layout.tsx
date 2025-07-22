import { cookies, headers } from 'next/headers';
import DocentDashboardClientLayout, {
  NotFoundPage,
  PermissionDeniedPage,
} from './client-layout';
import {
  ForbiddenError,
  NotFoundError,
  serverPermissionsService,
} from '../../services/permissionsService';
import { PERMISSION_LEVELS } from '@/lib/permissions/types';

export default async function DocentDashboardLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { collection_id: string };
}) {
  const collectionId = params.collection_id;

  try {
    // Check for middleware-provided cookies first, then fall back to actual cookies
    const headerStore = headers();
    const middlewareCookies = headerStore.get('x-middleware-cookies');

    let cookieString: string;
    if (middlewareCookies) {
      cookieString = middlewareCookies;
    } else {
      const cookieStore = cookies();
      cookieString = cookieStore.toString();
    }

    const permissions = await serverPermissionsService.getUserPermissions(
      collectionId,
      cookieString
    );

    // Check if user has read access to this collection
    const userLevel =
      permissions.collection_permissions[collectionId] || 'none';

    const hasReadAccess =
      PERMISSION_LEVELS[userLevel as keyof typeof PERMISSION_LEVELS] >=
      PERMISSION_LEVELS.read;

    if (!hasReadAccess) {
      // Show permission denied page
      return <PermissionDeniedPage />;
    }

    return (
      <DocentDashboardClientLayout>{children}</DocentDashboardClientLayout>
    );
  } catch (error) {
    if (error instanceof NotFoundError) {
      return <NotFoundPage />;
    } else if (error instanceof ForbiddenError) {
      return <PermissionDeniedPage />;
    }
    return <PermissionDeniedPage />;
  }
}
