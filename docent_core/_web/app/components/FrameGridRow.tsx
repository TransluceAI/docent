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
import { FrameGrid } from '@/app/types/frameTypes';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TableCell, TableRow } from '@/components/ui/table';
import { toast } from '@/hooks/use-toast';
import { cn, copyToClipboard } from '@/lib/utils';

import { updateFrameGrid } from '../store/frameSlice';
import { useAppDispatch } from '../store/hooks';
import { useHasFramegridPermission } from '@/lib/permissions/hooks';

interface FrameGridRowProps {
  framegrid: FrameGrid;
  /**
   * Triggered when the delete button is pressed. The parent component is
   * responsible for showing the confirmation dialog and dispatching the actual
   * delete thunk.
   */
  onDelete: (grid: FrameGrid) => void;
}

export default function FrameGridRow({
  framegrid,
  onDelete,
}: FrameGridRowProps) {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const hasAdminPermission = useHasFramegridPermission('admin', framegrid.id);
  const hasWritePermission = useHasFramegridPermission('write', framegrid.id);

  // Local editing state
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(framegrid.name ?? '');
  const [description, setDescription] = useState(framegrid.description ?? '');

  /* ----------------------------- Event handlers ---------------------------- */
  const openFrameGrid = () => {
    // Prevent navigation while editing to avoid accidental navigation away
    if (isEditing) return;
    router.push(`${BASE_DOCENT_PATH}/${framegrid.id}`);
  };

  const copyId = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const success = await copyToClipboard(framegrid.id);
    if (success) {
      toast({
        title: 'FrameGrid ID Copied',
        description: `Copied ${framegrid.id} to clipboard`,
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
    setName(framegrid.name ?? '');
    setDescription(framegrid.description ?? '');
  };

  const saveChanges = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isEditing) return;

    dispatch(
      updateFrameGrid({
        fg_id: framegrid.id,
        name,
        description,
      })
    );

    toast({
      title: 'Frame Grid Updated',
      description: 'The frame grid has been updated successfully',
    });

    setIsEditing(false);
  };

  const triggerDelete = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onDelete(framegrid);
  };

  /* ------------------------------- Utilities ------------------------------- */
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  /* --------------------------------- Render -------------------------------- */
  return (
    <TableRow
      key={framegrid.id}
      onClick={openFrameGrid}
      className={cn(
        'group transition-colors cursor-pointer hover:bg-gray-50',
        isEditing && 'bg-blue-50 cursor-default'
      )}
    >
      {/* ID */}
      <TableCell className="font-medium py-3">
        <div className="flex items-center">
          <Layers className="h-3.5 w-3.5 text-gray-400 mr-1.5" />
          <span className="font-mono text-gray-600 text-xs">
            {framegrid.id.split('-')[0]}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 ml-1"
            onClick={copyId}
            title="Copy full ID"
          >
            <ClipboardCopyIcon className="h-3 w-3 text-gray-400 group-hover:text-blue-500" />
          </Button>
        </div>
      </TableCell>

      {/* Name */}
      <TableCell className="py-2">
        {isEditing ? (
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Enter grid name"
            className="h-7 text-xs py-0 px-2"
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span className="text-gray-900 text-xs">
            {framegrid.name || (
              <span className="italic text-gray-400">Unnamed Grid</span>
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
          <span className="text-xs text-gray-500">
            {framegrid.description || (
              <span className="italic text-gray-400">
                No description provided
              </span>
            )}
          </span>
        )}
      </TableCell>

      {/* Created At */}
      <TableCell className="text-xs py-2">
        <div className="flex items-center text-gray-500">
          <CalendarIcon className="h-3 w-3 mr-1 text-gray-400" />
          {formatDate(framegrid.created_at)}
        </div>
      </TableCell>

      {/* Actions */}
      <TableCell className="py-2 text-right">
        {isEditing ? (
          <div className="flex items-center justify-end space-x-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-green-500"
              onClick={saveChanges}
              title="Save changes"
            >
              <CheckIcon className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-gray-500"
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
              className="h-7 w-7 text-gray-400 group-hover:text-blue-500"
              onClick={(e) => {
                e.stopPropagation();
                openFrameGrid();
              }}
              title="Open frame grid"
            >
              <ExternalLinkIcon className="h-3.5 w-3.5" />
            </Button> */}
            {hasWritePermission ? (
              <div className="flex items-center gap-3">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-auto w-auto text-gray-400 group-hover:text-blue-500 p-0"
                  onClick={startEditing}
                  disabled={!hasWritePermission}
                  title="Edit frame grid"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-auto w-auto text-gray-400 group-hover:text-red-500 p-0"
                  disabled={!hasAdminPermission}
                  onClick={triggerDelete}
                  title="Delete frame grid"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ) : (
              <div className="text-gray-400 text-xs">Read only</div>
            )}
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}
