'use client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Share2, UserPlus } from 'lucide-react';
import CollaboratorsList from './CollaboratorsList';
import { useState, useCallback } from 'react';
import {
  useGetCollaboratorsQuery,
  useGetOrgUsersQuery,
  useLazyGetUserByEmailQuery,
  useUpsertCollaboratorMutation,
  useRemoveCollaboratorMutation,
} from './collabSlice';
import { PermissionLevel } from './types';
import PermissionDropdown from './PermissionDropdown';
import { toast } from '@/hooks/use-toast';
import { useRequireUserContext } from '@/app/contexts/UserContext';
import {
  useHasFramegridAdminPermission,
  useHasFramegridWritePermission,
} from './hooks';

const AddCollaborator = ({ framegridId }: { framegridId: string }) => {
  const { data: orgUsers, isLoading: isLoadingOrgUsers } =
    useGetOrgUsersQuery(framegridId);
  const { data: collaborators } = useGetCollaboratorsQuery(framegridId);
  const { user } = useRequireUserContext();

  // Local state for input
  const [emailInput, setEmailInput] = useState('');
  const [inviteePermissionLevel, setInviteePermissionLevel] =
    useState<PermissionLevel>('read');

  const [upsertCollaborator] = useUpsertCollaboratorMutation();
  const [getUserByEmail] = useLazyGetUserByEmailQuery();

  const hasWritePermission = useHasFramegridWritePermission();

  // Send invite to new collaborator
  const handleSendInvite = async () => {
    if (!emailInput.trim()) return;

    try {
      // First, get the user by email using RTK Query
      const result = await getUserByEmail(emailInput.trim());

      if (result.error) {
        toast({
          title: 'Error',
          description: 'Failed to look up user. Please try again.',
          variant: 'destructive',
        });
        return;
      }

      const newUser = result.data;
      if (!newUser) {
        toast({
          title: 'User not found',
          description: `No user found with email address: ${emailInput.trim()}`,
          variant: 'destructive',
        });
        return;
      }
      if (newUser.id === user.id) {
        toast({
          title: 'Error',
          description: 'You cannot invite yourself.',
          variant: 'destructive',
        });
        return;
      }

      // Use the user's ID as the subject_id
      await upsertCollaborator({
        subject_id: newUser.id,
        subject_type: 'user',
        framegrid_id: framegridId,
        permission_level: inviteePermissionLevel,
      }).unwrap();

      setEmailInput('');
    } catch (error) {
      toast({
        title: 'Error',
        description: 'Failed to invite user. Please try again.',
        variant: 'destructive',
      });
    }
  };
  if (!hasWritePermission) {
    return (
      <div className="text-sm text-muted-foreground">
        You do not have permission to add or edit collaborators.
      </div>
    );
  }

  return (
    <div className="flex gap-2 items-center">
      <Input
        value={emailInput}
        onChange={(e) => setEmailInput(e.target.value)}
        disabled={!hasWritePermission}
        placeholder={
          hasWritePermission
            ? 'Enter email address'
            : "You don't have permission to add collaborators"
        }
        className="h-7 text-xs"
      />
      <PermissionDropdown
        value={inviteePermissionLevel}
        onChange={setInviteePermissionLevel}
      />
      <Button
        onClick={handleSendInvite}
        disabled={!emailInput.trim()}
        size="sm"
        className="h-7"
      >
        <UserPlus size={16} className="mr-1" />
        Invite
      </Button>
    </div>
  );
};

const ShareViewPopover = ({ framegridId }: { framegridId: string }) => {
  // Get current public permission level from collaborators
  const { publicPermissionLevel } = useGetCollaboratorsQuery(framegridId, {
    selectFromResult: (result) => {
      const publicCollab = result.data?.find(
        (c) => c.subject_type === 'public'
      );
      return {
        publicPermissionLevel: publicCollab?.permission_level || 'none',
      };
    },
  });

  const [upsertCollaborator] = useUpsertCollaboratorMutation();
  const [removeCollaborator] = useRemoveCollaboratorMutation();

  // Handler for public permission level changes
  const handlePublicPermissionChange = useCallback(
    (newPermissionLevel: PermissionLevel) => {
      if (newPermissionLevel === 'none') {
        // Remove public access
        removeCollaborator({
          subject_id: 'public',
          subject_type: 'public',
          framegrid_id: framegridId,
        });
      } else {
        // Set or update public access
        upsertCollaborator({
          subject_id: 'public',
          subject_type: 'public',
          framegrid_id: framegridId,
          permission_level: newPermissionLevel,
        });
      }
    },
    [framegridId, upsertCollaborator, removeCollaborator]
  );

  const hasAdminPermission = useHasFramegridAdminPermission();

  return (
    <Popover>
      <PopoverTrigger asChild>
        {hasAdminPermission && (
          <Button
            variant="outline"
            size="sm"
            className="gap-x-2 h-7 px-2"
            disabled={!hasAdminPermission}
          >
            <Share2 size={14} /> Share view
          </Button>
        )}
      </PopoverTrigger>
      <PopoverContent className="_SharePopover w-[640px] p-3 space-y-3 rounded-lg">
        {/* Section 1: Add collaborators */}
        <div className="space-y-1">
          <h3 className="text-sm font-medium">Add collaborators</h3>
          <AddCollaborator framegridId={framegridId} />
        </div>

        {/* Section 2: Access settings */}
        <div className="border-t" />
        <div className="flex items-center justify-between">
          <div>
            <Label htmlFor="public-access" className="text-sm font-medium">
              Public access
            </Label>
            <p className="text-xs text-muted-foreground">
              Anyone with the link can access
            </p>
          </div>
          <PublicPermissionDropdown
            value={publicPermissionLevel}
            onChange={handlePublicPermissionChange}
            disabled={!hasAdminPermission}
          />
        </div>

        {/* Section 3: Collaborators */}
        <div className="border-t" />
        <CollaboratorsList framegridId={framegridId} />
      </PopoverContent>
    </Popover>
  );
};

// New component for public permission dropdown
interface PublicPermissionDropdownProps {
  value: PermissionLevel;
  onChange: (newPermission: PermissionLevel) => void;
  disabled?: boolean;
}

const PublicPermissionDropdown = ({
  value,
  onChange,
  disabled = false,
}: PublicPermissionDropdownProps) => {
  const publicPermissionLabels = {
    none: 'No access',
    read: 'Can view',
    write: 'Can edit',
  };

  const publicPermissionDescriptions = {
    none: 'Only invited people can access',
    read: 'Anyone with the link can view',
    write: 'Anyone with the link can edit',
  };

  return (
    <Select
      value={value}
      onValueChange={(val) => onChange(val as PermissionLevel)}
      disabled={disabled}
    >
      <SelectTrigger className="w-28 h-7 text-xs">
        <SelectValue className="text-xs font-medium">
          {publicPermissionLabels[
            value as keyof typeof publicPermissionLabels
          ] || publicPermissionLabels.none}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="none">
          <div className="flex flex-col">
            <span className="text-xs font-medium">
              {publicPermissionLabels.none}
            </span>
            <span className="text-xs text-muted-foreground">
              {publicPermissionDescriptions.none}
            </span>
          </div>
        </SelectItem>
        <SelectItem value="read">
          <div className="flex flex-col">
            <span className="text-xs font-medium">
              {publicPermissionLabels.read}
            </span>
            <span className="text-xs text-muted-foreground">
              {publicPermissionDescriptions.read}
            </span>
          </div>
        </SelectItem>
        <SelectItem value="write">
          <div className="flex flex-col">
            <span className="text-xs font-medium">
              {publicPermissionLabels.write}
            </span>
            <span className="text-xs text-muted-foreground">
              {publicPermissionDescriptions.write}
            </span>
          </div>
        </SelectItem>
      </SelectContent>
    </Select>
  );
};

export default ShareViewPopover;
