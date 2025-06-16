'use client';
import { Button } from '@/components/ui/button';
import { AutoComplete } from '@/components/ui/autocomplete';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Share2, UserPlus } from 'lucide-react';
import CollaboratorsList from './CollaboratorsList';
import { useState, useMemo, useCallback } from 'react';
import {
  useGetCollaboratorsQuery,
  useGetOrgUsersQuery,
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

  const potentialUserCollaborators = useMemo(() => {
    const existingCollaborators = new Set(collaborators?.map(c => c.subject_id));
    return orgUsers?.filter((u) => u.id !== user.id && !existingCollaborators.has(u.id)) ?? [];
  }, [orgUsers, user, collaborators]);

  // Local state for autocomplete
  const [searchValue, setSearchValue] = useState('');
  const [inviteeId, setInviteeId] = useState<string | null>(null);
  const [inviteePermissionLevel, setInviteePermissionLevel] =
    useState<PermissionLevel>('read');

  const [upsertCollaborator] = useUpsertCollaboratorMutation();

  // Transform orgUsers into autocomplete items
  const userItems = useMemo(() => {
    if (!potentialUserCollaborators) return [];

    return potentialUserCollaborators.map((user) => ({
      value: user.id + ' ' + user.name + ' ' + user.email,
      label: user.name ? `${user.name} (${user.email})` : user.email,
      user,
    }));
  }, [potentialUserCollaborators]);

  // Handle autocomplete selection
  const handleUserSelect = (
    _userId: string,
    item: (typeof userItems)[number] | undefined
  ) => {
    if (item) {
      setInviteeId(item?.user.id); // Sync with existing inviteeId state for handleSendInvite
      setSearchValue(item?.label ?? '');
    }
  };
  const hasWritePermission = useHasFramegridWritePermission()
  const handleClearSelectedInvitee = () => {
    setInviteeId(null);
  };
  // Send invite to new collaborator
  const handleSendInvite = async () => {
    if (!inviteeId) return; // this is an id for now
    upsertCollaborator({
      subject_id: inviteeId,
      subject_type: 'user',
      framegrid_id: framegridId,
      permission_level: inviteePermissionLevel,
    });
  };
  if (!hasWritePermission) {
    return <div className="text-sm text-muted-foreground">You don't have permission to add or edit collaborators.</div>
  }

  return (
    <div className="flex gap-2">
      <div className="flex-1">
        <AutoComplete
          selectedValue={inviteeId ?? ''}
          onClearSelectedItem={handleClearSelectedInvitee}
          onSelectedValueChange={handleUserSelect}
          searchValue={searchValue}
          onSearchValueChange={setSearchValue}
          items={userItems}
          isLoading={isLoadingOrgUsers}
          disabled={!hasWritePermission}
          emptyMessage={
            <div className="p-3 text-center space-y-2">
              <p className="text-sm text-muted-foreground">
                No users found in your organization.
              </p>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(window.location.href);
                  toast({
                    title: 'Invite link copied to clipboard',
                    description: 'Send this link to your collaborator to join.',
                  });
                  setSearchValue('');
                }}
                className="text-xs text-primary hover:text-primary/80 underline underline-offset-2 transition-colors cursor-pointer"
              >
                Click to copy invite link
              </button>
            </div>
          }
          placeholder={hasWritePermission ? "Add collaborators by name or email" : "You don't have permission to add collaborators"}
        />
      </div>
      <PermissionDropdown
        value={inviteePermissionLevel}
        onChange={setInviteePermissionLevel}
      />
      <Button
        onClick={handleSendInvite}
        disabled={!inviteeId}
        size="sm"
        className="px-3"
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
        <Button variant="outline" size="sm" className="gap-x-2">
          <Share2 size={16} /> Share view
        </Button>
      </PopoverTrigger>
      <PopoverContent className="_SharePopover w-[640px]">
        <div className="p-4 space-y-6">
          {/* Section 1: Add collaborators */}
          <div className="space-y-3">
            <h3 className="text-md font-semibold">Add collaborators</h3>
            <AddCollaborator framegridId={framegridId} />
          </div>

          {/* Section 2: Access settings */}
          <div className="space-y-3 pt-2 border-t">
            <div className="flex items-center justify-between">
              <div className="space-y-1">
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
          </div>

          {/* Section 3: Collaborators */}
          <div className="space-y-3 pt-2 border-t">
      
            <CollaboratorsList framegridId={framegridId} />
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default ShareViewPopover;
