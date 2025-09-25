'use client';

import { Layers, Loader2 } from 'lucide-react';
import { useState } from 'react';

import { InvestigatorWorkspace } from '@/app/api/investigatorApi';
import { Button } from '@/components/ui/button';
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

import WorkspaceRow from '../components/WorkspaceRow';
import { useDeleteWorkspaceMutation } from '../api/investigatorApi';

interface WorkspacesTableProps {
  workspaces?: InvestigatorWorkspace[];
  isLoading: boolean;
}

export function WorkspacesTable({
  workspaces,
  isLoading,
}: WorkspacesTableProps) {
  // Delete dialog state – kept here so multiple rows can reuse shared dialog
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingWorkspace, setDeletingWorkspace] =
    useState<InvestigatorWorkspace | null>(null);

  const openDeleteDialog = (workspace: InvestigatorWorkspace) => {
    setDeletingWorkspace(workspace);
    setIsDeleteDialogOpen(true);
  };

  const [deleteWorkspace] = useDeleteWorkspaceMutation();

  const handleDeleteWorkspace = () => {
    if (!deletingWorkspace) return;
    deleteWorkspace(deletingWorkspace.id);
    setIsDeleteDialogOpen(false);
  };

  if (isLoading || !workspaces) {
    return (
      <div className="flex-1 flex items-center justify-center h-full min-h-[200px]">
        <Loader2 size={16} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (workspaces.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 px-3 text-center">
        <div className="bg-secondary p-3 rounded-full mb-3">
          <Layers className="h-7 w-7 text-primary" />
        </div>
        <h3 className="text-sm font-medium text-primary mb-1">
          No workspaces available
        </h3>
        <p className="text-xs text-muted-foreground max-w-md">
          Create a new workspace to get started with your experiments.
        </p>
      </div>
    );
  }

  return (
    <>
      <Table>
        <TableHeader className="bg-secondary sticky top-0">
          <TableRow>
            <TableHead className="w-[15%] py-2.5 font-medium text-xs text-muted-foreground">
              ID
            </TableHead>
            <TableHead className="w-[25%] py-2.5 font-medium text-xs text-muted-foreground">
              Name
            </TableHead>
            <TableHead className="w-[35%] py-2.5 font-medium text-xs text-muted-foreground">
              Description
            </TableHead>
            <TableHead className="w-[15%] py-2.5 font-medium text-xs text-muted-foreground">
              Created
            </TableHead>
            <TableHead className="w-[10%] py-2.5 font-medium text-xs text-muted-foreground text-right">
              Actions
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {workspaces.map((workspace) => (
            <WorkspaceRow
              key={workspace.id}
              workspace={workspace}
              onDelete={openDeleteDialog}
            />
          ))}
        </TableBody>
      </Table>

      {/* Delete Confirmation Dialog */}
      <Dialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Workspace</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this workspace? This will
              permanently delete all experiment configurations, judge configs,
              backend configs, and base contexts within this workspace. This
              action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            {deletingWorkspace && (
              <div className="flex flex-col space-y-2 bg-secondary p-3 rounded-md">
                <div className="text-sm font-medium break-all">
                  {deletingWorkspace.name || 'Unnamed Workspace'}
                </div>
                <div className="text-xs text-muted-foreground">
                  {deletingWorkspace.description || 'No description'}
                </div>
                <div className="text-xs font-mono text-secondary">
                  ID: {deletingWorkspace.id}
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
            <Button variant="destructive" onClick={handleDeleteWorkspace}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
