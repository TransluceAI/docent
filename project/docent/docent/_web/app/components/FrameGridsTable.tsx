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
  ExternalLinkIcon,
  FilterIcon,
  Layers,
  Loader2,
  SearchIcon,
} from 'lucide-react';
import { BASE_DOCENT_PATH } from '@/app/constants';
import { useRouter } from 'next/navigation';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useState } from 'react';
import { cn } from '@/lib/utils';

interface FrameGridsTableProps {
  frameGrids: FrameGrid[];
  isLoading: boolean;
}

export function FrameGridsTable({
  frameGrids,
  isLoading,
}: FrameGridsTableProps) {
  const router = useRouter();
  const [hoveredRowId, setHoveredRowId] = useState<string | null>(null);

  const handleOpenFrameGrid = (gridId: string) => {
    router.push(`${BASE_DOCENT_PATH}/${gridId}`);
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center h-full min-h-[200px]">
        <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    );
  }

  if (!frameGrids || frameGrids.length === 0) {
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
          <TableHead className="w-[20%] py-2.5 font-medium text-xs text-gray-500">
            Created
          </TableHead>
          <TableHead className="w-[5%] py-2.5"></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {frameGrids.map((grid) => (
          <TableRow
            key={grid.id}
            className={cn(
              'cursor-pointer transition-colors',
              hoveredRowId === grid.id ? 'bg-blue-50' : ''
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
              </div>
            </TableCell>
            <TableCell className="py-2">
              <span className="text-gray-900 text-xs">
                {grid.name || (
                  <span className="italic text-gray-400">Unnamed Grid</span>
                )}
              </span>
            </TableCell>
            <TableCell className="py-2 text-xs text-gray-500">
              {grid.description || (
                <span className="italic text-gray-400">
                  No description provided
                </span>
              )}
            </TableCell>
            <TableCell className="text-xs py-2">
              <div className="flex items-center text-gray-500">
                <CalendarIcon className="h-3 w-3 mr-1 text-gray-400" />
                {formatDate(grid.created_at)}
              </div>
            </TableCell>
            <TableCell className="py-2">
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  'h-7 w-7',
                  hoveredRowId === grid.id ? 'text-blue-500' : 'text-gray-400'
                )}
                onClick={(e) => {
                  e.stopPropagation();
                  handleOpenFrameGrid(grid.id);
                }}
              >
                <ExternalLinkIcon className="h-3.5 w-3.5" />
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
