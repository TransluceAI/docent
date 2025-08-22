import { redirect } from 'next/navigation';
import { getUser } from './services/dal';

/**
 * Root Landing Page - Server Component
 *
 * Redirects users based on authentication status:
 * - Authenticated users → /dashboard (handled by route group)
 * - Unauthenticated users → /signup
 */
export default async function LandingPage() {
  const user = await getUser();

  if (user && !user.is_anonymous) {
    // User is authenticated and not anonymous, redirect to dashboard
    redirect('/dashboard');
  } else {
    // User is not authenticated, redirect to signup
    redirect('/signup');
  }
}
