import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { PermissionLevel } from "./types"
import { cn } from "@/lib/utils"


// Permission Dropdown Component
interface PermissionDropdownProps {
    value: PermissionLevel;
    onChange: (newPermission: PermissionLevel) => void;
    disabled?: boolean;
  }
  
  const PermissionDropdown = ({ value, onChange, disabled }: PermissionDropdownProps) => {
    const permissionLabels = {
      none: "No access",
      read: "Can view",
      write: "Can edit", 
      admin: "Full access"
    };

    const permissionDescriptions = {
      read: "View transcripts, runs, search, and filter",
      write: "Add transcripts and manage sharing",
      admin: "Administrative access"
    };
  
    return (
      <Select value={value} onValueChange={(val) => onChange(val as PermissionLevel)} disabled={disabled}>
        <SelectTrigger className="w-32">
          <SelectValue>
            <span className="text-xs font-medium">{permissionLabels[value]}</span>
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="read">
            <div className="flex flex-col">
              <span className="text-xs font-medium">{permissionLabels.read}</span>
              <span className="text-xs text-muted-foreground">{permissionDescriptions.read}</span>
            </div>
          </SelectItem>
          <SelectItem value="write">
            <div className="flex flex-col">
              <span className="text-xs font-medium">{permissionLabels.write}</span>
              <span className="text-xs text-muted-foreground">{permissionDescriptions.write}</span>
            </div>
          </SelectItem>
          <SelectItem value="admin">
            <div className="flex flex-col">
              <span className="text-xs font-medium">{permissionLabels.admin}</span>
              <span className="text-xs text-muted-foreground">{permissionDescriptions.admin}</span>
            </div>
          </SelectItem>
        </SelectContent>
      </Select>
    );
  };

export default PermissionDropdown;