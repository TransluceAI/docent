// User types matching backend models

/**
 * Frontend User type for authenticated user context
 * Maps to backend UserResponse fields
 */
export interface User {
  user_id: string;
  email: string;
  is_anonymous: boolean;
}

/**
 * Request payload for creating a new user
 * Matches backend UserCreateRequest
 */
export interface UserCreateRequest {
  email: string;
}

/**
 * Response from user-related API endpoints
 * Matches backend UserResponse
 */
export interface UserResponse {
  user_id: string;
  email: string;
}
