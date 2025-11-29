'use client';

import { CheckIcon, Loader2, Pencil, Trash2, XIcon } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { COLLECTIONS_DASHBOARD_PATH } from '@/app/constants';
import { Collection } from '@/app/types/collectionTypes';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TableCell, TableRow } from '@/components/ui/table';
import UuidPill from '@/components/UuidPill';
import { toast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';
import { formatDateValue } from '@/lib/dateUtils';

import { useUpdateCollectionMutation } from '../api/collectionApi';

export interface CollectionRowProps {
  collection: Collection;
  hasWritePermission: boolean;
  hasAdminPermission: boolean;
  permissionsLoading: boolean;
  /**
   * Triggered when the delete button is pressed. The parent component is
   * responsible for showing the confirmation dialog and dispatching the actual
   * delete thunk.
   */
  onDelete: (collection: Collection) => void;
}

export default function CollectionRow({
  collection,
  hasWritePermission,
  hasAdminPermission,
  permissionsLoading,
  onDelete,
}: CollectionRowProps) {
  const router = useRouter();

  // Local editing state
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(collection.name ?? '');
  const [description, setDescription] = useState(collection.description ?? '');

  /* ----------------------------- Event handlers ---------------------------- */
  const openCollection = (e?: React.MouseEvent) => {
    if (isEditing) return;
    const href = `${COLLECTIONS_DASHBOARD_PATH}/${collection.id}`;
    if (e && (e.metaKey || e.ctrlKey)) {
      window.open(href, '_blank');
      return;
    }
    router.push(href);
  };

  const handleAuxClick = (e: React.MouseEvent) => {
    if (isEditing) return;
    if (e.button === 1) {
      const href = `${COLLECTIONS_DASHBOARD_PATH}/${collection.id}`;
      window.open(href, '_blank');
    }
  };

  const startEditing = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsEditing(true);
  };

  const cancelEditing = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    setIsEditing(false);
    // Reset local state to original values
    setName(collection.name ?? '');
    setDescription(collection.description ?? '');
  };

  const [updateCollection] = useUpdateCollectionMutation();

  const saveChanges = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isEditing) return;

    updateCollection({
      collection_id: collection.id,
      name,
      description,
    });

    toast({
      title: 'Collection Updated',
      description: 'The collection has been updated successfully',
    });

    setIsEditing(false);
  };

  const triggerDelete = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onDelete(collection);
  };

  /* --------------------------------- Render -------------------------------- */
  return (
    <TableRow
      key={collection.id}
      onClick={openCollection}
      onAuxClick={handleAuxClick}
      className={cn(
        'group transition-colors cursor-pointer hover:bg-secondary/50',
        isEditing && 'bg-blue-50 cursor-default'
      )}
    >
      {/* ID */}
      <TableCell className="py-2.5">
        <UuidPill uuid={collection.id} stopPropagation />
      </TableCell>

      {/* Name */}
      <TableCell className="py-2">
        {isEditing ? (
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Enter collection name"
            className="h-7 text-xs py-0 px-2"
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span className="text-primary text-xs">
            {collection.name || (
              <span className="italic text-secondary">Unnamed Collection</span>
            )}
          </span>
        )}
      </TableCell>

      {/* Description */}
      <TableCell className="py-2">
        {isEditing ? (
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Enter description"
            className="h-7 text-xs py-0 px-2"
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span className="text-xs text-muted-foreground">
            {collection.description || (
              <span className="italic text-muted-foreground">
                No description provided
              </span>
            )}
          </span>
        )}
      </TableCell>

      {/* Agent Run Count */}
      <TableCell className="text-xs py-2 text-z">
        <span className="text-muted-foreground">
          {collection.agent_run_count?.toLocaleString() ?? '-'}
        </span>
      </TableCell>

      {/* Rubric Count */}
      <TableCell className="text-xs py-2">
        <span className="text-muted-foreground">
          {collection.rubric_count?.toLocaleString() ?? '-'}
        </span>
      </TableCell>

      {/* Label Set Count */}
      <TableCell className="text-xs py-2">
        <span className="text-muted-foreground">
          {collection.label_set_count?.toLocaleString() ?? '-'}
        </span>
      </TableCell>

      {/* Created At */}
      <TableCell className="text-xs py-2">
        <div className="flex items-center text-muted-foreground">
          {formatDateValue(collection.created_at, true)}
        </div>
      </TableCell>

      {/* Actions */}
      <TableCell className="py-2 text-right">
        {isEditing ? (
          <div className="flex items-center justify-end space-x-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-green-foreground"
              onClick={saveChanges}
              title="Save changes"
            >
              <CheckIcon className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground"
              onClick={cancelEditing}
              title="Cancel editing"
            >
              <XIcon className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : (
          <div className="flex items-center justify-end space-x-1">
            {/* <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-secondary group-hover:text-accent-foreground"
              onClick={(e) => {
                e.stopPropagation();
                openCollection();
              }}
              title="Open collection"
            >
              <ExternalLinkIcon className="h-3.5 w-3.5" />
            </Button> */}
            {permissionsLoading ? (
              <div className="flex items-center justify-end">
                <Loader2
                  size={16}
                  className="animate-spin text-muted-foreground"
                />
              </div>
            ) : hasWritePermission ? (
              <div className="flex items-center gap-3">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-auto w-auto text-muted-foreground group-hover:text-blue-text p-0"
                  onClick={startEditing}
                  disabled={!hasWritePermission}
                  title="Edit collection"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-auto w-auto text-muted-foreground group-hover:text-red-text p-0"
                  disabled={!hasAdminPermission}
                  onClick={triggerDelete}
                  title="Delete collection"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ) : (
              <div className="text-muted-foreground text-xs">Read only</div>
            )}
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}
