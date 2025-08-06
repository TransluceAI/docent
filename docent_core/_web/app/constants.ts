/**
 * BASE_URL is the public URL of the Docent API server.
 * INTERNAL_BASE_URL is the URL of the Docent API server that is used for server-side requests.
 * These are usually the same, but if the API server is inaccessible from the frontend deployment at the BASE_URL, then we need a separate INTERNAL_BASE_URL.
 * For example, this is required for the Docker Compose setup.
 */

export const BASE_URL = process.env.NEXT_PUBLIC_API_HOST;
if (!BASE_URL) {
  throw new Error('NEXT_PUBLIC_API_HOST is not set');
}
export const INTERNAL_BASE_URL =
  process.env.NEXT_PUBLIC_INTERNAL_API_HOST || BASE_URL;

export const BASE_DOCENT_PATH = '/dashboard';

export const COOKIE_KEY = 'docent_session';
