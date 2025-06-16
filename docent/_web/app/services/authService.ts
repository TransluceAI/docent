import { apiRestClient } from './apiService';

/**
 * Pure authentication API operations
 * No side effects (redirects, state management) - just API calls
 */
export class AuthService {
  /**
   * Login user with email
   */
  static async login(
    email: string
  ): Promise<{ id: string; email: string; is_anonymous: boolean }> {
    const response = await apiRestClient.post('/login', { email });
    return response.data;
  }

  /**
   * Signup new user with email
   */
  static async signup(
    email: string
  ): Promise<{ id: string; email: string; is_anonymous: boolean }> {
    const response = await apiRestClient.post('/signup', { email });
    return response.data;
  }

  /**
   * Logout current user (API call only)
   */
  static async logout(): Promise<void> {
    await apiRestClient.post('/logout');
  }

  /**
   * Get current user data (client-side)
   * Use sparingly - prefer server-side auth via DAL
   */
  static async getCurrentUser(): Promise<{
    id: string;
    email: string;
    is_anonymous: boolean;
  } | null> {
    try {
      const response = await apiRestClient.get('/me');
      return response.data;
    } catch (error: any) {
      if (error.response?.status === 401) {
        return null; // User not authenticated
      }
      throw error;
    }
  }
}

// Export convenience functions for easier imports
export const { login, logout, signup, getCurrentUser } = AuthService;
