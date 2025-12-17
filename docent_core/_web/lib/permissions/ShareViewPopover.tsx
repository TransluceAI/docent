'use client';
import { COLLECTIONS_DASHBOARD_PATH } from '@/app/constants';
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { copyToClipboard } from '@/lib/utils';
import { Copy, Share2, UserPlus, ExternalLink } from 'lucide-react';
import Link from 'next/link';
import CollaboratorsList from './CollaboratorsList';
import { useEffect, useState, useCallback } from 'react';
import {
  useGetCollaboratorsQuery,
  useGetMyOrganizationsQuery,
  useLazyGetUserByEmailQuery,
  useUpsertCollaboratorMutation,
  useRemoveCollaboratorMutation,
  Organization,
} from './collabSlice';
import { PermissionLevel } from './types';
import PermissionDropdown from './PermissionDropdown';
import { toast } from 'sonner';
import { useRequireUserContext } from '@/app/contexts/UserContext';
import {
  useHasCollectionAdminPermissionForCollection,
  useHasCollectionWritePermissionForCollection,
} from './hooks';

const AddCollaborator = ({ collectionId }: { collectionId: string }) => {
  const { user } = useRequireUserContext();

  // Local state for input
  const [emailInput, setEmailInput] = useState('');
  const [inviteePermissionLevel, setInviteePermissionLevel] =
    useState<PermissionLevel>('read');

  const [upsertCollaborator] = useUpsertCollaboratorMutation();
  const [getUserByEmail] = useLazyGetUserByEmailQuery();

  const hasAdminPermission =
    useHasCollectionAdminPermissionForCollection(collectionId);

  // Send invite to new collaborator
  const handleSendInvite = async () => {
    if (!emailInput.trim()) return;

    try {
      // First, get the user by email using RTK Query
      const result = await getUserByEmail(emailInput.trim());

      if (result.error) {
        toast.error('Failed to look up user. Please try again.');
        return;
      }

      const newUser = result.data;
      if (!newUser) {
        toast.error(`No user found with email address: ${emailInput.trim()}`);
        return;
      }
      if (newUser.id === user.id) {
        toast.error('You cannot invite yourself.');
        return;
      }

      // Use the user's ID as the subject_id
      await upsertCollaborator({
        subject_id: newUser.id,
        subject_type: 'user',
        collection_id: collectionId,
        permission_level: inviteePermissionLevel,
      }).unwrap();

      setEmailInput('');
    } catch (error) {
      toast.error('Failed to invite user. Please try again.');
    }
  };
  if (!hasAdminPermission) {
    return (
      <div className="text-sm text-muted-foreground">
        You do not have permission to manage sharing for this collection.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[1fr_7rem_auto] gap-2 items-center">
      <Input
        value={emailInput}
        onChange={(e) => setEmailInput(e.target.value)}
        disabled={!hasAdminPermission}
        placeholder={
          hasAdminPermission
            ? 'Enter email address'
            : "You don't have permission to manage sharing"
        }
        className="h-7 text-xs w-full"
      />
      <PermissionDropdown
        value={inviteePermissionLevel}
        onChange={setInviteePermissionLevel}
        triggerClassName="w-full"
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

const AddOrganizationCollaborator = ({
  collectionId,
}: {
  collectionId: string;
}) => {
  const { data: organizations, isLoading } = useGetMyOrganizationsQuery();
  const [selectedOrgId, setSelectedOrgId] = useState<string>('');
  const [permissionLevel, setPermissionLevel] =
    useState<PermissionLevel>('read');
  const [upsertCollaborator] = useUpsertCollaboratorMutation();
  const hasAdminPermission =
    useHasCollectionAdminPermissionForCollection(collectionId);

  useEffect(() => {
    if (!selectedOrgId && organizations?.length === 1) {
      setSelectedOrgId(organizations[0].id);
    }
  }, [organizations, selectedOrgId]);

  const selectedOrg: Organization | undefined = organizations?.find(
    (o) => o.id === selectedOrgId
  );

  const handleAddOrganization = async () => {
    if (!selectedOrgId) return;
    try {
      await upsertCollaborator({
        subject_id: selectedOrgId,
        subject_type: 'organization',
        collection_id: collectionId,
        permission_level: permissionLevel,
      }).unwrap();
      toast.success(
        selectedOrg?.name
          ? `Shared with ${selectedOrg.name}`
          : 'Shared with organization'
      );
      setSelectedOrgId('');
      setPermissionLevel('read');
    } catch {
      toast.error('Failed to share with organization. Please try again.');
    }
  };

  if (isLoading) {
    return (
      <div className="text-sm text-muted-foreground">
        Loading organizations…
      </div>
    );
  }

  if (!hasAdminPermission) {
    return (
      <div className="text-sm text-muted-foreground">
        You do not have permission to manage sharing for this collection.
      </div>
    );
  }

  if (!organizations?.length) {
    return (
      <div className="text-xs text-muted-foreground">
        You don&apos;t belong to any organizations.{' '}
        <Link
          href="/settings/organizations"
          className="text-primary underline underline-offset-2 hover:text-primary/80 inline-flex items-center gap-0.5"
        >
          Create one
          <ExternalLink size={10} />
        </Link>{' '}
        or ask an admin to add you.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[1fr_7rem_auto] gap-2 items-center">
      <Select
        value={selectedOrgId}
        onValueChange={(val) => setSelectedOrgId(val)}
      >
        <SelectTrigger className="h-7 text-xs w-full">
          <SelectValue placeholder="Select organization" />
        </SelectTrigger>
        <SelectContent>
          {organizations.map((org) => (
            <SelectItem key={org.id} value={org.id}>
              <div className="flex flex-col">
                <span className="text-xs font-medium">{org.name}</span>
                {org.description ? (
                  <span className="text-xs text-muted-foreground">
                    {org.description}
                  </span>
                ) : null}
              </div>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <PermissionDropdown
        value={permissionLevel}
        onChange={setPermissionLevel}
        triggerClassName="w-full"
      />
      <Button
        onClick={handleAddOrganization}
        disabled={!selectedOrgId}
        size="sm"
        className="h-7"
      >
        <UserPlus size={16} className="mr-1" />
        Invite
      </Button>
    </div>
  );
};

const ShareViewPopover = ({ collectionId }: { collectionId: string }) => {
  // Get current public permission level from collaborators
  const { publicPermissionLevel } = useGetCollaboratorsQuery(collectionId, {
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
          collection_id: collectionId,
        });
      } else {
        // Set or update public access
        upsertCollaborator({
          subject_id: 'public',
          subject_type: 'public',
          collection_id: collectionId,
          permission_level: newPermissionLevel,
        });
      }
    },
    [collectionId, upsertCollaborator, removeCollaborator]
  );

  const hasAdminPermission =
    useHasCollectionAdminPermissionForCollection(collectionId);
  const hasWritePermission =
    useHasCollectionWritePermissionForCollection(collectionId);
  const accessButtonLabel = hasWritePermission ? 'Read-write' : 'Read-only';
  const handleCopyCollectionLink = useCallback(async () => {
    try {
      if (typeof window === 'undefined') {
        throw new Error('Window is undefined');
      }
      const shareUrl = `${window.location.origin}${COLLECTIONS_DASHBOARD_PATH}/${collectionId}`;
      const didCopy = await copyToClipboard(shareUrl);
      if (!didCopy) {
        throw new Error('Copy command failed');
      }
      toast.success('Collection link copied to clipboard');
    } catch (error) {
      console.error('Failed to copy collection link:', error);
      toast.error('Failed to copy link to clipboard');
    }
  }, [collectionId]);

  if (!hasAdminPermission) {
    return (
      <Button variant="outline" size="sm" className="gap-x-2 h-7 px-2" disabled>
        <Share2 size={14} /> {accessButtonLabel}
      </Button>
    );
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-x-2 h-7 px-2">
          <Share2 size={14} /> Share
        </Button>
      </PopoverTrigger>
      <PopoverContent className="_SharePopover w-[640px] p-3 space-y-3 rounded-lg">
        {/* Section 1: Add collaborators */}
        <div className="space-y-1">
          <h3 className="text-sm font-medium">Add collaborators</h3>
          <AddCollaborator collectionId={collectionId} />
        </div>

        {/* Section 1b: Share with organization */}
        <div className="space-y-1">
          <h3 className="text-sm font-medium">Share with organization</h3>
          <AddOrganizationCollaborator collectionId={collectionId} />
        </div>

        {/* Section 2: Access settings */}
        <div className="border-t" />
        <div className="flex items-center justify-between gap-3">
          <div>
            <Label htmlFor="public-access" className="text-sm font-medium">
              Public access
            </Label>
            <p className="text-xs text-muted-foreground">
              Anyone with the link can access
            </p>
          </div>
          <div className="flex items-center gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-muted-foreground"
                  onClick={handleCopyCollectionLink}
                  aria-label="Copy collection link"
                >
                  <Copy size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                Click to copy the collection URL
              </TooltipContent>
            </Tooltip>
            <PublicPermissionDropdown
              value={publicPermissionLevel}
              onChange={handlePublicPermissionChange}
              disabled={!hasAdminPermission}
            />
          </div>
        </div>

        {/* Section 3: Collaborators */}
        <div className="border-t" />
        <CollaboratorsList collectionId={collectionId} />
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
