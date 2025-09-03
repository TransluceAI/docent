'use client';
import { ModeToggle } from '@/components/ui/theme-toggle';

import { PlusIcon, BookOpenIcon } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { toast } from '@/hooks/use-toast';

import { CollectionsTable } from '../components/CollectionsTable';
import { UserProfile } from '../components/auth/UserProfile';
import { resetCollectionSlice } from '../store/collectionSlice';
import { useAppDispatch } from '../store/hooks';
import { resetTranscriptSlice } from '../store/transcriptSlice';
import { useRequireUserContext } from '../contexts/UserContext';
import {
  useCreateCollectionMutation,
  useGetCollectionsQuery,
} from '../api/collectionApi';

export default function HomePage() {
  // User is guaranteed to be present in authenticated pages
  const { user } = useRequireUserContext();

  const dispatch = useAppDispatch();

  // New collection dialog state
  const [isNewCollectionDialogOpen, setIsNewCollectionDialogOpen] =
    useState(false);
  const [newCollectionName, setNewCollectionName] = useState('');
  const [newCollectionDescription, setNewCollectionDescription] = useState('');

  // RTK Query hooks
  const { data: collections, isLoading: isLoadingCollections } =
    useGetCollectionsQuery();
  const [createCollection, { isLoading: isCreatingCollection }] =
    useCreateCollectionMutation();

  /**
   * TODO(mengk): get rid of this!!!
   */
  useEffect(() => {
    // Clear out old state
    dispatch(resetCollectionSlice());
    dispatch(resetTranscriptSlice());
    // TODO(mengk): call thunks to cancel the transcript requests too
  }, [dispatch]);

  const handleCreateCollection = async () => {
    try {
      await createCollection({
        name: newCollectionName,
        description: newCollectionDescription,
      }).unwrap();

      // Close dialog and reset form
      setIsNewCollectionDialogOpen(false);
      setNewCollectionName('');
      setNewCollectionDescription('');

      toast({
        title: 'Collection Created',
        description: 'New collection has been created successfully',
      });
    } catch (error) {
      console.error('Failed to create collection:', error);
      toast({
        title: 'Error',
        description: 'Failed to create new collection',
        variant: 'destructive',
      });
    }
  };

  return (
    <ScrollArea className="h-screen">
      <div className="container mx-auto py-4 px-3 max-w-screen-xl space-y-3">
        {/* Header Section */}
        <div className="space-y-1 mb-4">
          <div className="flex justify-between items-center">
            <div>
              <div className="text-lg font-semibold tracking-tight">
                Docent Dashboard
              </div>
              <div className="text-xs text-muted-foreground">
                Welcome {user.email}!{' '}
                {user.is_anonymous
                  ? 'Make an account to create new Collections.'
                  : 'Create a new Collection for each benchmark or set of experiments.'}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      className="flex items-center gap-1 h-7"
                      size="sm"
                      onClick={() => setIsNewCollectionDialogOpen(true)}
                      disabled={user.is_anonymous}
                    >
                      <PlusIcon className="h-3.5 w-3.5" />
                      Create New Collection
                    </Button>
                  </TooltipTrigger>
                  {user.is_anonymous && (
                    <TooltipContent>
                      <p>Create an account to create collections</p>
                    </TooltipContent>
                  )}
                </Tooltip>
              </TooltipProvider>
              <ModeToggle />
              <UserProfile />
            </div>
          </div>
        </div>

        <Separator className="my-4" />

        {/* Quickstart banner */}
        <div className="bg-secondary border-border rounded-sm p-3">
          <div className="flex items-start gap-3">
            <BookOpenIcon className="h-5 w-5 text-muted-foreground mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <h3 className="font-medium text-sm mb-1 text-primary">
                Get Started with Docent
              </h3>
              <p className="text-xs text-muted-foreground mb-3">
                Learn how to ingest your data and get started with analysis!
              </p>
              <Button variant="outline" size="sm" asChild>
                <a
                  href="https://transluce-docent.readthedocs-hosted.com/en/latest/quickstart"
                  target="_blank"
                  className="inline-flex items-center gap-1"
                >
                  Read the quickstart guide
                </a>
              </Button>
              <Button variant="outline" size="sm" asChild>
                <a
                  href="https://docent.transluce.org/sample"
                  target="_blank"
                  className="inline-flex items-center gap-1 ml-1"
                >
                  Check out a sample collection
                </a>
              </Button>
            </div>
          </div>
        </div>

        {/* Table area */}
        <CollectionsTable
          collections={collections}
          isLoading={isLoadingCollections}
        />
      </div>

      {/* Create New Collection Dialog */}
      <Dialog
        open={isNewCollectionDialogOpen}
        onOpenChange={setIsNewCollectionDialogOpen}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Collection</DialogTitle>
            <DialogDescription>
              Create a new collection for your benchmark or experiment set.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="new-name">Name</Label>
              <Input
                id="new-name"
                value={newCollectionName}
                onChange={(e) => setNewCollectionName(e.target.value)}
                placeholder="Enter a name for this collection"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="new-description">Description</Label>
              <Textarea
                id="new-description"
                value={newCollectionDescription}
                onChange={(e) => setNewCollectionDescription(e.target.value)}
                placeholder="Enter a description for this collection"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsNewCollectionDialogOpen(false)}
              disabled={isCreatingCollection}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreateCollection}
              disabled={isCreatingCollection}
            >
              {isCreatingCollection ? 'Creating...' : 'Create Collection'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ScrollArea>
  );
}
