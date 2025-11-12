'use client';

import { useState, useMemo } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  useGetLabelsForAgentRunQuery,
  useGetLabelSetsQuery,
  useDeleteLabelMutation,
  type Label as LabelType,
  type LabelSet,
} from '@/app/api/labelApi';
import {
  Loader2,
  Tag,
  Tags,
  Pencil,
  Trash2,
  ChevronDown,
  Plus,
} from 'lucide-react';
import { useParams } from 'next/navigation';
import LabelEditForm from './LabelEditForm';
import { Label } from '@/components/ui/label';
import LabelSetsDialog from '../../components/LabelSetsDialog';
import { toast } from '@/hooks/use-toast';
import { useSearchParams } from 'next/navigation';

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';
import { useLabelSets } from '@/providers/use-label-sets';

interface AgentRunLabelsProps {
  agentRunId: string;
  collectionId: string;
}

type ViewMode = 'list' | 'edit';

export default function AgentRunLabels({
  agentRunId,
  collectionId,
}: AgentRunLabelsProps) {
  //*****************************//
  // Temp query params for Sonia //
  //*****************************//

  const searchParams = useSearchParams();
  const disableAddLabels = searchParams.get('add_labels') === 'false';

  //************//
  // View state //
  //************//

  // Whether to show the list of agent run labels or the label form
  const [viewMode, setViewMode] = useState<ViewMode>('list');

  // Whether to show the other labels in the collapsible section
  const [isOtherLabelsOpen, setIsOtherLabelsOpen] = useState(false);

  // Whether to show the label sets dialog
  const [isLabelSetsDialogOpen, setIsLabelSetsDialogOpen] = useState(false);

  //***************//
  // Data fetching //
  //***************//

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

  // Fetch the active label set from local storage
  const { activeLabelSet, setLabelSet: setActiveLabelSet } =
    useLabelSets(collectionId);

  //****************************//
  // Label data transformations //
  //****************************//

  // Create a map from label set id to labels
  const labelSetIdsToLabels = useMemo(() => {
    return labels?.reduce(
      (acc, label) => {
        acc[label.label_set_id] = label;
        return acc;
      },
      {} as Record<string, LabelType>
    );
  }, [labels]);

  // Create a map from label set id to label sets
  const labelSetIdsToLabelSets = useMemo(() => {
    return labelSets?.reduce(
      (acc, labelSet) => {
        acc[labelSet.id] = labelSet;
        return acc;
      },
      {} as Record<string, LabelSet>
    );
  }, [labelSets]);

  // Split labels into active and other labels
  const { activeLabel, otherLabels } = useMemo(() => {
    return {
      activeLabel: activeLabelSet
        ? labelSetIdsToLabels?.[activeLabelSet?.id]
        : null,
      otherLabels: labels?.filter(
        (label) => label.label_set_id !== activeLabelSet?.id
      ),
    };
  }, [labels, activeLabelSet]);

  const activeLabelSetHasLabel = useMemo(() => {
    if (!activeLabelSet) return false;
    return labelSetIdsToLabels?.[activeLabelSet.id] ? true : false;
  }, [labelSetIdsToLabels, activeLabelSet]);

  //****************//
  // Event handlers //
  //****************//

  const handleEditClick = (labelSet: LabelSet) => {
    setActiveLabelSet(labelSet);
    setViewMode('edit');
  };

  const Header = ({ handleBackToList }: { handleBackToList?: () => void }) => {
    const hasLabelSets = labelSets?.length && labelSets.length > 0;

    return (
      <>
        <div className="flex 2xl:items-end 2xl:justify-between 2xl:flex-row flex-col gap-2">
          <div className="flex flex-col gap-1">
            <h4 className="font-semibold text-sm">Labels for this Agent Run</h4>

            <span className="text-xs text-muted-foreground">
              Click on a label to edit it.
            </span>
          </div>
          {handleBackToList ? (
            <Button
              variant="outline"
              size="sm"
              onClick={handleBackToList}
              className="w-fit"
            >
              Back
            </Button>
          ) : (
            <div className="flex gap-2  flex-col xl:flex-row">
              {activeLabelSet && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 gap-2  w-full text-xs"
                  disabled={disableAddLabels}
                  onClick={() => setIsLabelSetsDialogOpen(true)}
                >
                  <Tags className="h-3.5 w-3.5" />
                  Select a different set
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 gap-1 w-full text-xs"
                disabled={
                  disableAddLabels ||
                  (activeLabelSet ? activeLabelSetHasLabel : false)
                }
                onClick={() => {
                  if (activeLabelSet) {
                    setViewMode('edit');
                  } else {
                    setIsLabelSetsDialogOpen(true);
                  }
                }}
              >
                <Plus className="size-3.5" />
                {activeLabelSet ? (
                  <span className="truncate">
                    Add label:{' '}
                    <span className="font-mono text-blue-text">
                      {activeLabelSet.name}
                    </span>
                  </span>
                ) : hasLabelSets ? (
                  <span>Select label set</span>
                ) : (
                  <span>Create a label set</span>
                )}
              </Button>
            </div>
          )}
        </div>
      </>
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
  if (viewMode === 'edit' && activeLabelSet) {
    return (
      <div className="h-full flex flex-col space-y-2">
        <Header handleBackToList={() => setViewMode('list')} />

        <ScrollArea className="flex-1 border rounded-md p-2.5 bg-card">
          <LabelEditForm
            labelSet={activeLabelSet}
            existingLabel={activeLabel || undefined}
            onSuccess={() => setViewMode('list')}
          />
        </ScrollArea>
      </div>
    );
  }

  // Show list view
  return (
    <>
      <div className="h-full flex flex-col space-y-2">
        <Header />

        <ScrollArea className="flex-1 rounded-md ">
          <div className="space-y-2">
            {labels?.length === 0 && !activeLabelSet && (
              <Card className="flex items-center justify-center min-h-24 shadow-sm rounded-md">
                <p className="text-xs text-muted-foreground text-center">
                  {labelSets?.length === 0
                    ? 'No label sets exist yet. Create one to start labeling.'
                    : 'No labels for this agent run. Select a label set to add one.'}
                </p>
              </Card>
            )}

            {/* Active label set label */}
            {activeLabelSet &&
              (activeLabel ? (
                <AgentRunLabelCard
                  key={activeLabel.id}
                  label={activeLabel}
                  labelSet={activeLabelSet!}
                  handleEditClick={handleEditClick}
                />
              ) : (
                <Card className="flex items-center justify-center min-h-24 shadow-sm rounded-md">
                  <p className="text-xs text-muted-foreground text-center">
                    <span>
                      No label for set{' '}
                      <span className="font-mono text-blue-text">
                        {activeLabelSet?.name}
                      </span>
                    </span>
                  </p>
                </Card>
              ))}

            {/* Other labels (collapsible) */}
            {otherLabels && otherLabels.length > 0 && (
              <Collapsible
                open={isOtherLabelsOpen}
                onOpenChange={setIsOtherLabelsOpen}
              >
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full h-8 text-xs text-muted-foreground hover:text-foreground flex items-center justify-between px-2"
                  >
                    <span>Other Labels ({otherLabels.length})</span>
                    <ChevronDown
                      className={`h-4 w-4 transition-transform ${
                        isOtherLabelsOpen ? 'rotate-180' : ''
                      }`}
                    />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="space-y-2 mt-2">
                  {otherLabels.map((label) => {
                    const labelSet =
                      labelSetIdsToLabelSets?.[label.label_set_id];
                    if (!labelSet) {
                      return null;
                    }
                    return (
                      <AgentRunLabelCard
                        key={label.id}
                        label={label}
                        labelSet={labelSet}
                        handleEditClick={handleEditClick}
                      />
                    );
                  })}
                </CollapsibleContent>
              </Collapsible>
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Label Sets Dialog */}
      <LabelSetsDialog
        open={isLabelSetsDialogOpen}
        onOpenChange={setIsLabelSetsDialogOpen}
        onImportLabelSet={setActiveLabelSet} // Just set as the active label set
        activeLabelSetId={activeLabelSet?.id}
      />
    </>
  );
}

interface AgentRunLabelCardProps {
  label: LabelType;
  labelSet: LabelSet;
  handleEditClick: (labelSet: LabelSet) => void;
}

const AgentRunLabelCard = ({
  label,
  labelSet,
  handleEditClick,
}: AgentRunLabelCardProps) => {
  const { collection_id: collectionId, agent_run_id: agentRunId } = useParams<{
    collection_id: string;
    agent_run_id: string;
  }>();

  const [deleteLabelId, setDeleteLabelId] = useState<string | null>(null);
  const [deleteLabel] = useDeleteLabelMutation();

  if (label.id === undefined || label.id === null) {
    return null;
  }

  const labelId = label.id;

  const handleDeleteLabel = async (labelId: string) => {
    try {
      await deleteLabel({ collectionId, labelId, agentRunId }).unwrap();
      toast({
        title: 'Label deleted',
        description: 'The label has been successfully deleted.',
      });
      setDeleteLabelId(null);
    } catch (error) {
      console.error('Failed to delete label:', error);
      toast({
        title: 'Error',
        description: 'Failed to delete label',
        variant: 'destructive',
      });
    }
  };

  return (
    <Card
      key={label.id}
      className="p-3 shadow-sm rounded-md cursor-pointer hover:bg-accent/80 transition-all group relative"
      onClick={() => handleEditClick(labelSet)}
    >
      <div className="space-y-1 flex flex-col">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <Tag className="size-3 text-blue-border" />
            <Label className="text-xs font-medium">{labelSet.name}</Label>
          </div>

          {/* Action buttons for editing and deletion */}
          <div
            className={cn(
              'flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity',
              deleteLabelId !== null ? 'opacity-100' : 'opacity-0' // Hold the buttons visible while deleting
            )}
          >
            <Button
              size="sm"
              variant="ghost"
              className="h-6 w-6 p-0"
              onClick={(e) => {
                e.stopPropagation();
                handleEditClick(labelSet);
              }}
            >
              <Pencil className="h-3 w-3" />
            </Button>

            <Popover
              open={deleteLabelId === labelId}
              onOpenChange={(open) => setDeleteLabelId(open ? labelId : null)}
            >
              <PopoverTrigger asChild>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-64 p-3" align="end">
                <div className="space-y-3">
                  <div className="text-sm font-medium">Delete this label?</div>
                  <div className="text-xs text-muted-foreground">
                    This action cannot be undone.
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeleteLabelId(null);
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
                        handleDeleteLabel(labelId);
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>

        <div className="pt-2 border-t">
          <div className="space-y-1">
            {Object.entries(labelSet.label_schema.properties).map(
              ([key, _]) => {
                const displayValue = String(label.label_value[key]);
                1;
                return (
                  <div key={key} className="text-xs">
                    <span className="font-medium">{key}:</span>{' '}
                    {label.label_value[key] !== undefined &&
                    label.label_value[key] !== null ? (
                      <span className="text-foreground">{displayValue}</span>
                    ) : (
                      <span className="text-muted-foreground italic">
                        (empty)
                      </span>
                    )}
                  </div>
                );
              }
            )}
          </div>
        </div>
      </div>
    </Card>
  );
};
