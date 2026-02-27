import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { PermissionLevel } from './types';
import { useHasCollectionAdminPermission } from './hooks';
import { PERMISSION_LABELS } from './permissionDisplay';

// Permission Dropdown Component
interface PermissionDropdownProps {
  value: PermissionLevel;
  onChange: (newPermission: PermissionLevel) => void;
  triggerClassName?: string;
}

const PermissionDropdown = ({
  value,
  onChange,
  triggerClassName,
}: PermissionDropdownProps) => {
  const hasAdminPermission = useHasCollectionAdminPermission();

  const permissionDescriptions = {
    read: 'View runs and searches',
    write: 'Add/remove runs and perform searches',
    admin: 'Manage sharing and delete the collection',
  };

  return (
    <Select
      value={value}
      onValueChange={(val) => onChange(val as PermissionLevel)}
      disabled={!hasAdminPermission}
    >
      <SelectTrigger className={cn('h-7 text-xs', triggerClassName ?? 'w-28')}>
        <SelectValue className="text-xs font-medium">
          {PERMISSION_LABELS[value]}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="read">
          <div className="flex flex-col">
            <span className="text-xs font-medium">
              {PERMISSION_LABELS.read}
            </span>
            <span className="text-xs text-muted-foreground">
              {permissionDescriptions.read}
            </span>
          </div>
        </SelectItem>
        <SelectItem value="write">
          <div className="flex flex-col">
            <span className="text-xs font-medium">
              {PERMISSION_LABELS.write}
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
                {PERMISSION_LABELS.admin}
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
