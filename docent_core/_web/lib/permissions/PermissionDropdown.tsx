import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { PermissionLevel } from './types';
import {
  useHasCollectionAdminPermission,
  useHasCollectionWritePermission,
} from './hooks';

// Permission Dropdown Component
interface PermissionDropdownProps {
  value: PermissionLevel;
  onChange: (newPermission: PermissionLevel) => void;
}

const PermissionDropdown = ({ value, onChange }: PermissionDropdownProps) => {
  const hasWritePermission = useHasCollectionWritePermission();
  const hasAdminPermission = useHasCollectionAdminPermission();
  const permissionLabels = {
    none: 'No access',
    read: 'Can view',
    write: 'Can edit',
    admin: 'Full access',
  };

  const permissionDescriptions = {
    read: 'View runs and searches',
    write: 'Add/remove runs and perform searches',
    admin: 'Manage sharing and delete the collection',
  };

  return (
    <Select
      value={value}
      onValueChange={(val) => onChange(val as PermissionLevel)}
      disabled={
        !hasWritePermission || (value === 'admin' && !hasAdminPermission)
      }
    >
      <SelectTrigger className="w-28 h-7 text-xs">
        <SelectValue className="text-xs font-medium">
          {permissionLabels[value]}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="read">
          <div className="flex flex-col">
            <span className="text-xs font-medium">{permissionLabels.read}</span>
            <span className="text-xs text-muted-foreground">
              {permissionDescriptions.read}
            </span>
          </div>
        </SelectItem>
        <SelectItem value="write">
          <div className="flex flex-col">
            <span className="text-xs font-medium">
              {permissionLabels.write}
            </span>
            <span className="text-xs text-muted-foreground">
              {permissionDescriptions.write}
            </span>
          </div>
        </SelectItem>
        {hasAdminPermission && (
          <SelectItem value="admin">
            <div className="flex flex-col">
              <span className="text-xs font-medium">
                {permissionLabels.admin}
              </span>
              <span className="text-xs text-muted-foreground">
                {permissionDescriptions.admin}
              </span>
            </div>
          </SelectItem>
        )}
      </SelectContent>
    </Select>
  );
};

export default PermissionDropdown;
