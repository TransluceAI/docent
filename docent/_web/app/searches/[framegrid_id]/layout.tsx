import { requireAuth } from '../../lib/dal';

/**
 * Authenticated Layout - wraps all pages that require authentication
 *
 * This layout:
 * 1. Performs server-side auth check and redirects to /login if needed
 * 2. Ensures user data is available via the main UserProvider
 * 3. Can include authenticated-specific UI elements (nav, user menu, etc.)
 */
export default async function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  // This will redirect to /login if not authenticated
  // The user data is already available via the root UserProvider
  await requireAuth();

  return <>{children}</>;
}
