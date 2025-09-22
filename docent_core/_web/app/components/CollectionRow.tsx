'use client';

import {
  CalendarIcon,
  CheckIcon,
  ClipboardCopyIcon,
  Layers,
  Pencil,
  Trash2,
  XIcon,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { BASE_DOCENT_PATH } from '@/app/constants';
import { Collection } from '@/app/types/collectionTypes';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TableCell, TableRow } from '@/components/ui/table';
import { toast } from '@/hooks/use-toast';
import { cn, copyToClipboard } from '@/lib/utils';

import { useHasCollectionPermission } from '@/lib/permissions/hooks';
import { useUpdateCollectionMutation } from '../api/collectionApi';

interface CollectionRowProps {
  collection: Collection;
  /**
   * Triggered when the delete button is pressed. The parent component is
   * responsible for showing the confirmation dialog and dispatching the actual
   * delete thunk.
   */
  onDelete: (collection: Collection) => void;
}

export default function CollectionRow({
  collection,
  onDelete,
}: CollectionRowProps) {
  const router = useRouter();
  const hasAdminPermission = useHasCollectionPermission('admin', collection.id);
  const hasWritePermission = useHasCollectionPermission('write', collection.id);

  // Local editing state
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(collection.name ?? '');
  const [description, setDescription] = useState(collection.description ?? '');

  /* ----------------------------- Event handlers ---------------------------- */
  const openCollection = (e?: React.MouseEvent) => {
    if (isEditing) return;
    const href = `${BASE_DOCENT_PATH}/${collection.id}`;
    if (e && (e.metaKey || e.ctrlKey)) {
      window.open(href, '_blank');
      return;
    }
    router.push(href);
  };

  const handleAuxClick = (e: React.MouseEvent) => {
    if (isEditing) return;
    if (e.button === 1) {
      const href = `${BASE_DOCENT_PATH}/${collection.id}`;
      window.open(href, '_blank');
    }
  };

  const copyId = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const success = await copyToClipboard(collection.id);
    if (success) {
      toast({
        title: 'Collection ID Copied',
        description: `Copied ${collection.id} to clipboard`,
      });
    } else {
      toast({
        title: 'Failed to copy',
        description: 'Could not copy to clipboard',
        variant: 'destructive',
      });
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

  /* ------------------------------- Utilities ------------------------------- */
  const formatDate = (dateString: string) => {
    // dateString is in UTC
    const date = new Date(dateString + 'Z');
    // display in local time
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
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
      <TableCell className="font-medium py-3">
        <div className="flex items-center">
          <Layers className="h-3.5 w-3.5 text-muted-foreground mr-1.5" />
          <span className="font-mono text-primary text-xs">
            {collection.id.split('-')[0]}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 ml-1"
            onClick={copyId}
            title="Copy full ID"
          >
            <ClipboardCopyIcon className="h-3 w-3 text-muted-foreground group-hover:text-blue-text" />
          </Button>
        </div>
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

      {/* Created At */}
      <TableCell className="text-xs py-2">
        <div className="flex items-center text-muted-foreground">
          <CalendarIcon className="h-3 w-3 mr-1 text-muted-foreground" />
          {formatDate(collection.created_at)}
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
            {hasWritePermission ? (
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
