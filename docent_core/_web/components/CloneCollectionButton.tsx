'use client';

import { CopyPlus, Loader2 } from 'lucide-react';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';
import { useCloneCollectionMutation } from '@/app/api/collectionApi';
import { COLLECTIONS_DASHBOARD_PATH } from '@/app/constants';
import { useUserContext } from '@/app/contexts/UserContext';
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

interface CloneCollectionButtonProps {
  variant?: 'default' | 'outline' | 'ghost';
  size?: 'default' | 'sm' | 'lg' | 'icon';
  className?: string;
  showLabel?: boolean;
  collectionName?: string | null;
}

export function CloneCollectionButton({
  variant = 'outline',
  size = 'default',
  className,
  showLabel = false,
  collectionName,
}: CloneCollectionButtonProps) {
  const params = useParams();
  const router = useRouter();
  const { user } = useUserContext();
  const collectionId = params.collection_id as string;

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [cloneName, setCloneName] = useState('');
  const [cloneDescription, setCloneDescription] = useState('');

  const [cloneCollection, { isLoading }] = useCloneCollectionMutation();

  const handleButtonClick = () => {
    // If user is not logged in, redirect to signup with return URL
    if (!user || user.is_anonymous) {
      const currentPath = window.location.pathname;
      const signupUrl = `/signup?redirect=${encodeURIComponent(currentPath)}`;
      router.push(signupUrl);
      return;
    }

    // If user is logged in, show the clone dialog
    const defaultName = collectionName
      ? `${collectionName} (Copy)`
      : 'Cloned Collection';
    setCloneName(defaultName);
    setCloneDescription('');
    setIsDialogOpen(true);
  };

  const handleClone = async () => {
    if (!user || user.is_anonymous) return;

    try {
      const result = await cloneCollection({
        collection_id: collectionId,
        name: cloneName.trim() || undefined,
        description: cloneDescription.trim() || undefined,
      }).unwrap();

      toast.success(
        `Collection cloned successfully! ${result.agent_runs_cloned} agent runs copied.`
      );

      setIsDialogOpen(false);

      // Hard navigation to the new collection to ensure fresh data load
      window.location.href = `${COLLECTIONS_DASHBOARD_PATH}/${result.collection_id}`;
    } catch (error: any) {
      const message =
        error?.data?.detail || error?.message || 'Failed to clone collection';
      toast.error(message);
    }
  };

  const buttonContent = (
    <Button
      variant={variant}
      size={size}
      className={cn(className)}
      onClick={handleButtonClick}
    >
      <CopyPlus className="h-4 w-4" />
      {showLabel && <span>Clone Collection</span>}
    </Button>
  );

  // Show tooltip only for icon-only buttons
  if (!showLabel) {
    return (
      <>
        <Tooltip>
          <TooltipTrigger asChild>{buttonContent}</TooltipTrigger>
          <TooltipContent side="right">
            {!user || user.is_anonymous
              ? 'Sign up to clone this collection'
              : 'Clone this collection'}
          </TooltipContent>
        </Tooltip>

        {/* Clone Dialog */}
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogContent>
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
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="clone-description">
                  Description (optional)
                </Label>
                <Input
                  id="clone-description"
                  value={cloneDescription}
                  onChange={(e) => setCloneDescription(e.target.value)}
                  placeholder="Enter description"
                />
              </div>
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setIsDialogOpen(false)}
                disabled={isLoading}
              >
                Cancel
              </Button>
              <Button onClick={handleClone} disabled={isLoading}>
                {isLoading ? (
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
      </>
    );
  }

  return (
    <>
      {buttonContent}

      {/* Clone Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
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
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="clone-description">Description (optional)</Label>
              <Input
                id="clone-description"
                value={cloneDescription}
                onChange={(e) => setCloneDescription(e.target.value)}
                placeholder="Enter description"
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsDialogOpen(false)}
              disabled={isLoading}
            >
              Cancel
            </Button>
            <Button onClick={handleClone} disabled={isLoading}>
              {isLoading ? (
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
    </>
  );
}
