'use client';

import React, { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader2, Trash2 } from 'lucide-react';

import { Separator } from '@/components/ui/separator';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { toast } from 'sonner';

import {
  useGetResultSetsQuery,
  useDeleteResultSetMutation,
  ResultSetResponse,
} from '@/app/api/resultSetApi';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

export default function ResultsPage() {
  const params = useParams();
  const router = useRouter();
  const collectionId = params.collection_id as string;
  const hasWritePermission = useHasCollectionWritePermission();
  const [deletePopoverId, setDeletePopoverId] = useState<string | null>(null);

  const {
    data: resultSets = [],
    isLoading,
    error,
  } = useGetResultSetsQuery({ collectionId }, { skip: !collectionId });

  const [deleteResultSet] = useDeleteResultSetMutation();

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  const handleRowClick = (resultSet: ResultSetResponse) => {
    const identifier = resultSet.name || resultSet.id;
    router.push(
      `/dashboard/${collectionId}/results/${encodeURIComponent(identifier)}`
    );
  };

  const handleDelete = async (resultSet: ResultSetResponse) => {
    const identifier = resultSet.name || resultSet.id;
    try {
      await deleteResultSet({
        collectionId,
        resultSetIdOrName: identifier,
      }).unwrap();
      toast.success('Result set deleted successfully');
      setDeletePopoverId(null);
    } catch {
      toast.error('Failed to delete result set');
    }
  };

  if (isLoading && resultSets.length === 0) {
    return (
      <div className="flex-1 flex bg-card min-h-0 shrink-0 border rounded-lg p-3">
        <div className="flex items-center justify-center w-full py-8">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-card min-h-0 shrink-0 border rounded-lg p-4">
      <div className="space-y-1 mb-4">
        <div className="flex justify-between items-center">
          <div>
            <div className="text-sm font-semibold tracking-tight">
              Result Sets
            </div>
            <div className="text-xs text-muted-foreground">
              View LLM analysis result sets for this collection
            </div>
          </div>
        </div>
      </div>

      <Separator className="my-4" />

      {error && (
        <div className="text-red-500 text-sm mb-4 p-3 bg-red-50 rounded">
          Failed to load result sets
        </div>
      )}

      {resultSets.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground text-xs">
          No result sets found for this collection.
        </div>
      ) : (
        <div className="flex-1 overflow-auto min-h-0">
          <Table>
            <TableHeader className="bg-secondary sticky top-0">
              <TableRow>
                <TableHead className="py-2.5 font-medium text-xs text-muted-foreground">
                  Name
                </TableHead>
                <TableHead className="py-2.5 font-medium text-xs text-muted-foreground">
                  Created At
                </TableHead>
                <TableHead className="py-2.5 font-medium text-xs text-muted-foreground text-right">
                  Results
                </TableHead>
                <TableHead className="py-2.5 font-medium text-xs text-muted-foreground">
                  Preview
                </TableHead>
                {hasWritePermission && (
                  <TableHead className="py-2.5 font-medium text-xs text-muted-foreground w-[60px]">
                    Actions
                  </TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {resultSets.map((resultSet) => (
                <TableRow
                  key={resultSet.id}
                  className="cursor-pointer hover:bg-secondary/50"
                  onClick={() => handleRowClick(resultSet)}
                >
                  <TableCell className="py-2 text-xs font-medium">
                    {resultSet.name || (
                      <span className="text-muted-foreground italic">
                        {resultSet.id.slice(0, 8)}...
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="py-2 text-xs text-muted-foreground">
                    {formatDate(resultSet.created_at)}
                  </TableCell>
                  <TableCell className="py-2 text-xs text-muted-foreground text-right">
                    {resultSet.result_count ?? 0}
                  </TableCell>
                  <TableCell className="py-2 text-xs text-muted-foreground max-w-[300px] truncate">
                    {resultSet.first_prompt_preview || '-'}
                  </TableCell>
                  {hasWritePermission && (
                    <TableCell
                      className="py-2"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Popover
                        open={deletePopoverId === resultSet.id}
                        onOpenChange={(open) =>
                          setDeletePopoverId(open ? resultSet.id : null)
                        }
                      >
                        <PopoverTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-muted-foreground hover:text-destructive"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-64 p-3" align="end">
                          <div className="space-y-3">
                            <div className="text-sm font-medium">
                              Delete result set?
                            </div>
                            <div className="text-xs text-muted-foreground">
                              This will permanently delete{' '}
                              {resultSet.name ? (
                                <>&quot;{resultSet.name}&quot;</>
                              ) : (
                                'this result set'
                              )}{' '}
                              and all {resultSet.result_count ?? 0} results.
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
                                className="h-7 text-xs"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDelete(resultSet);
                                }}
                              >
                                Delete
                              </Button>
                            </div>
                          </div>
                        </PopoverContent>
                      </Popover>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
