'use client';

import { FrameGrid } from '@/app/types/frameTypes';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  CalendarIcon,
  CheckIcon,
  ClipboardCopyIcon,
  ExternalLinkIcon,
  FilterIcon,
  Layers,
  Loader2,
  MoreHorizontal,
  Pencil,
  SearchIcon,
  Trash2,
  XIcon,
} from 'lucide-react';
import { BASE_DOCENT_PATH } from '@/app/constants';
import { useRouter } from 'next/navigation';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useState } from 'react';
import { cn } from '@/lib/utils';
import { toast } from '@/hooks/use-toast';
import { useAppDispatch } from '../store/hooks';
import { deleteFrameGrid, updateFrameGrid } from '../store/frameSlice';
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
import { Textarea } from '@/components/ui/textarea';

interface FrameGridsTableProps {
  frameGrids?: FrameGrid[];
  isLoading: boolean;
}

export function FrameGridsTable({
  frameGrids,
  isLoading,
}: FrameGridsTableProps) {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const [hoveredRowId, setHoveredRowId] = useState<string | null>(null);

  // Delete dialog state
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingGrid, setDeletingGrid] = useState<FrameGrid | null>(null);

  // Inline editing state
  const [editingRowId, setEditingRowId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');

  const handleOpenFrameGrid = (gridId: string) => {
    // Don't navigate if we're currently editing
    if (editingRowId) return;
    router.push(`${BASE_DOCENT_PATH}/${gridId}`);
  };

  const handleCopyId = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    navigator.clipboard
      .writeText(id)
      .then(() => {
        toast({
          title: 'FrameGrid ID Copied',
          description: `Copied ${id} to clipboard`,
        });
      })
      .catch((err) => {
        console.error('Failed to copy: ', err);
        toast({
          variant: 'destructive',
          description: 'Failed to copy ID',
        });
      });
  };

  const startEditing = (e: React.MouseEvent, grid: FrameGrid) => {
    e.stopPropagation();
    setEditingRowId(grid.id);
    setEditName(grid.name || '');
    setEditDescription(grid.description || '');
  };

  const cancelEditing = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingRowId(null);
  };

  const handleUpdateFrameGrid = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!editingRowId) return;

    dispatch(
      updateFrameGrid({
        fg_id: editingRowId,
        name: editName,
        description: editDescription,
      })
    );

    setEditingRowId(null);
    toast({
      title: 'Frame Grid Updated',
      description: 'The frame grid has been updated successfully',
    });
  };

  const openDeleteDialog = (e: React.MouseEvent, grid: FrameGrid) => {
    e.stopPropagation();
    setDeletingGrid(grid);
    setIsDeleteDialogOpen(true);
  };

  const handleDeleteFrameGrid = () => {
    if (!deletingGrid) return;

    dispatch(deleteFrameGrid(deletingGrid.id));
    setIsDeleteDialogOpen(false);
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  if (isLoading || !frameGrids) {
    return (
      <div className="flex-1 flex items-center justify-center h-full min-h-[200px]">
        <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    );
  }

  if (frameGrids.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 px-3 text-center">
        <div className="bg-gray-50 p-3 rounded-full mb-3">
          <Layers className="h-6 w-6 text-gray-400" />
        </div>
        <h3 className="text-sm font-medium text-gray-900 mb-1">
          No frame grids available
        </h3>
        <p className="text-xs text-gray-500 max-w-md">
          No frame grids have been created yet. Create a new frame grid to get
          started.
        </p>
      </div>
    );
  }

  return (
    <>
      <Table>
        <TableHeader className="bg-gray-50 sticky top-0">
          <TableRow>
            <TableHead className="w-[15%] py-2.5 font-medium text-xs text-gray-500">
              ID
            </TableHead>
            <TableHead className="w-[25%] py-2.5 font-medium text-xs text-gray-500">
              Name
            </TableHead>
            <TableHead className="w-[35%] py-2.5 font-medium text-xs text-gray-500">
              Description
            </TableHead>
            <TableHead className="w-[15%] py-2.5 font-medium text-xs text-gray-500">
              Created
            </TableHead>
            <TableHead className="w-[10%] py-2.5 font-medium text-xs text-gray-500 text-right">
              Actions
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {frameGrids.map((grid) => (
            <TableRow
              key={grid.id}
              className={cn(
                'transition-colors',
                editingRowId === grid.id ? 'bg-blue-50' : '',
                hoveredRowId === grid.id && editingRowId !== grid.id
                  ? 'bg-gray-50'
                  : '',
                editingRowId !== grid.id ? 'cursor-pointer' : ''
              )}
              onMouseEnter={() => setHoveredRowId(grid.id)}
              onMouseLeave={() => setHoveredRowId(null)}
              onClick={() => handleOpenFrameGrid(grid.id)}
            >
              <TableCell className="font-medium py-2">
                <div className="flex items-center">
                  <Layers className="h-3.5 w-3.5 text-gray-400 mr-1.5" />
                  <span className="font-mono text-gray-600 text-xs">
                    {grid.id.split('-')[0]}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 ml-1"
                    onClick={(e) => handleCopyId(e, grid.id)}
                    title="Copy full ID"
                  >
                    <ClipboardCopyIcon
                      className={cn(
                        'h-3 w-3',
                        hoveredRowId === grid.id
                          ? 'text-blue-500'
                          : 'text-gray-400'
                      )}
                    />
                  </Button>
                </div>
              </TableCell>
              <TableCell className="py-2">
                {editingRowId === grid.id ? (
                  <Input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder="Enter grid name"
                    className="h-7 text-xs py-0 px-2"
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <span className="text-gray-900 text-xs">
                    {grid.name || (
                      <span className="italic text-gray-400">Unnamed Grid</span>
                    )}
                  </span>
                )}
              </TableCell>
              <TableCell className="py-2">
                {editingRowId === grid.id ? (
                  <Input
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    placeholder="Enter description"
                    className="h-7 text-xs py-0 px-2"
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <span className="text-xs text-gray-500">
                    {grid.description || (
                      <span className="italic text-gray-400">
                        No description provided
                      </span>
                    )}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-xs py-2">
                <div className="flex items-center text-gray-500">
                  <CalendarIcon className="h-3 w-3 mr-1 text-gray-400" />
                  {formatDate(grid.created_at)}
                </div>
              </TableCell>
              <TableCell className="py-2 text-right">
                {editingRowId === grid.id ? (
                  <div className="flex items-center justify-end space-x-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-green-500"
                      onClick={handleUpdateFrameGrid}
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
                    <Button
                      variant="ghost"
                      size="icon"
                      className={cn(
                        'h-7 w-7',
                        hoveredRowId === grid.id
                          ? 'text-blue-500'
                          : 'text-gray-400'
                      )}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleOpenFrameGrid(grid.id);
                      }}
                      title="Open frame grid"
                    >
                      <ExternalLinkIcon className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className={cn(
                        'h-7 w-7',
                        hoveredRowId === grid.id
                          ? 'text-blue-500'
                          : 'text-gray-400'
                      )}
                      onClick={(e) => startEditing(e, grid)}
                      title="Edit frame grid"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className={cn(
                        'h-7 w-7',
                        hoveredRowId === grid.id
                          ? 'text-red-500'
                          : 'text-gray-400'
                      )}
                      onClick={(e) => openDeleteDialog(e, grid)}
                      title="Delete frame grid"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {/* Delete Confirmation Dialog - keep this one as requested */}
      <Dialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Frame Grid</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this frame grid? This action
              cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            {deletingGrid && (
              <div className="flex flex-col space-y-2 bg-gray-50 p-3 rounded-md">
                <div className="text-sm font-medium">
                  {deletingGrid.name || 'Unnamed Grid'}
                </div>
                <div className="text-xs text-gray-500">
                  {deletingGrid.description || 'No description'}
                </div>
                <div className="text-xs font-mono text-gray-400">
                  ID: {deletingGrid.id}
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
            <Button variant="destructive" onClick={handleDeleteFrameGrid}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
