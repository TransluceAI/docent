'use client';

import { Layers, Loader2 } from 'lucide-react';
import { useState } from 'react';

import { FrameGrid } from '@/app/types/frameTypes';
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

import { deleteFrameGrid, fetchFrameGrids } from '../store/frameSlice';
import { useAppDispatch } from '../store/hooks';

import FrameGridRow from './FrameGridRow';

interface FrameGridsTableProps {
  frameGrids?: FrameGrid[];
  isLoading: boolean;
}

export function FrameGridsTable({
  frameGrids,
  isLoading,
}: FrameGridsTableProps) {
  const dispatch = useAppDispatch();

  // Delete dialog state – kept here so multiple rows can reuse shared dialog
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingGrid, setDeletingGrid] = useState<FrameGrid | null>(null);

  const openDeleteDialog = (grid: FrameGrid) => {
    setDeletingGrid(grid);
    setIsDeleteDialogOpen(true);
  };

  const handleDeleteFrameGrid = () => {
    if (!deletingGrid) return;

    dispatch(deleteFrameGrid(deletingGrid.id)).then(() => {
      dispatch(fetchFrameGrids());
    });
    setIsDeleteDialogOpen(false);
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
            <FrameGridRow
              key={grid.id}
              framegrid={grid}
              onDelete={openDeleteDialog}
            />
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
