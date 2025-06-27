// User types matching backend models

/**
 * Frontend User type for authenticated user context
 * Maps to backend UserResponse fields
 */
export interface User {
  id: string;
  email: string;
  is_anonymous: boolean;
  name?: string;
}
