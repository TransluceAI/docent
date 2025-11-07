'use client';

import { useState, useMemo } from 'react';

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  useGetLabelSetsWithCountsQuery,
  useDeleteLabelSetMutation,
  type LabelSet,
} from '@/app/api/labelApi';
import LabelSetsTable, { type LabelSetTableRow } from './LabelSetsTable';
import { cn } from '@/lib/utils';
import LabelSetEditor from './LabelSetEditor';
import { useToast } from '@/hooks/use-toast';
import { useParams } from 'next/navigation';
import { SchemaDefinition } from '@/app/types/schema';
import { Button } from '@/components/ui/button';
import { Plus } from 'lucide-react';

interface LabelSetsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImportLabelSet?: (labelSet: LabelSet) => void;
  onClearActiveLabelSet?: () => void;
  currentRubricSchema?: Record<string, any>;
  activeLabelSetId?: string;
}

export default function LabelSetsDialog({
  open,
  onOpenChange,
  onImportLabelSet,
  onClearActiveLabelSet,
  currentRubricSchema,
  activeLabelSetId,
}: LabelSetsDialogProps) {
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();

  const [selectedLabelSetId, setSelectedLabelSetId] = useState<string | null>(
    null
  );
  const [isCreateMode, setIsCreateMode] = useState(false);
  const { toast } = useToast();

  // Fetch all label sets with counts
  const { data: allLabelSets, isLoading } = useGetLabelSetsWithCountsQuery({
    collectionId,
  });

  const [deleteLabelSet] = useDeleteLabelSetMutation();

  const labelSetRows: LabelSetTableRow[] = useMemo(() => {
    if (!allLabelSets) return [];

    return allLabelSets.map((ls) => ({
      id: ls.id,
      name: ls.name,
      description: ls.description ?? null,
      labelCount: ls.label_count,
      labelSchema: ls.label_schema as SchemaDefinition,
    }));
  }, [allLabelSets]);

  const handleSelectLabelSet = (id: string) => {
    setSelectedLabelSetId(id);
    setIsCreateMode(false);
  };

  const handleCreateNewLabelSet = () => {
    setSelectedLabelSetId(null);
    setIsCreateMode(true);
  };

  const handleCreateSuccess = (newLabelSetId: string) => {
    setSelectedLabelSetId(newLabelSetId);
    setIsCreateMode(false);
  };

  const handleDeleteLabelSet = async (labelSetId: string) => {
    await deleteLabelSet({ collectionId, labelSetId })
      .unwrap()
      .then(() => {
        toast({
          title: 'Label set deleted',
          description: 'The label set has been successfully deleted.',
        });

        // Clear selection if the deleted set was selected
        if (selectedLabelSetId === labelSetId) {
          setSelectedLabelSetId(null);
          setIsCreateMode(false);
        }

        // Clear active label set if the deleted set was active
        if (activeLabelSetId === labelSetId && onClearActiveLabelSet) {
          onClearActiveLabelSet();
        }
      })
      .catch((error) => {
        toast({
          title: 'Failed to delete label set',
          description: 'An error occurred while deleting the label set.',
          variant: 'destructive',
        });
      });
  };

  const handleImportLabelSet = (labelSet: LabelSet) => {
    if (onImportLabelSet) {
      onImportLabelSet(labelSet);
      toast({
        title: 'Label set activated',
        description: `"${labelSet.name}" is now the active label set.`,
      });
    }
  };

  const isSchemaCompatible = (row: LabelSetTableRow) => {
    if (!currentRubricSchema) return true;
    return (
      JSON.stringify(row.labelSchema) === JSON.stringify(currentRubricSchema)
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[90vw] h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Label Sets</DialogTitle>
        </DialogHeader>
        <div className="flex-1 flex space-x-4 min-h-0">
          {/* Left Side - Table */}
          <div className="w-1/2 flex flex-col h-full min-h-0 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground font-medium">
                Select a label set to add labels to.
              </span>
              <Button
                size="sm"
                onClick={handleCreateNewLabelSet}
                className="gap-1.5 h-7 text-xs"
              >
                <Plus className="h-3 w-3" />
                Create New
              </Button>
            </div>
            <LabelSetsTable
              labelSets={labelSetRows}
              selectedLabelSetId={selectedLabelSetId}
              onSelectLabelSet={handleSelectLabelSet}
              onImportLabelSet={
                onImportLabelSet ? handleImportLabelSet : undefined
              }
              onDeleteLabelSet={handleDeleteLabelSet}
              isValidRow={currentRubricSchema ? isSchemaCompatible : undefined}
              activeLabelSetId={activeLabelSetId}
              isLoading={isLoading}
            />
          </div>

          {/* Right Side - Detail Panel */}
          <div
            className={cn(
              'w-1/2 min-h-0 rounded-md p-3 items-center justify-center flex',
              selectedLabelSetId ? 'border' : 'border-dashed border'
            )}
          >
            <LabelSetEditor
              labelSetId={selectedLabelSetId}
              isCreateMode={isCreateMode}
              onCreateSuccess={handleCreateSuccess}
              prefillSchema={currentRubricSchema}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
