'use client';

import { Layers, Loader2, Search } from 'lucide-react';
import { useState } from 'react';

import { Collection } from '@/app/types/collectionTypes';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import CollectionRow from './CollectionRow';
import { useDeleteCollectionMutation } from '../api/collectionApi';
import { useGetCollectionsPermissionsQuery } from '@/lib/permissions/collabSlice';
import { useCollectionCounts } from '../hooks/use-collection-counts';
import { PERMISSION_LEVELS } from '@/lib/permissions/types';

interface CollectionsTableProps {
  collections?: Collection[];
  isLoading: boolean;
}

export function CollectionsTable({
  collections,
  isLoading,
}: CollectionsTableProps) {
  const [searchTerm, setSearchTerm] = useState('');

  // Delete dialog state – kept here so multiple rows can reuse shared dialog
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingCollection, setDeletingCollection] =
    useState<Collection | null>(null);

  const openDeleteDialog = (collection: Collection) => {
    setDeletingCollection(collection);
    setIsDeleteDialogOpen(true);
  };

  const [deleteCollection] = useDeleteCollectionMutation();
  const ids = (collections || []).map((c) => c.id);
  const { data: batchPerms, isFetching: permissionsFetching } =
    useGetCollectionsPermissionsQuery(ids, {
      skip: ids.length === 0,
    });

  // Fetch counts asynchronously in batches
  const { counts: collectionCounts, isLoading: countsLoading } =
    useCollectionCounts(ids);

  const handleDeleteCollection = () => {
    if (!deletingCollection) return;
    deleteCollection(deletingCollection.id);
    setIsDeleteDialogOpen(false);
  };

  if (isLoading || !collections) {
    return (
      <div className="flex-1 flex items-center justify-center h-full min-h-[200px]">
        <Loader2 size={16} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  const filteredCollections = collections.filter(
    (c) =>
      !searchTerm || c.name?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (collections.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 px-3 text-center">
        <div className="bg-secondary p-3 rounded-full mb-3">
          <Layers className="h-7 w-7 text-primary" />
        </div>
        <h3 className="text-sm font-medium text-primary mb-1">
          No collections available
        </h3>
        <p className="text-xs text-muted-foreground max-w-md">
          Create a new collection to get started.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search collections..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="pl-9 h-8"
        />
      </div>
      <Table className="table-fixed w-full">
        <TableHeader className="bg-secondary sticky top-0">
          <TableRow>
            <TableHead className="w-[10%] py-1 font-medium text-xs text-muted-foreground">
              ID
            </TableHead>
            <TableHead className="w-[20%] py-1 font-medium text-xs text-muted-foreground">
              Name
            </TableHead>
            <TableHead className="w-[20%] py-1 font-medium text-xs text-muted-foreground">
              Description
            </TableHead>
            <TableHead className="w-[8%] py-1 font-medium text-xs text-muted-foreground">
              Agent Runs
            </TableHead>
            <TableHead className="w-[8%] py-1 font-medium text-xs text-muted-foreground">
              Rubrics
            </TableHead>
            <TableHead className="w-[8%] py-1 font-medium text-xs text-muted-foreground">
              Label Sets
            </TableHead>
            <TableHead className="w-[12%] py-1 font-medium text-xs text-muted-foreground">
              Created
            </TableHead>
            <TableHead className="w-[8%] py-1 font-medium text-xs text-muted-foreground text-right">
              Actions
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filteredCollections.map((collection) => {
            const level =
              (batchPerms?.collection_permissions?.[collection.id] as
                | keyof typeof PERMISSION_LEVELS
                | undefined) || 'none';
            const hasWritePermission =
              PERMISSION_LEVELS[level] >= PERMISSION_LEVELS.write;
            const hasAdminPermission =
              PERMISSION_LEVELS[level] >= PERMISSION_LEVELS.admin;
            return (
              <CollectionRow
                key={collection.id}
                collection={collection}
                counts={collectionCounts[collection.id]}
                countsLoading={
                  countsLoading && !collectionCounts[collection.id]
                }
                onDelete={openDeleteDialog}
                hasWritePermission={hasWritePermission}
                hasAdminPermission={hasAdminPermission}
                permissionsLoading={Boolean(!batchPerms || permissionsFetching)}
              />
            );
          })}
        </TableBody>
      </Table>

      {/* Delete Confirmation Dialog - keep this one as requested */}
      <Dialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Collection</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this collection? This action
              cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            {deletingCollection && (
              <div className="flex flex-col space-y-2 bg-secondary p-3 rounded-md">
                <div className="text-sm font-medium break-all">
                  {deletingCollection.name || 'Unnamed Collection'}
                </div>
                <div className="text-xs text-muted-foreground">
                  {deletingCollection.description || 'No description'}
                </div>
                <div className="text-xs font-mono text-secondary">
                  ID: {deletingCollection.id}
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsDeleteDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteCollection}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
