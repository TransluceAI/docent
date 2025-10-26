'use client';

import { useMemo, useState } from 'react';
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Plus, CirclePlus, Trash2, CheckCircle2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn, getSchemaPreview } from '@/lib/utils';
import { LabelSet } from '@/app/api/labelApi';
import { SchemaDefinition } from '@/app/types/schema';

const ROW_HEIGHT_PX = 40;

export interface LabelSetTableRow {
  id: string;
  name: string;
  description: string | null;
  labelCount: number;
  labelSchema: SchemaDefinition;
}

export interface LabelSetsTableProps {
  labelSets: LabelSetTableRow[];
  selectedLabelSetId: string | null;
  onSelectLabelSet: (id: string) => void;
  onCreateNewLabelSet: () => void;
  onImportLabelSet?: (labelSet: LabelSet) => void;
  onDeleteLabelSet?: (labelSetId: string) => void;
  isValidRow: (row: LabelSetTableRow) => boolean;
  activeLabelSetId?: string;
  isLoading?: boolean;
  tooltipText?: {
    active: string;
    inactive: string;
  };
  incompatibleHeaderText?: string;
}

export default function LabelSetsTable({
  labelSets,
  selectedLabelSetId,
  onSelectLabelSet,
  onCreateNewLabelSet,
  onImportLabelSet,
  onDeleteLabelSet,
  isValidRow,
  activeLabelSetId,
  isLoading,
  tooltipText = {
    active: 'Currently active',
    inactive: 'Set as active label set',
  },
  incompatibleHeaderText,
}: LabelSetsTableProps) {
  const [deletePopoverId, setDeletePopoverId] = useState<string | null>(null);

  // Sort label sets into compatible and incompatible groups
  const { sortedLabelSets, firstIncompatibleIndex } = useMemo(() => {
    const compatible = labelSets.filter(isValidRow);
    const incompatible = labelSets.filter((row) => !isValidRow(row));
    return {
      sortedLabelSets: [...compatible, ...incompatible],
      firstIncompatibleIndex:
        incompatible.length > 0 ? compatible.length : undefined,
    };
  }, [labelSets, isValidRow]);

  //****************************
  // Import and delete buttons *
  //****************************

  const ActionButtons = ({ row }: { row: LabelSetTableRow }) => {
    const isValid = isValidRow(row);

    const isActive = row.id === activeLabelSetId;

    const labelSet: LabelSet = {
      id: row.id,
      name: row.name,
      description: row.description,
      label_schema: row.labelSchema,
    };

    return (
      <div
        className="flex items-center gap-1"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Show activate button in SingleRubricArea context */}
        {onImportLabelSet && isValid ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 p-0 !opacity-100"
                  disabled={isActive}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (!isActive) {
                      onImportLabelSet(labelSet);
                    }
                  }}
                >
                  {isActive ? (
                    <CheckCircle2 className="size-4 text-green-text flex-shrink-0" />
                  ) : (
                    <CirclePlus className="h-3.5 w-3.5" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {isActive ? tooltipText.active : tooltipText.inactive}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <div className="h-7 w-7 p-0 !opacity-100" />
        )}
        {onDeleteLabelSet && (
          <Popover
            open={deletePopoverId === row.id}
            onOpenChange={(open) => setDeletePopoverId(open ? row.id : null)}
          >
            <PopoverTrigger asChild>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 p-0 opacity-0 group-hover:opacity-100"
                onClick={(e) => e.stopPropagation()}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-64 p-3" align="end">
              <div className="space-y-3">
                <div className="text-sm font-medium">Delete label set?</div>
                <div className="text-xs text-muted-foreground">
                  This will permanently delete &quot;{row.name}
                  &quot; and all its labels.
                </div>
                <div className="flex justify-end gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeletePopoverId(null);
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    className="h-7 text-xs bg-red-bg border-red-border text-red-text hover:bg-red-muted"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteLabelSet(row.id);
                      setDeletePopoverId(null);
                    }}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </PopoverContent>
          </Popover>
        )}
      </div>
    );
  };

  //**********
  // Columns *
  //**********

  const columns = useMemo<ColumnDef<LabelSetTableRow, unknown>[]>(() => {
    return [
      {
        id: 'name',
        header: () => (
          <span className="text-xs font-medium text-muted-foreground">
            Name
          </span>
        ),
        cell: ({ row }) => {
          return (
            <span className="text-xs font-medium text-foreground">
              {row.original.name}
            </span>
          );
        },
        size: 100,
      },
      {
        id: 'description',
        header: () => (
          <span className="text-xs font-medium text-muted-foreground">
            Description
          </span>
        ),
        cell: ({ row }) => {
          const desc = row.original.description || '';
          const truncated = desc.length > 50 ? desc.slice(0, 50) + '...' : desc;
          return (
            <span className="text-xs text-muted-foreground" title={desc}>
              {truncated || '-'}
            </span>
          );
        },
        size: 200,
      },
      {
        id: 'labelCount',
        header: () => (
          <span className="text-xs font-medium text-muted-foreground">
            Labels
          </span>
        ),
        cell: ({ row }) => {
          return (
            <span className="text-xs text-muted-foreground">
              {row.original.labelCount}
            </span>
          );
        },
        size: 80,
      },
      {
        id: 'schema',
        header: () => (
          <span className="text-xs font-medium text-muted-foreground">
            Schema Preview
          </span>
        ),
        cell: ({ row }) => {
          const preview = getSchemaPreview(row.original.labelSchema);
          return (
            <div className="text-xs text-muted-foreground truncate">
              {preview || '-'}
            </div>
          );
        },
        size: 300,
      },
      {
        id: 'actions',
        header: () => (
          <span className="text-xs font-medium text-muted-foreground">
            {/* Actions */}
          </span>
        ),
        cell: ({ row }) => {
          return <ActionButtons row={row.original} />;
        },
        size: 100,
      },
    ];
  }, [onImportLabelSet, onDeleteLabelSet, activeLabelSetId, deletePopoverId]);

  const table = useReactTable({
    data: sortedLabelSets,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="flex flex-col h-full min-h-0 space-y-3">
      <div className="flex items-center justify-end">
        {/* <div className="text-sm font-semibold">Label Sets</div> */}
        <Button
          size="sm"
          onClick={onCreateNewLabelSet}
          className="gap-1.5 h-7 text-xs"
        >
          <Plus className="h-3 w-3" />
          Create New
        </Button>
      </div>

      <div className="border rounded-md flex-1 flex flex-col min-h-0">
        <div className="flex-1 min-h-0 overflow-auto custom-scrollbar">
          <Table className="min-w-full">
            <TableHeader className="sticky top-0 z-20 bg-secondary">
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className="text-xs"
                      style={{
                        height: ROW_HEIGHT_PX,
                        width: header.column.columnDef.size,
                      }}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="text-center py-8 text-xs text-muted-foreground"
                  >
                    Loading label sets...
                  </TableCell>
                </TableRow>
              ) : labelSets.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="text-center py-8 text-xs text-muted-foreground"
                  >
                    No label sets found. Create one to get started.
                  </TableCell>
                </TableRow>
              ) : (
                <>
                  {table.getRowModel().rows.map((row, index) => {
                    const isActive = selectedLabelSetId === row.original.id;
                    const isFirstIncompatible =
                      index === firstIncompatibleIndex;

                    return (
                      <>
                        {/* Insert separator row before first incompatible item */}
                        {isFirstIncompatible && incompatibleHeaderText && (
                          <TableRow
                            key="separator"
                            className="hover:bg-transparent"
                          >
                            <TableCell
                              colSpan={columns.length}
                              className="text-center py-2 text-xs bg-muted text-muted-foreground"
                            >
                              {incompatibleHeaderText}
                            </TableCell>
                          </TableRow>
                        )}

                        <TableRow
                          key={row.id}
                          data-state={isActive ? 'active' : undefined}
                          onClick={() => onSelectLabelSet(row.original.id)}
                          className={cn(
                            'text-xs cursor-pointer select-none group',
                            isActive
                              ? 'bg-indigo-bg/80 border-l-2 border-indigo-border'
                              : 'hover:bg-muted'
                          )}
                          style={{ height: ROW_HEIGHT_PX }}
                        >
                          {row.getVisibleCells().map((cell) => (
                            <TableCell
                              key={cell.id}
                              className="py-1.5"
                              style={{
                                width: cell.column.columnDef.size,
                              }}
                            >
                              {flexRender(
                                cell.column.columnDef.cell,
                                cell.getContext()
                              )}
                            </TableCell>
                          ))}
                        </TableRow>
                      </>
                    );
                  })}
                </>
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
