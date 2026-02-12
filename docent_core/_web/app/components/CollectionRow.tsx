'use client';

import {
  CheckIcon,
  Copy,
  CopyPlus,
  Loader2,
  Pencil,
  Trash2,
  XIcon,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { COLLECTIONS_DASHBOARD_PATH } from '@/app/constants';
import { Collection } from '@/app/types/collectionTypes';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TableCell, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import UuidPill from '@/components/UuidPill';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { formatDateValue } from '@/lib/dateUtils';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Label } from '@/components/ui/label';
import { useUserContext } from '@/app/contexts/UserContext';

import {
  useUpdateCollectionMutation,
  useCloneCollectionMutation,
  CollectionCounts,
} from '../api/collectionApi';

export interface CollectionRowProps {
  collection: Collection;
  counts?: CollectionCounts;
  countsLoading?: boolean;
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
  counts,
  countsLoading,
  hasWritePermission,
  hasAdminPermission,
  permissionsLoading,
  onDelete,
}: CollectionRowProps) {
  const router = useRouter();
  const { user } = useUserContext();

  // Local editing state
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(collection.name ?? '');
  const [description, setDescription] = useState(collection.description ?? '');

  // Clone dialog state
  const [isCloneDialogOpen, setIsCloneDialogOpen] = useState(false);
  const [cloneName, setCloneName] = useState('');
  const [cloneDescription, setCloneDescription] = useState('');

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
  const [cloneCollection, { isLoading: isCloning }] =
    useCloneCollectionMutation();

  const saveChanges = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isEditing) return;

    updateCollection({
      collection_id: collection.id,
      name,
      description,
    });

    toast.success('The collection has been updated successfully');

    setIsEditing(false);
  };

  const triggerClone = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    // If user is not logged in, redirect to signup
    if (!user || user.is_anonymous) {
      const currentPath = window.location.pathname;
      const signupUrl = `/signup?redirect=${encodeURIComponent(currentPath)}`;
      router.push(signupUrl);
      return;
    }

    // Open clone dialog
    const defaultName = collection.name
      ? `${collection.name} (Copy)`
      : 'Cloned Collection';
    setCloneName(defaultName);
    setCloneDescription(collection.description ?? '');
    setIsCloneDialogOpen(true);
  };

  const handleClone = async () => {
    if (!user || user.is_anonymous) return;

    try {
      const result = await cloneCollection({
        collection_id: collection.id,
        name: cloneName.trim() || undefined,
        description: cloneDescription.trim() || undefined,
      }).unwrap();

      toast.success(
        `Collection cloned successfully! ${result.agent_runs_cloned} agent runs copied.`
      );

      setIsCloneDialogOpen(false);

      // Navigate to the new collection
      router.push(`${COLLECTIONS_DASHBOARD_PATH}/${result.collection_id}`);
    } catch (error: any) {
      console.error('Failed to clone collection:', error);
      const message =
        error?.data?.detail || error?.message || 'Failed to clone collection';
      toast.error(message);
    }
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
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-primary text-xs truncate block">
                {collection.name || (
                  <span className="italic text-muted-foreground">
                    Unnamed Collection
                  </span>
                )}
              </span>
            </TooltipTrigger>
            {collection.name && (
              <TooltipContent side="bottom" className="max-w-sm break-words">
                {collection.name}
              </TooltipContent>
            )}
          </Tooltip>
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
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-xs text-muted-foreground truncate block">
                {collection.description || (
                  <span className="italic text-muted-foreground">
                    No description provided
                  </span>
                )}
              </span>
            </TooltipTrigger>
            {collection.description && (
              <TooltipContent side="bottom" className="max-w-sm break-words">
                {collection.description}
              </TooltipContent>
            )}
          </Tooltip>
        )}
      </TableCell>

      {/* Agent Run Count */}
      <TableCell className="text-xs py-2">
        {countsLoading ? (
          <Skeleton className="h-4 w-8" />
        ) : (
          <span className="text-muted-foreground">
            {counts?.agent_run_count?.toLocaleString() ?? '-'}
          </span>
        )}
      </TableCell>

      {/* Rubric Count */}
      <TableCell className="text-xs py-2">
        {countsLoading ? (
          <Skeleton className="h-4 w-8" />
        ) : (
          <span className="text-muted-foreground">
            {counts?.rubric_count?.toLocaleString() ?? '-'}
          </span>
        )}
      </TableCell>

      {/* Label Set Count */}
      <TableCell className="text-xs py-2">
        {countsLoading ? (
          <Skeleton className="h-4 w-8" />
        ) : (
          <span className="text-muted-foreground">
            {counts?.label_set_count?.toLocaleString() ?? '-'}
          </span>
        )}
      </TableCell>

      {/* Created At */}
      <TableCell className="text-xs py-2">
        <div className="flex items-center text-muted-foreground whitespace-nowrap">
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
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-auto w-auto text-muted-foreground hover:text-indigo-text p-0"
                      onClick={triggerClone}
                    >
                      <CopyPlus className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    {!user || user.is_anonymous
                      ? 'Sign up to clone collection'
                      : 'Clone collection'}
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-auto w-auto text-muted-foreground hover:text-blue-text p-0"
                      onClick={startEditing}
                      disabled={!hasWritePermission}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">Edit collection</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex"
                    >
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-auto w-auto text-muted-foreground hover:text-red-text p-0"
                        disabled={!hasAdminPermission}
                        onClick={hasAdminPermission ? triggerDelete : undefined}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    {hasAdminPermission
                      ? 'Delete collection'
                      : 'Admin permission required'}
                  </TooltipContent>
                </Tooltip>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-auto w-auto text-muted-foreground hover:text-indigo-text p-0"
                      onClick={triggerClone}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    {!user || user.is_anonymous
                      ? 'Sign up to clone collection'
                      : 'Clone collection'}
                  </TooltipContent>
                </Tooltip>
                <div className="text-muted-foreground text-xs">Read only</div>
              </div>
            )}
          </div>
        )}
      </TableCell>

      {/* Clone Dialog */}
      <Dialog open={isCloneDialogOpen} onOpenChange={setIsCloneDialogOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>Clone Collection</DialogTitle>
            <DialogDescription>
              Create a copy of this collection with all agent runs. Rubrics,
              charts, and other configuration will not be copied.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="clone-name">Name</Label>
              <Input
                id="clone-name"
                value={cloneName}
                onChange={(e) => setCloneName(e.target.value)}
                placeholder="Enter collection name"
                onClick={(e) => e.stopPropagation()}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="clone-description">Description (optional)</Label>
              <Input
                id="clone-description"
                value={cloneDescription}
                onChange={(e) => setCloneDescription(e.target.value)}
                placeholder="Enter description"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={(e) => {
                e.stopPropagation();
                setIsCloneDialogOpen(false);
              }}
              disabled={isCloning}
            >
              Cancel
            </Button>
            <Button
              onClick={(e) => {
                e.stopPropagation();
                handleClone();
              }}
              disabled={isCloning}
            >
              {isCloning ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Cloning...
                </>
              ) : (
                'Clone Collection'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TableRow>
  );
}
