import { User } from '@/app/types/userTypes';
import { cookies, headers } from 'next/headers';
import { COOKIE_KEY, INTERNAL_BASE_URL } from '../constants';

/**
 * Verifies the session with the backend
 * Returns the user and sessionId if valid, otherwise returns null
 */
export async function getUser(): Promise<User | null> {
  // First, check if middleware provided user data via headers
  const headerStore = await headers();
  const middlewareUser = headerStore.get('x-middleware-user');
  if (middlewareUser) {
    try {
      return JSON.parse(middlewareUser);
    } catch (error) {
      console.error('Failed to parse middleware user data:', error);
    }
  }

  // Fallback to normal cookie-based authentication
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get(COOKIE_KEY);

  if (!sessionCookie?.value) {
    return null;
  }

  const response = await fetch(`${INTERNAL_BASE_URL}/rest/me`, {
    headers: {
      Cookie: `${COOKIE_KEY}=${sessionCookie.value}`,
      'Content-Type': 'application/json',
    },
    cache: 'no-store', // Always get fresh auth data
    // Add timeout to prevent hanging requests
    signal: AbortSignal.timeout(5000), // 5 second timeout
  });
  if (!response.ok) {
    return null;
  }

  const user = await response.json();
  return user;
}
