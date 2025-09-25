/**
 * This is the homepage for the investigator application.
 * It includes the list of workspaces, which are self-contained
 * environments for performing experiments, analagously to how Docent collections
 * contain agent runs. (This page is similar to the main Docent dashboard, but shows
 * workspaces instead of collections.)
 *
 * Key functionalities:
 * - Creating new workspaces (with a required name and optional description)
 * - Renaming workspaces/changing their description
 * - Deleting workspaces
 *
 * http://localhost:3001/investigator
 */

'use client';

import { ModeToggle } from '@/components/ui/theme-toggle';
import { PlusIcon, FlaskConicalIcon } from 'lucide-react';
import { useState } from 'react';

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

import { WorkspacesTable } from '../components/WorkspacesTable';
import { UserProfile } from '../components/auth/UserProfile';
import { useRequireUserContext } from '../contexts/UserContext';
import {
  useCreateWorkspaceMutation,
  useGetWorkspacesQuery,
} from '../api/investigatorApi';
import AccessDeniedPage from './components/AccessDeniedPage';
import { handleInvestigatorError, is403Error } from './utils/errorHandling';

export default function InvestigatorHomePage() {
  // User is guaranteed to be present in authenticated pages
  const { user } = useRequireUserContext();

  // New workspace dialog state
  const [isNewWorkspaceDialogOpen, setIsNewWorkspaceDialogOpen] =
    useState(false);
  const [newWorkspaceName, setNewWorkspaceName] = useState('');
  const [newWorkspaceDescription, setNewWorkspaceDescription] = useState('');

  // RTK Query hooks
  const {
    data: workspaces,
    isLoading: isLoadingWorkspaces,
    error: workspacesError,
  } = useGetWorkspacesQuery();
  const [createWorkspace, { isLoading: isCreatingWorkspace }] =
    useCreateWorkspaceMutation();

  // Check for 403 error
  if (workspacesError && is403Error(workspacesError)) {
    return (
      <AccessDeniedPage
        title="Investigator Access Denied"
        message="You are not authorized to access investigator features."
        backButtonText="Back to Dashboard"
        backButtonHref="/dashboard"
      />
    );
  }

  const handleCreateWorkspace = async () => {
    // Validate that name is provided
    if (!newWorkspaceName.trim()) {
      toast({
        title: 'Name Required',
        description: 'Please provide a name for the workspace',
        variant: 'destructive',
      });
      return;
    }

    try {
      await createWorkspace({
        name: newWorkspaceName,
        description: newWorkspaceDescription,
      }).unwrap();

      // Close dialog and reset form
      setIsNewWorkspaceDialogOpen(false);
      setNewWorkspaceName('');
      setNewWorkspaceDescription('');

      toast({
        title: 'Workspace Created',
        description: 'New workspace has been created successfully',
      });
    } catch (error) {
      console.error('Failed to create workspace:', error);
      handleInvestigatorError(error, 'Failed to create new workspace');
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
                Investigator Dashboard
              </div>
              <div className="text-xs text-muted-foreground">
                Welcome {user.email}!{' '}
                {user.is_anonymous
                  ? 'Make an account to create new workspaces.'
                  : 'Create a new workspace for each set of experiments.'}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      className="flex items-center gap-1 h-7"
                      size="sm"
                      onClick={() => setIsNewWorkspaceDialogOpen(true)}
                      disabled={user.is_anonymous}
                    >
                      <PlusIcon className="h-3.5 w-3.5" />
                      Create New Workspace
                    </Button>
                  </TooltipTrigger>
                  {user.is_anonymous && (
                    <TooltipContent>
                      <p>Create an account to create workspaces</p>
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

        {/* Info banner */}
        <div className="bg-secondary border-border rounded-sm p-3">
          <div className="flex items-start gap-3">
            <FlaskConicalIcon className="h-5 w-5 text-muted-foreground mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <h3 className="font-medium text-sm mb-1 text-primary">
                Experiment Workspaces
              </h3>
              <p className="text-xs text-muted-foreground mb-3">
                Workspaces are self-contained environments for your experiments.
                Each workspace can contain its own judge configurations, backend
                settings, base contexts, and experiment configurations.
              </p>
              <div className="text-xs text-muted-foreground">
                <strong>Tip:</strong> Create separate workspaces for different
                projects or experiment types to keep your configurations
                organized.
              </div>
            </div>
          </div>
        </div>

        {/* Table area */}
        <WorkspacesTable
          workspaces={workspaces}
          isLoading={isLoadingWorkspaces}
        />
      </div>

      {/* Create New Workspace Dialog */}
      <Dialog
        open={isNewWorkspaceDialogOpen}
        onOpenChange={setIsNewWorkspaceDialogOpen}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Workspace</DialogTitle>
            <DialogDescription>
              Create a new workspace for your experiments. Each workspace is a
              self-contained environment with its own configurations.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="new-name">
                Name <span className="text-red-text">*</span>
              </Label>
              <Input
                id="new-name"
                value={newWorkspaceName}
                onChange={(e) => setNewWorkspaceName(e.target.value)}
                placeholder="e.g., Safety Experiments Q4 2024"
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="new-description">Description</Label>
              <Textarea
                id="new-description"
                value={newWorkspaceDescription}
                onChange={(e) => setNewWorkspaceDescription(e.target.value)}
                placeholder="Describe the purpose of this workspace"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setIsNewWorkspaceDialogOpen(false);
                setNewWorkspaceName('');
                setNewWorkspaceDescription('');
              }}
              disabled={isCreatingWorkspace}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreateWorkspace}
              disabled={isCreatingWorkspace || !newWorkspaceName.trim()}
            >
              {isCreatingWorkspace ? 'Creating...' : 'Create Workspace'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ScrollArea>
  );
}
