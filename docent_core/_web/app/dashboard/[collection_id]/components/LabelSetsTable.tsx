'use client';

import { useMemo, useState } from 'react';
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import {
  CirclePlus,
  Trash2,
  ChevronDown,
  ChevronRight,
  ClipboardCopyIcon,
} from 'lucide-react';

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

import { cn, getSchemaPreview, copyToClipboard } from '@/lib/utils';
import { LabelSet } from '@/app/api/labelApi';
import { SchemaDefinition } from '@/app/types/schema';
import { toast } from '@/hooks/use-toast';

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
  onImportLabelSet?: (labelSet: LabelSet) => void;
  onDeleteLabelSet?: (labelSetId: string) => void;
  isValidRow?: (row: LabelSetTableRow) => boolean;
  activeLabelSetId?: string;
  isLoading?: boolean;
}

export default function LabelSetsTable({
  labelSets,
  selectedLabelSetId,
  onSelectLabelSet,
  onImportLabelSet,
  onDeleteLabelSet,
  isValidRow,
  activeLabelSetId,
  isLoading,
}: LabelSetsTableProps) {
  const [deletePopoverId, setDeletePopoverId] = useState<string | null>(null);
  const [showIncompatible, setShowIncompatible] = useState(false);

  // Split label sets into compatible and incompatible groups
  const { compatibleLabelSets, incompatibleLabelSets } = useMemo(() => {
    if (!isValidRow) {
      return {
        compatibleLabelSets: labelSets,
        incompatibleLabelSets: [],
      };
    }

    const compatible = labelSets.filter(isValidRow);
    const incompatible = labelSets.filter((row) => !isValidRow(row));
    return {
      compatibleLabelSets: compatible,
      incompatibleLabelSets: incompatible,
    };
  }, [labelSets, isValidRow]);

  //****************************
  // Import and delete buttons *
  //****************************

  const ActionButtons = ({ row }: { row: LabelSetTableRow }) => {
    const isValid = isValidRow ? isValidRow(row) : true;

    const isActive = row.id === activeLabelSetId;

    const labelSet: LabelSet = {
      id: row.id,
      name: row.name,
      description: row.description,
      label_schema: row.labelSchema,
    };

    const copyId = async (e: React.MouseEvent) => {
      e.stopPropagation();
      const success = await copyToClipboard(row.id);
      if (success) {
        toast({
          title: 'Label Set ID Copied',
          description: `Copied ${row.id} to clipboard`,
        });
      } else {
        toast({
          title: 'Failed to copy',
          description: 'Could not copy to clipboard',
          variant: 'destructive',
        });
      }
    };

    return (
      <div
        className="flex items-center gap-1"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Show activate button in SingleRubricArea context */}
        <div className="flex justify-end w-16">
          {onImportLabelSet && isValid ? (
            <>
              {isActive ? (
                <div className="text-[10px] font-medium border text-green-text border-green-border bg-green-bg rounded-full px-2 py-0.5">
                  Selected
                </div>
              ) : (
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
                  <CirclePlus className="h-3.5 w-3.5" />
                </Button>
              )}
            </>
          ) : null}
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0 opacity-0 group-hover:opacity-100"
          onClick={copyId}
          title="Copy label set ID"
        >
          <ClipboardCopyIcon className="h-3.5 w-3.5" />
        </Button>
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
            <div className="text-xs text-muted-foreground truncate w-64">
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

  const compatibleTable = useReactTable({
    data: compatibleLabelSets,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const incompatibleTable = useReactTable({
    data: incompatibleLabelSets,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="border rounded-md flex-1 flex flex-col min-h-0">
      <div className="flex-1 min-h-0 overflow-auto custom-scrollbar">
        <Table className="min-w-full">
          <TableHeader className="sticky top-0 z-20 bg-secondary">
            {compatibleTable.getHeaderGroups().map((headerGroup) => (
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
            ) : compatibleLabelSets.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="text-center py-8 text-xs text-muted-foreground"
                >
                  No compatible label sets found. Create a new one to get
                  started.
                </TableCell>
              </TableRow>
            ) : (
              <>
                {compatibleTable.getRowModel().rows.map((row, index) => {
                  const isActive = selectedLabelSetId === row.original.id;
                  const nextIsActive =
                    index < compatibleTable.getRowModel().rows.length - 1 &&
                    compatibleTable.getRowModel().rows[index + 1].original
                      .id === selectedLabelSetId;

                  return (
                    <TableRow
                      key={row.id}
                      data-state={isActive ? 'active' : undefined}
                      onClick={() => onSelectLabelSet(row.original.id)}
                      className={cn(
                        'text-xs cursor-pointer select-none group',
                        isActive
                          ? 'bg-indigo-bg/80 hover:bg-indigo-bg/80'
                          : 'hover:bg-muted',
                        nextIsActive ? 'border-b-transparent' : 'border-b'
                      )}
                      style={{
                        height: ROW_HEIGHT_PX,
                        boxShadow: isActive
                          ? 'inset 0 0 0 1px hsl(var(--indigo-border))'
                          : undefined,
                      }}
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
                  );
                })}
              </>
            )}
          </TableBody>
        </Table>
      </div>

      {/* Collapsible incompatible label sets section */}
      {incompatibleLabelSets.length > 0 && (
        <div className="border-t">
          <button
            onClick={() => setShowIncompatible(!showIncompatible)}
            className="w-full px-4 py-2 flex items-center justify-between hover:bg-muted transition-colors text-xs text-muted-foreground"
          >
            <span className="flex items-center gap-2">
              {showIncompatible ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
              Incompatible Schema: These label sets don&apos;t match the
              rubric&apos;s output schema ({incompatibleLabelSets.length})
            </span>
          </button>

          {showIncompatible && (
            <div className="overflow-auto custom-scrollbar max-h-[300px]">
              <Table className="min-w-full">
                <TableBody>
                  {incompatibleTable.getRowModel().rows.map((row, index) => {
                    const isActive = selectedLabelSetId === row.original.id;
                    const nextIsActive =
                      index < incompatibleTable.getRowModel().rows.length - 1 &&
                      incompatibleTable.getRowModel().rows[index + 1].original
                        .id === selectedLabelSetId;

                    return (
                      <TableRow
                        key={row.id}
                        data-state={isActive ? 'active' : undefined}
                        onClick={() => onSelectLabelSet(row.original.id)}
                        className={cn(
                          'text-xs cursor-pointer select-none group',
                          isActive
                            ? 'bg-indigo-bg/80 hover:bg-indigo-bg/80'
                            : 'hover:bg-muted',
                          nextIsActive ? 'border-b-transparent' : 'border-b'
                        )}
                        style={{
                          height: ROW_HEIGHT_PX,
                          boxShadow: isActive
                            ? 'inset 0 0 0 1px hsl(var(--indigo-border))'
                            : undefined,
                        }}
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
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
