'use client';

import { Loader2, PlusIcon } from 'lucide-react';
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
import { toast } from '@/hooks/use-toast';

import { FrameGridsTable } from './FrameGridsTable';
import { UserProfile } from './auth/UserProfile';
import { apiRestClient } from '../services/apiService';
import socketService from '../services/socketService';
import {
  cancelCurrentSearch,
  cancelCurrentClusterRequest,
  resetSearchSlice,
} from '../store/searchSlice';
import { resetExperimentViewerSlice } from '../store/experimentViewerSlice';
import { fetchFrameGrids, resetFrameSlice } from '../store/frameSlice';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { resetTranscriptSlice } from '../store/transcriptSlice';
import { useRequireUserContext } from '../contexts/UserContext';

export default function DocentDashboard() {
  // User is guaranteed to be present in authenticated pages
  const { user } = useRequireUserContext();

  const frameGridId = useAppSelector((state) => state.frame.frameGridId);
  const frameGrids = useAppSelector((state) => state.frame.frameGrids);
  const isLoadingFrameGrids = useAppSelector(
    (state) => state.frame.isLoadingFrameGrids
  );
  const dispatch = useAppDispatch();

  // New framegrid dialog state
  const [isNewGridDialogOpen, setIsNewGridDialogOpen] = useState(false);
  const [newGridName, setNewGridName] = useState('');
  const [newGridDescription, setNewGridDescription] = useState('');
  const [isCreatingGrid, setIsCreatingGrid] = useState(false);

  useEffect(() => {
    // Fetch data when component mounts
    dispatch(fetchFrameGrids());

    // Clear out old state
    socketService.closeSocket();
    dispatch(resetFrameSlice());
    dispatch(resetExperimentViewerSlice());
    dispatch(resetSearchSlice());
    dispatch(resetTranscriptSlice());
    dispatch(cancelCurrentSearch());
    dispatch(cancelCurrentClusterRequest());
    // TODO(mengk): call thunks to cancel the transcript requests too
  }, [dispatch, frameGridId]);

  const handleCreateFrameGrid = async () => {
    setIsCreatingGrid(true);
    try {
      await apiRestClient.post('/create', {
        name: newGridName,
        description: newGridDescription,
      });

      dispatch(fetchFrameGrids());

      // Close dialog and reset form
      setIsNewGridDialogOpen(false);
      setNewGridName('');
      setNewGridDescription('');

      toast({
        title: 'Frame Grid Created',
        description: 'New frame grid has been created successfully',
      });
    } catch (error) {
      console.error('Failed to create frame grid:', error);
      toast({
        title: 'Error',
        description: 'Failed to create new frame grid',
        variant: 'destructive',
      });
    } finally {
      setIsCreatingGrid(false);
    }
  };

  return (
    <ScrollArea className="h-screen">
      <div className="container mx-auto py-4 px-3 max-w-screen-xl">
        {/* Header Section */}
        <div className="space-y-1 mb-4">
          <div className="flex justify-between items-center">
            <div>
              <div className="text-lg font-semibold tracking-tight">
                Docent Dashboard
              </div>
              <div className="text-xs text-gray-500">
                Welcome {user.email}! Create a new FrameGrid for each benchmark
                or set of experiments.
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                className="flex items-center gap-1 h-7"
                size="sm"
                onClick={() => setIsNewGridDialogOpen(true)}
              >
                <PlusIcon className="h-3.5 w-3.5" />
                Create New Frame Grid
              </Button>
              <UserProfile />
            </div>
          </div>
        </div>

        <Separator className="my-4" />

        {/* Table area */}
        <FrameGridsTable
          frameGrids={frameGrids}
          isLoading={isLoadingFrameGrids}
        />
      </div>

      {/* Create New Frame Grid Dialog */}
      <Dialog open={isNewGridDialogOpen} onOpenChange={setIsNewGridDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Frame Grid</DialogTitle>
            <DialogDescription>
              Create a new frame grid for your benchmark or experiment set.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="new-name">Name</Label>
              <Input
                id="new-name"
                value={newGridName}
                onChange={(e) => setNewGridName(e.target.value)}
                placeholder="Enter a name for this frame grid"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="new-description">Description</Label>
              <Textarea
                id="new-description"
                value={newGridDescription}
                onChange={(e) => setNewGridDescription(e.target.value)}
                placeholder="Enter a description for this frame grid"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsNewGridDialogOpen(false)}
              disabled={isCreatingGrid}
            >
              Cancel
            </Button>
            <Button onClick={handleCreateFrameGrid} disabled={isCreatingGrid}>
              {isCreatingGrid ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating...
                </>
              ) : (
                'Create Frame Grid'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ScrollArea>
  );
}
