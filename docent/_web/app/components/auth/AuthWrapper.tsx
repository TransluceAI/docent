'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { Loader2 } from 'lucide-react';

import { useUser } from '../../contexts/UserContext';

interface AuthWrapperProps {
  children: React.ReactNode;
}

const publicRoutes = ['/login', '/signup'];

export const AuthWrapper = ({ children }: AuthWrapperProps) => {
  const { user, loading } = useUser();
  const pathname = usePathname();
  const router = useRouter();

  const isPublic = publicRoutes.includes(pathname);
  const isAuthenticated = !!user;

  // Handle route redirections
  useEffect(() => {
    if (loading) return;

    if (isAuthenticated && isPublic) {
      router.replace('/');
    } else if (!isAuthenticated && !isPublic) {
      router.replace('/login');
    }
  }, [loading, isAuthenticated, isPublic, router]);

  const isRedirectingToHome = isAuthenticated && isPublic;
  const isRedirectingToLogin = !isAuthenticated && !isPublic;
  // While determining auth state or redirecting, show spinner
  const shouldShowLoader =
    loading || isRedirectingToHome || isRedirectingToLogin;

  if (shouldShowLoader) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }
  // If current route is public and user is not authenticated, render children
  if (publicRoutes.includes(pathname)) {
    return <>{children}</>;
  }

  // User is authenticated, render the protected content
  return <>{children}</>;
};
