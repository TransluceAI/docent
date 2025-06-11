'use client';

import {
  createContext,
  useContext,
  ReactNode,
  useMemo,
  useCallback,
} from 'react';
import { UserPermissions } from '../services/permissionsService';

interface PermissionsContextType {
  permissions: UserPermissions | null;
  hasFramegridPermission: (
    frameGridId: string,
    requiredLevel: 'read' | 'write' | 'admin'
  ) => boolean;
  hasViewPermission: (
    viewId: string,
    requiredLevel: 'read' | 'write' | 'admin'
  ) => boolean;
  frameGridId: string;
}

const PermissionsContext = createContext<PermissionsContextType | undefined>(
  undefined
);

interface PermissionsProviderProps {
  children: ReactNode;
  frameGridId: string;
  permissions: UserPermissions | null;
}

const PERMISSION_LEVELS = {
  none: 0,
  read: 1,
  write: 2,
  admin: 3,
};

export const PermissionsProvider = ({
  children,
  frameGridId,
  permissions,
}: PermissionsProviderProps) => {
  const hasFramegridPermission = useCallback(
    (
      frameGridId: string,
      requiredLevel: 'read' | 'write' | 'admin'
    ): boolean => {
      if (!permissions?.framegrid_permissions) return false;

      const userLevel =
        permissions.framegrid_permissions[frameGridId] || 'none';
      return (
        PERMISSION_LEVELS[userLevel as keyof typeof PERMISSION_LEVELS] >=
        PERMISSION_LEVELS[requiredLevel]
      );
    },
    [permissions]
  );

  const hasViewPermission = useCallback(
    (viewId: string, requiredLevel: 'read' | 'write' | 'admin'): boolean => {
      if (!permissions?.view_permissions) return false;

      const userLevel = permissions.view_permissions[viewId] || 'none';
      return (
        PERMISSION_LEVELS[userLevel as keyof typeof PERMISSION_LEVELS] >=
        PERMISSION_LEVELS[requiredLevel]
      );
    },
    [permissions]
  );

  const contextValue = useMemo(
    () => ({
      permissions,
      hasFramegridPermission,
      hasViewPermission,
      frameGridId,
    }),
    [permissions, hasFramegridPermission, hasViewPermission, frameGridId]
  );

  return (
    <PermissionsContext.Provider value={contextValue}>
      {children}
    </PermissionsContext.Provider>
  );
};

export const usePermissions = () => {
  const context = useContext(PermissionsContext);
  if (context === undefined) {
    throw new Error('usePermissions must be used within a PermissionsProvider');
  }
  return context;
};
