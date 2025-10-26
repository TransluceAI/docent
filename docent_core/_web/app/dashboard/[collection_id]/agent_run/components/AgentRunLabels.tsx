'use client';

import { useState, useMemo } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  useGetLabelsForAgentRunQuery,
  useGetLabelSetsQuery,
  useCreateLabelMutation,
  type Label as LabelType,
  type LabelSet,
} from '@/app/api/labelApi';
import { Loader2, Plus, Tag } from 'lucide-react';
import LabelEditForm from './LabelEditForm';
import { Label } from '@/components/ui/label';
import { SchemaDefinition } from '@/app/types/schema';
import LabelSetsDialog from '../../components/LabelSetsDialog';
import { toast } from '@/hooks/use-toast';
import { useSearchParams } from 'next/navigation';

interface AgentRunLabelsProps {
  agentRunId: string;
  collectionId: string;
}

interface LabelWithSet {
  label: LabelType;
  labelSet: LabelSet;
}

type ViewMode = 'list' | 'edit' | 'create';

export default function AgentRunLabels({
  agentRunId,
  collectionId,
}: AgentRunLabelsProps) {
  const searchParams = useSearchParams();
  const disableAddLabels = searchParams.get('add_labels') === 'false';

  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [selectedLabelSetId, setSelectedLabelSetId] = useState<string | null>(
    null
  );
  const [isLabelSetsDialogOpen, setIsLabelSetsDialogOpen] = useState(false);

  const [createLabel] = useCreateLabelMutation();

  // Fetch labels for this agent run
  const {
    data: labels,
    isLoading: isLoadingLabels,
    error: labelsError,
  } = useGetLabelsForAgentRunQuery({ collectionId, agentRunId });

  // Fetch all label sets
  const {
    data: labelSets,
    isLoading: isLoadingLabelSets,
    error: labelSetsError,
  } = useGetLabelSetsQuery({ collectionId });

  // Group labels by label set
  const labelsWithSets: LabelWithSet[] = useMemo(() => {
    if (!labels || !labelSets) return [];

    return labels
      .map((label) => {
        const labelSet = labelSets.find((ls) => ls.id === label.label_set_id);
        if (!labelSet) return null;
        return { label, labelSet };
      })
      .filter((item): item is LabelWithSet => item !== null);
  }, [labels, labelSets]);

  // Get the selected label and label set for editing
  const selectedLabelWithSet = useMemo(() => {
    if (!selectedLabelSetId || !labelsWithSets) return null;
    return labelsWithSets.find(
      (item) => item.labelSet.id === selectedLabelSetId
    );
  }, [selectedLabelSetId, labelsWithSets]);

  const handleEditClick = (labelSetId: string) => {
    setSelectedLabelSetId(labelSetId);
    setViewMode('edit');
  };

  const handleBackToList = () => {
    setSelectedLabelSetId(null);
    setViewMode('list');
  };

  const handleSuccess = () => {
    handleBackToList();
  };

  const handleAddLabelFromSet = async (labelSet: LabelSet) => {
    try {
      // Create an empty label with the schema structure
      const emptyLabelValue: Record<string, any> = {};
      const schema = labelSet.label_schema as SchemaDefinition;

      // Initialize all schema properties with appropriate empty values
      Object.keys(schema.properties).forEach((key) => {
        emptyLabelValue[key] = undefined;
      });

      await createLabel({
        collectionId,
        label: {
          label_set_id: labelSet.id,
          label_value: emptyLabelValue,
          agent_run_id: agentRunId,
        },
      }).unwrap();

      // Close the dialog
      setIsLabelSetsDialogOpen(false);

      // Open the edit form
      setSelectedLabelSetId(labelSet.id);
      setViewMode('edit');
    } catch (error) {
      console.error('Failed to create label:', error);
      toast({
        title: 'Error',
        description: 'Failed to create label',
        variant: 'destructive',
      });
    }
  };

  // Get list of label set IDs that already have labels for this agent run
  const existingLabelSetIds = useMemo(() => {
    return labelsWithSets.map((item) => item.labelSet.id);
  }, [labelsWithSets]);

  const renderLabelContent = (label: LabelType, schema: SchemaDefinition) => {
    return (
      <div className="space-y-1">
        {Object.entries(schema.properties).map(([key, _]) => {
          const displayValue = String(label.label_value[key]);

          return (
            <div key={key} className="text-xs">
              <span className="font-medium">{key}:</span>{' '}
              {label.label_value[key] !== undefined &&
              label.label_value[key] !== null ? (
                <span className="text-foreground">{displayValue}</span>
              ) : (
                <span className="text-muted-foreground italic">(empty)</span>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  if (isLoadingLabels || isLoadingLabelSets) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (labelsError || labelSetsError) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm text-destructive">Failed to load labels</p>
      </div>
    );
  }

  // Show edit view
  if (viewMode === 'edit' && selectedLabelWithSet) {
    return (
      <div className="h-full flex flex-col space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex flex-col gap-1">
            <h4 className="font-semibold text-sm">Edit Label</h4>

            <span className="text-xs text-muted-foreground">
              Edit the label for the selected label set.
            </span>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleBackToList}
            className="w-fit"
          >
            Close
          </Button>
        </div>
        <ScrollArea className="flex-1 border rounded-md p-2.5 bg-card">
          <LabelEditForm
            labelSet={selectedLabelWithSet.labelSet}
            existingLabel={selectedLabelWithSet.label}
            agentRunId={agentRunId}
            collectionId={collectionId}
            onSuccess={handleSuccess}
          />
        </ScrollArea>
      </div>
    );
  }

  // Show list view
  return (
    <div className="h-full flex flex-col space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <h4 className="font-semibold text-sm">Labels for this Agent Run</h4>

          <span className="text-xs text-muted-foreground">
            Click on a label to edit it.
          </span>
        </div>

        <Button
          size="sm"
          variant="outline"
          disabled={disableAddLabels}
          className="h-7 text-xs gap-2"
          onClick={() => setIsLabelSetsDialogOpen(true)}
        >
          <Plus className="h-4 w-4" />
          Add Label
        </Button>
      </div>

      <ScrollArea className="flex-1 border rounded-md p-3 bg-muted">
        <div className="space-y-2">
          {labelsWithSets.length === 0 && (
            <Card className="p-4 shadow-sm rounded-md">
              <p className="text-xs text-muted-foreground text-center">
                No labels for this agent run
              </p>
            </Card>
          )}

          {/* Existing labels */}
          {labelsWithSets.map(({ label, labelSet }) => (
            <Card
              key={label.id}
              className="p-3 shadow-sm rounded-md cursor-pointer hover:bg-accent/80 transition-all"
              onClick={() => handleEditClick(labelSet.id)}
            >
              <div className="space-y-1 flex flex-col">
                <div className="flex items-center gap-1">
                  <Tag className="size-3 text-blue-border" />
                  <Label className="text-xs font-medium">{labelSet.name}</Label>
                </div>
                <div className="pt-2 border-t">
                  {renderLabelContent(label, labelSet.label_schema)}
                </div>
              </div>
            </Card>
          ))}
        </div>
      </ScrollArea>
      <LabelSetsDialog
        open={isLabelSetsDialogOpen}
        onOpenChange={setIsLabelSetsDialogOpen}
        onImportLabelSet={handleAddLabelFromSet}
        existingLabelSetIds={existingLabelSetIds}
        tooltipText={{
          active: 'Label already exists',
          inactive: 'Create label from this set',
        }}
      />
    </div>
  );
}
