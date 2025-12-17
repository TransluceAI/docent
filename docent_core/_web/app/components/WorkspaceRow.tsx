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

import { InvestigatorWorkspace } from '@/app/api/investigatorApi';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TableCell, TableRow } from '@/components/ui/table';
import { toast } from 'sonner';
import { cn, copyToClipboard } from '@/lib/utils';

import { useUpdateWorkspaceMutation } from '../api/investigatorApi';

interface WorkspaceRowProps {
  workspace: InvestigatorWorkspace;
  /**
   * Triggered when the delete button is pressed. The parent component is
   * responsible for showing the confirmation dialog and dispatching the actual
   * delete action.
   */
  onDelete: (workspace: InvestigatorWorkspace) => void;
}

export default function WorkspaceRow({
  workspace,
  onDelete,
}: WorkspaceRowProps) {
  const router = useRouter();

  // Local editing state
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(workspace.name ?? '');
  const [description, setDescription] = useState(workspace.description ?? '');

  /* ----------------------------- Event handlers ---------------------------- */
  const openWorkspace = () => {
    // Prevent navigation while editing to avoid accidental navigation away
    if (isEditing) return;
    router.push(`/investigator/${workspace.id}`);
  };

  const copyId = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const success = await copyToClipboard(workspace.id);
    if (success) {
      toast.success(`Copied ${workspace.id} to clipboard`);
    } else {
      toast.error('Could not copy to clipboard');
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
    setName(workspace.name ?? '');
    setDescription(workspace.description ?? '');
  };

  const [updateWorkspace] = useUpdateWorkspaceMutation();

  const saveChanges = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isEditing) return;

    try {
      await updateWorkspace({
        workspace_id: workspace.id,
        name,
        description,
      }).unwrap();

      toast.success('Your changes have been saved');

      setIsEditing(false);
    } catch (error) {
      toast.error('Failed to save changes. Please try again.');
    }
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    onDelete(workspace);
  };

  /* --------------------------------- Render --------------------------------- */
  const formattedDate = workspace.created_at
    ? new Date(workspace.created_at).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : 'Unknown';

  return (
    <TableRow
      className={cn(
        'cursor-pointer hover:bg-secondary/50 transition-colors',
        isEditing && 'bg-secondary/30'
      )}
      onClick={openWorkspace}
    >
      {/* ID Column */}
      <TableCell className="py-2.5">
        <div className="flex items-center gap-1.5">
          <Layers className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
          <span className="text-xs font-mono text-muted-foreground truncate max-w-[100px]">
            {workspace.id}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-5 w-5 p-0"
            onClick={copyId}
          >
            <ClipboardCopyIcon className="h-3 w-3" />
          </Button>
        </div>
      </TableCell>

      {/* Name Column */}
      <TableCell className="py-2.5">
        {isEditing ? (
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            className="h-7 text-xs"
            placeholder="Workspace name"
          />
        ) : (
          <div className="text-xs font-medium text-primary">
            {workspace.name || (
              <span className="text-muted-foreground italic">
                Unnamed Workspace
              </span>
            )}
          </div>
        )}
      </TableCell>

      {/* Description Column */}
      <TableCell className="py-2.5">
        {isEditing ? (
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            className="h-7 text-xs"
            placeholder="Workspace description"
          />
        ) : (
          <div className="text-xs text-muted-foreground">
            {workspace.description || (
              <span className="italic">No description</span>
            )}
          </div>
        )}
      </TableCell>

      {/* Created Date Column */}
      <TableCell className="py-2.5">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <CalendarIcon className="h-3 w-3" />
          {formattedDate}
        </div>
      </TableCell>

      {/* Actions Column */}
      <TableCell className="py-2.5 text-right">
        {isEditing ? (
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={saveChanges}
            >
              <CheckIcon className="h-3.5 w-3.5 text-green-text" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={cancelEditing}
            >
              <XIcon className="h-3.5 w-3.5 text-red-text" />
            </Button>
          </div>
        ) : (
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={startEditing}
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={handleDelete}
            >
              <Trash2 className="h-3.5 w-3.5 text-red-text" />
            </Button>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}
