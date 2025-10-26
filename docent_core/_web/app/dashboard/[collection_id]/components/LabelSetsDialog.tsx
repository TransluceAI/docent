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

interface LabelSetsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImportLabelSet?: (labelSet: LabelSet) => void;
  onClearActiveLabelSet?: () => void;
  currentRubricSchema?: Record<string, any>;
  activeLabelSetId?: string;
  existingLabelSetIds?: string[];
  tooltipText?: {
    active: string;
    inactive: string;
  };
}

export default function LabelSetsDialog({
  open,
  onOpenChange,
  onImportLabelSet,
  onClearActiveLabelSet,
  currentRubricSchema,
  activeLabelSetId,
  existingLabelSetIds = [],
  tooltipText,
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
      const description = currentRubricSchema
        ? `"${labelSet.name}" is now the active label set.`
        : `Added label for set: "${labelSet.name}".`;
      toast({
        title: 'Label set activated',
        description: description,
      });
    }
  };

  const isSchemaCompatible = (row: LabelSetTableRow) => {
    if (!currentRubricSchema) return true;
    return (
      JSON.stringify(row.labelSchema) === JSON.stringify(currentRubricSchema)
    );
  };

  const hasExistingLabel = (row: LabelSetTableRow) => {
    return !existingLabelSetIds.includes(row.id);
  };

  // Determine incompatibility message based on context
  const incompatibleHeaderText = currentRubricSchema
    ? "Incompatible Schema: These label sets don't match the rubric's output schema"
    : 'Already Added: These label sets already have labels for this agent run';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[90vw] h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Label Sets</DialogTitle>
        </DialogHeader>
        <div className="flex-1 flex space-x-4 min-h-0">
          {/* Left Side - Table */}
          <div className="w-1/2 min-h-0">
            <LabelSetsTable
              labelSets={labelSetRows}
              selectedLabelSetId={selectedLabelSetId}
              onSelectLabelSet={handleSelectLabelSet}
              onCreateNewLabelSet={handleCreateNewLabelSet}
              onImportLabelSet={
                onImportLabelSet ? handleImportLabelSet : undefined
              }
              onDeleteLabelSet={handleDeleteLabelSet}
              isValidRow={
                currentRubricSchema ? isSchemaCompatible : hasExistingLabel
              }
              activeLabelSetId={activeLabelSetId}
              isLoading={isLoading}
              tooltipText={tooltipText}
              incompatibleHeaderText={incompatibleHeaderText}
            />
          </div>

          {/* Right Side - Detail Panel */}
          <div
            className={cn(
              'w-1/2 min-h-0 rounded-md p-4 items-center justify-center flex',
              selectedLabelSetId ? 'border' : 'border-dashed border'
            )}
          >
            <LabelSetEditor
              labelSetId={selectedLabelSetId}
              isCreateMode={isCreateMode}
              collectionId={collectionId}
              onCreateSuccess={handleCreateSuccess}
              prefillSchema={currentRubricSchema}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
