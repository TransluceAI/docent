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
    return response.data;
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
    return response.data;
  }

  /**
   * Logout current user
   */
  static async logout(): Promise<void> {
    await apiRestClient.post('/logout');
  }
}

// Export convenience functions for easier imports
export const { login, logout, signup } = AuthService;
