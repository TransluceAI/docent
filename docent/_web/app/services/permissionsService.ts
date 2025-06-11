import { apiRestClient } from './apiService';
import { BASE_URL } from '@/app/constants';

export interface UserPermissions {
  framegrid_permissions: Record<string, string | null>;
  view_permissions: Record<string, string | null>;
}

export const permissionsService = {
  async getUserPermissions(frameGridId: string): Promise<UserPermissions> {
    const response = await apiRestClient.get(`/${frameGridId}/permissions`);
    return response.data;
  },
};

// Server-side compatible permissions service
export const serverPermissionsService = {
  async getUserPermissions(
    frameGridId: string,
    cookies?: string
  ): Promise<UserPermissions> {
    const response = await fetch(
      `${BASE_URL}/rest/${frameGridId}/permissions`,
      {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          ...(cookies && { Cookie: cookies }),
        },
        credentials: 'include',
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to fetch permissions: ${response.statusText}`);
    }

    return response.json();
  },
};
