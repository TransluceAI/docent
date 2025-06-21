import { cookies, headers } from 'next/headers';
import DocentDashboardClientLayout from './client-layout';
import { serverPermissionsService } from '../../services/permissionsService';
import { PERMISSION_LEVELS } from '@/lib/permissions/types';

export default async function DocentDashboardLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { fg_id: string };
}) {
  const fgId = params.fg_id;

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
      fgId,
      cookieString
    );

    // Check if user has read access to this framegrid
    const userLevel = permissions.framegrid_permissions[fgId] || 'none';

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
    console.error('Failed to fetch permissions:', error);
    return <PermissionDeniedPage />;
  }
}

function PermissionDeniedPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="text-base font-semibold text-gray-900 mb-2">
          Access Denied
        </h1>
        <p className="text-gray-600 text-sm">
          You don&apos;t have permission to view this resource
        </p>
      </div>
    </div>
  );
}
