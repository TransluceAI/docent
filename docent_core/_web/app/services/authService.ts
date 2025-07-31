import { apiRestClient } from './apiService';

/**
 * Pure authentication API operations
 * No side effects (redirects, state management) - just API calls
 */
export class AuthService {
  /**
   * Login user with email and password
   */
  static async login(
    email: string,
    password: string
  ): Promise<{
    user: { id: string; email: string; is_anonymous: boolean };
    session_id: string;
  }> {
    const response = await apiRestClient.post('/login', { email, password });
    const { user, session_id } = response.data;

    // FastAPI sets a cookie in headers, but it may be running on a different domain from the Next.js app.
    // We set a cookie here too so we're authenticated with the Next.js as well as FastAPI.
    if (session_id) {
      document.cookie = `docent_session_id=${session_id}; path=/; secure; samesite=none; max-age=${30 * 24 * 60 * 60}`;
    }

    return { user, session_id };
  }

  /**
   * Signup new user with email and password
   */
  static async signup(
    email: string,
    password: string
  ): Promise<{
    user: { id: string; email: string; is_anonymous: boolean };
    session_id: string;
  }> {
    const response = await apiRestClient.post('/signup', { email, password });
    const { user, session_id } = response.data;

    if (session_id) {
      document.cookie = `docent_session_id=${session_id}; path=/; secure; samesite=none; max-age=${30 * 24 * 60 * 60}`;
    }

    return { user, session_id };
  }

  /**
   * Logout current user (API call and clear frontend cookie)
   */
  static async logout(): Promise<void> {
    await apiRestClient.post('/logout');

    // Clear frontend cookie
    document.cookie =
      'docent_session_id=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  }
}

// Export convenience functions for easier imports
export const { login, logout, signup } = AuthService;
