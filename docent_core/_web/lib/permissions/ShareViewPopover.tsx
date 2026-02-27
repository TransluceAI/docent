'use client';
import { COLLECTIONS_DASHBOARD_PATH } from '@/app/constants';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
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
import { Copy, ExternalLink, Share2, User, UserPlus } from 'lucide-react';
import Link from 'next/link';
import CollaboratorsList from './CollaboratorsList';
import { useEffect, useState, useCallback } from 'react';
import {
  useGetCollaboratorsQuery,
  useGetCollectionPermissionsQuery,
  useGetMyOrganizationsQuery,
  useLazyGetUserByEmailQuery,
  useUpsertCollaboratorMutation,
  useRemoveCollaboratorMutation,
  Organization,
} from './collabSlice';
import { PERMISSION_LEVELS, PermissionLevel } from './types';
import PermissionDropdown from './PermissionDropdown';
import {
  PERMISSION_LABELS,
  PUBLIC_PERMISSION_LABELS,
  PermissionPill,
  PublicPermissionLevel,
  getInitials,
} from './permissionDisplay';
import { toast } from 'sonner';
import { useRequireUserContext } from '@/app/contexts/UserContext';
import { useHasCollectionAdminPermissionForCollection } from './hooks';

const normalizePermissionLevel = (
  permissionLevel: PermissionLevel | null | undefined
): PermissionLevel => {
  if (
    permissionLevel === 'none' ||
    permissionLevel === 'read' ||
    permissionLevel === 'write' ||
    permissionLevel === 'admin'
  ) {
    return permissionLevel;
  }
  return 'none';
};

const getMaxPermissionLevel = (
  left: PermissionLevel,
  right: PermissionLevel
): PermissionLevel =>
  PERMISSION_LEVELS[left] >= PERMISSION_LEVELS[right] ? left : right;

const normalizePublicPermissionLevel = (
  permissionLevel: PermissionLevel | null | undefined
): PublicPermissionLevel =>
  permissionLevel === 'read' || permissionLevel === 'write'
    ? permissionLevel
    : 'none';

const AddCollaborator = ({ collectionId }: { collectionId: string }) => {
  const { user } = useRequireUserContext();

  // Local state for input
  const [emailInput, setEmailInput] = useState('');
  const [inviteePermissionLevel, setInviteePermissionLevel] =
    useState<PermissionLevel>('read');

  const [upsertCollaborator] = useUpsertCollaboratorMutation();
  const [getUserByEmail] = useLazyGetUserByEmailQuery();

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
  return (
    <div className="grid grid-cols-[1fr_7rem_auto] gap-2 items-center">
      <Input
        value={emailInput}
        onChange={(e) => setEmailInput(e.target.value)}
        placeholder="Enter email address"
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
  const { user } = useRequireUserContext();

  // Get current public permission level from collaborators
  const { publicPermissionLevel, currentUserDirectPermissionLevel } =
    useGetCollaboratorsQuery(collectionId, {
      selectFromResult: (result) => {
        const publicCollab = result.data?.find(
          (c) => c.subject_type === 'public'
        );
        const currentUserCollab = result.data?.find(
          (c) => c.subject_type === 'user' && c.subject_id === user.id
        );
        return {
          publicPermissionLevel: normalizePublicPermissionLevel(
            publicCollab?.permission_level
          ),
          currentUserDirectPermissionLevel:
            currentUserCollab?.permission_level || 'none',
        };
      },
    });
  const { data: permissions } = useGetCollectionPermissionsQuery(collectionId);

  const [upsertCollaborator] = useUpsertCollaboratorMutation();
  const [removeCollaborator] = useRemoveCollaboratorMutation();

  // Handler for public permission level changes
  const handlePublicPermissionChange = useCallback(
    (newPermissionLevel: PublicPermissionLevel) => {
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
  const isReadOnlySharing = !hasAdminPermission;
  const effectivePermissionLevel = normalizePermissionLevel(
    permissions?.collection_permissions?.[collectionId]
  );
  const directPermissionLevel = normalizePermissionLevel(
    currentUserDirectPermissionLevel
  );
  const yourPermissionLevel = getMaxPermissionLevel(
    effectivePermissionLevel,
    directPermissionLevel
  );
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

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-x-2 h-7 px-2">
          <Share2 size={14} /> Share
        </Button>
      </PopoverTrigger>
      <PopoverContent className="_SharePopover w-[640px] p-3 space-y-3 rounded-lg">
        {!isReadOnlySharing && (
          <>
            {/* Section 1: Add users */}
            <div className="space-y-1">
              <h3 className="text-sm font-medium">Add users</h3>
              <AddCollaborator collectionId={collectionId} />
            </div>

            {/* Section 1b: Share with organization */}
            <div className="space-y-1">
              <h3 className="text-sm font-medium">Share with organization</h3>
              <AddOrganizationCollaborator collectionId={collectionId} />
            </div>
          </>
        )}

        {/* Section 2: Access settings */}
        {!isReadOnlySharing && <div className="border-t" />}
        <div className="flex items-center justify-between gap-3">
          <div>
            <Label htmlFor="public-access" className="text-sm font-medium">
              Public access
            </Label>
            <p className="text-xs text-muted-foreground">
              Access for anyone with the link
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
              readOnly={isReadOnlySharing}
            />
          </div>
        </div>

        {/* Section 3: Collaborators */}
        <div className="border-t" />
        <CollaboratorsList
          collectionId={collectionId}
          canManageSharing={hasAdminPermission}
          excludeSubjectId={user.id}
        />

        <div className="border-t" />
        <YourPermissionsSection
          permissionLevel={yourPermissionLevel}
          userName={user.name}
          userEmail={user.email}
        />
      </PopoverContent>
    </Popover>
  );
};

interface YourPermissionsSectionProps {
  permissionLevel: PermissionLevel;
  userName?: string;
  userEmail?: string;
}

const YourPermissionsSection = ({
  permissionLevel,
  userName,
  userEmail,
}: YourPermissionsSectionProps) => (
  <div className="space-y-1">
    <h3 className="text-sm font-medium">Your access</h3>
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <Avatar className="h-7 w-8">
          <AvatarFallback className="text-xs">
            {getInitials(userName, userEmail)}
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium truncate">
              {userName || userEmail || 'Unknown'}
            </span>
            <span className="text-[11px] text-muted-foreground">(You)</span>
          </div>
          {userEmail && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <User size={14} />
              <span className="truncate">{userEmail}</span>
            </div>
          )}
        </div>
      </div>
      <PermissionPill permissionLabel={PERMISSION_LABELS[permissionLevel]} />
    </div>
  </div>
);

// New component for public permission dropdown
interface PublicPermissionDropdownProps {
  value: PublicPermissionLevel;
  onChange: (newPermission: PublicPermissionLevel) => void;
  readOnly?: boolean;
}

const PublicPermissionDropdown = ({
  value,
  onChange,
  readOnly = false,
}: PublicPermissionDropdownProps) => {
  const publicPermissionDescriptions = {
    none: 'Only invited people can access',
    read: 'Anyone with the link can view',
    write: 'Anyone with the link can edit',
  };

  if (readOnly) {
    return <PermissionPill permissionLabel={PUBLIC_PERMISSION_LABELS[value]} />;
  }

  return (
    <Select
      value={value}
      onValueChange={(val) => onChange(val as PublicPermissionLevel)}
    >
      <SelectTrigger className="w-28 h-7 text-xs">
        <SelectValue className="text-xs font-medium">
          {PUBLIC_PERMISSION_LABELS[value]}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="none">
          <div className="flex flex-col">
            <span className="text-xs font-medium">
              {PUBLIC_PERMISSION_LABELS.none}
            </span>
            <span className="text-xs text-muted-foreground">
              {publicPermissionDescriptions.none}
            </span>
          </div>
        </SelectItem>
        <SelectItem value="read">
          <div className="flex flex-col">
            <span className="text-xs font-medium">
              {PUBLIC_PERMISSION_LABELS.read}
            </span>
            <span className="text-xs text-muted-foreground">
              {publicPermissionDescriptions.read}
            </span>
          </div>
        </SelectItem>
        <SelectItem value="write">
          <div className="flex flex-col">
            <span className="text-xs font-medium">
              {PUBLIC_PERMISSION_LABELS.write}
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
