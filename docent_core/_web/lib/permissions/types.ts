// TODO: change backend to return 'none' string
export const PERMISSION_LEVELS = {
  none: 0,
  read: 1,
  write: 2,
  admin: 3,
};

export type PermissionLevel = 'read' | 'write' | 'admin' | 'none';
export type SubjectType = 'user' | 'organization' | 'public';
