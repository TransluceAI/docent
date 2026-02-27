import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Building, Globe, User, X } from 'lucide-react';
import PermissionDropdown from './PermissionDropdown';
import {
  OrganizationCollaborator,
  UserCollaborator,
  useGetCollaboratorsQuery,
  useRemoveCollaboratorMutation,
  useUpsertCollaboratorMutation,
} from './collabSlice';
import {
  PERMISSION_LABELS,
  PermissionPill,
  getInitials,
} from './permissionDisplay';
import { PermissionLevel, SubjectType } from './types';

const getDisplayName = (
  collaborator: UserCollaborator | OrganizationCollaborator
) => {
  if (collaborator.subject_type === 'user') {
    return collaborator.subject.name || collaborator.subject.email || 'Unknown';
  }
  return collaborator.subject.name || 'Unknown';
};

const getSubjectIcon = (subjectType: SubjectType) => {
  switch (subjectType) {
    case 'user':
      return <User size={14} />;
    case 'organization':
      return <Building size={14} />;
    case 'public':
      return <Globe size={14} />;
    default:
      return <User size={14} />;
  }
};

interface CollaboratorRowProps {
  collaborator: UserCollaborator | OrganizationCollaborator;
  canManageSharing: boolean;
}

const CollaboratorRow = ({
  collaborator,
  canManageSharing,
}: CollaboratorRowProps) => {
  const [upsertCollaborator] = useUpsertCollaboratorMutation();
  const [removeCollaborator] = useRemoveCollaboratorMutation();

  const isReadOnlyRow = !canManageSharing;
  const displayName = getDisplayName(collaborator);
  const displayEmail =
    collaborator.subject_type === 'user'
      ? collaborator.subject.email
      : undefined;

  const onPermissionChange = (newPermission: PermissionLevel) => {
    if (isReadOnlyRow) return;
    upsertCollaborator({
      subject_id: collaborator.subject_id,
      subject_type: collaborator.subject_type,
      collection_id: collaborator.collection_id,
      permission_level: newPermission,
    });
  };

  const onRemove = () => {
    if (isReadOnlyRow) return;
    removeCollaborator({
      subject_id: collaborator.subject_id,
      subject_type: collaborator.subject_type,
      collection_id: collaborator.collection_id,
    });
  };

  return (
    <div className={cn('flex items-center justify-between')}>
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <Avatar className="h-7 w-8">
          <AvatarFallback className="text-xs">
            {getInitials(displayName, displayEmail)}
          </AvatarFallback>
        </Avatar>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium truncate">{displayName}</span>
          </div>
          {displayEmail && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              {getSubjectIcon(collaborator.subject_type)}
              <span className="truncate">{displayEmail}</span>
            </div>
          )}
          {collaborator.subject_type !== 'user' && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              {getSubjectIcon(collaborator.subject_type)}
              <span className="capitalize">{collaborator.subject_type}</span>
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {isReadOnlyRow ? (
          <PermissionPill
            permissionLabel={PERMISSION_LABELS[collaborator.permission_level]}
          />
        ) : (
          <>
            <PermissionDropdown
              value={collaborator.permission_level}
              onChange={onPermissionChange}
            />
            <Button variant="ghost" size="sm" onClick={onRemove}>
              <X size={14} />
            </Button>
          </>
        )}
      </div>
    </div>
  );
};

interface CollaboratorsListProps {
  collectionId: string;
  canManageSharing: boolean;
  excludeSubjectId?: string;
}

const CollaboratorsList = ({
  collectionId,
  canManageSharing,
  excludeSubjectId,
}: CollaboratorsListProps) => {
  const { data: collaborators } = useGetCollaboratorsQuery(collectionId);

  const userCollaborators = (collaborators?.filter(
    (c): c is UserCollaborator =>
      c.subject_type === 'user' && c.subject_id !== excludeSubjectId
  ) ?? []) as UserCollaborator[];
  const orgCollaborators = (collaborators?.filter(
    (c): c is OrganizationCollaborator => c.subject_type === 'organization'
  ) ?? []) as OrganizationCollaborator[];

  const collaboratorCount = userCollaborators.length + orgCollaborators.length;

  return (
    <div className="space-y-1">
      <h3 className="text-sm font-medium">
        Collaborators ({collaboratorCount})
      </h3>

      {userCollaborators.map((collaborator) => (
        <CollaboratorRow
          key={`${collaborator.subject_id}-${collaborator.subject_type}-${collaborator.collection_id}`}
          collaborator={collaborator}
          canManageSharing={canManageSharing}
        />
      ))}
      {orgCollaborators.map((collaborator) => (
        <CollaboratorRow
          key={`${collaborator.subject_id}-${collaborator.subject_type}-${collaborator.collection_id}`}
          collaborator={collaborator}
          canManageSharing={canManageSharing}
        />
      ))}
    </div>
  );
};

export default CollaboratorsList;
