'use client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
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
import { useHasFramegridWritePermission } from './hooks';

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
  // Determine current public access state from collaborators
  const { isPublicCollab } = useGetCollaboratorsQuery(framegridId, {
    selectFromResult: (result) => ({
      isPublicCollab:
        result.data?.some((c) => c.subject_type === 'public') ?? false,
    }),
  });

  const [upsertCollaborator] = useUpsertCollaboratorMutation();
  const [removeCollaborator] = useRemoveCollaboratorMutation();

  // Toggle handler that also updates backend
  const handlePublicToggle = useCallback(
    (checked: boolean) => {
      if (checked) {
        upsertCollaborator({
          subject_id: 'public',
          subject_type: 'public',
          framegrid_id: framegridId,
          permission_level: 'read', // Public access is always read-only
        });
      } else {
        removeCollaborator({
          subject_id: 'public',
          subject_type: 'public',
          framegrid_id: framegridId,
        });
      }
    },
    [framegridId, upsertCollaborator, removeCollaborator]
  );
  const hasWritePermission = useHasFramegridWritePermission();

  return (
    <Popover>
      <PopoverTrigger asChild>
        {hasWritePermission && (
          <Button
            variant="outline"
            size="sm"
            className="gap-x-2 h-7 px-2"
            disabled={!hasWritePermission}
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
              Make public
            </Label>
            <p className="text-xs text-muted-foreground">
              Anyone with the link can view
            </p>
          </div>
          <Switch
            id="public-access"
            checked={isPublicCollab}
            disabled={!hasWritePermission}
            onCheckedChange={handlePublicToggle}
          />
        </div>

        {/* Section 3: Collaborators */}
        <div className="border-t" />
        <CollaboratorsList framegridId={framegridId} />
      </PopoverContent>
    </Popover>
  );
};

export default ShareViewPopover;
