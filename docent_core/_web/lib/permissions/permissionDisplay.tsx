import { PermissionLevel } from './types';

export type PublicPermissionLevel = 'none' | 'read' | 'write';

export const PERMISSION_LABELS: Record<PermissionLevel, string> = {
  none: 'No access',
  read: 'Can view',
  write: 'Can edit',
  admin: 'Full access',
};

export const PUBLIC_PERMISSION_LABELS: Record<PublicPermissionLevel, string> = {
  none: 'No access',
  read: 'Can view',
  write: 'Can edit',
};

export const getInitials = (name?: string, email?: string) => {
  if (name) {
    return name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  }
  if (email) {
    return email.slice(0, 2).toUpperCase();
  }
  return '??';
};

interface PermissionPillProps {
  permissionLabel: string;
}

export const PermissionPill = ({ permissionLabel }: PermissionPillProps) => (
  <span className="inline-flex h-7 items-center rounded-md border border-border bg-secondary px-2 text-xs font-medium text-primary">
    {permissionLabel}
  </span>
);
