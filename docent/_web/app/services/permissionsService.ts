import { PermissionLevel } from '@/lib/permissions/types';
import { apiRestClient } from './apiService';
import { INTERNAL_BASE_URL } from '@/app/constants';

export class ForbiddenError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ForbiddenError';
  }
}

export class NotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NotFoundError';
  }
}

export interface UserPermissions {
  framegrid_permissions: Record<string, PermissionLevel>;
  view_permissions: Record<string, PermissionLevel>;
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
      `${INTERNAL_BASE_URL}/rest/${frameGridId}/permissions`,
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
      if (response.status === 403) {
        throw new ForbiddenError(
          `You don't have permission to access this framegrid`
        );
      } else if (response.status === 404) {
        throw new NotFoundError(`Framegrid ${frameGridId} does not exist`);
      } else {
        throw new Error(`Failed to fetch permissions: ${response.statusText}`);
      }
    }

    return response.json();
  },
};
