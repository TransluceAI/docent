// const useHasCollectionPermission = (collectionId: string, required)

import { PERMISSION_LEVELS, PermissionLevel } from '@/lib/permissions/types';
import { useGetCollectionPermissionsQuery } from './collabSlice';
import { useAppSelector } from '@/app/store/hooks';
import { UserPermissions } from '@/app/services/permissionsService';

const hasCollectionPermission = (
  permissions: UserPermissions,
  collectionId: string,
  requiredLevel: PermissionLevel
) => {
  if (!permissions?.collection_permissions) return false;
  const userLevel = permissions.collection_permissions[collectionId] || 'none';
  return PERMISSION_LEVELS[userLevel] >= PERMISSION_LEVELS[requiredLevel];
};

export const useHasCollectionPermission = (
  permission: PermissionLevel,
  collectionIdParam?: string
) => {
  const collectionId =
    useAppSelector((state) => state.collection.collectionId) ||
    collectionIdParam;
  const { data: permissions } = useGetCollectionPermissionsQuery(
    collectionId || '',
    { skip: !collectionId }
  );
  if (!permissions || !collectionId) return false;
  return hasCollectionPermission(permissions, collectionId, permission);
};

export const useHasCollectionWritePermission = () => {
  return useHasCollectionPermission('write');
};

export const useHasCollectionAdminPermission = () => {
  return useHasCollectionPermission('admin');
};
