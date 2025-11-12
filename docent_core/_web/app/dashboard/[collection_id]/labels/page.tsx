'use client';

import { useState, useMemo } from 'react';

import {
  useGetLabelSetsWithCountsQuery,
  useDeleteLabelSetMutation,
} from '@/app/api/labelApi';
import LabelSetsTable, {
  type LabelSetTableRow,
} from '../components/LabelSetsTable';
import { cn } from '@/lib/utils';
import LabelSetEditor from '../components/LabelSetEditor';
import { useToast } from '@/hooks/use-toast';
import { useParams } from 'next/navigation';
import { SchemaDefinition } from '@/app/types/schema';
import { Button } from '@/components/ui/button';
import { Plus } from 'lucide-react';
import { Separator } from '@/components/ui/separator';

export default function LabelsPage() {
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
      })
      .catch((error) => {
        toast({
          title: 'Failed to delete label set',
          description: 'An error occurred while deleting the label set.',
          variant: 'destructive',
        });
      });
  };

  return (
    <div className="flex-1 flex flex-row min-h-0 bg-background rounded-lg border">
      {/* Left Side - Table */}
      <div className="w-1/2 flex flex-col h-full min-h-0 p-3 space-y-3">
        <div className="flex items-center justify-end">
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
          onDeleteLabelSet={handleDeleteLabelSet}
          isLoading={isLoading}
        />
      </div>

      <Separator orientation="vertical" />

      {/* Right Side - Detail Panel */}
      <div className={'w-1/2 min-h-0 p-3 items-center justify-center flex'}>
        <div
          className={cn(
            'w-full h-full flex items-center justify-center rounded-md p-3',
            !selectedLabelSetId && !isCreateMode && 'border-dashed border'
          )}
        >
          <LabelSetEditor
            labelSetId={selectedLabelSetId}
            isCreateMode={isCreateMode}
            onCreateSuccess={handleCreateSuccess}
          />
        </div>
      </div>
    </div>
  );
}
