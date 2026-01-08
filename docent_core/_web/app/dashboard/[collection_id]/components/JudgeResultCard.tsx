import React, { useEffect, useMemo, useState } from 'react';
import {
  useCreateLabelMutation,
  useUpdateLabelMutation,
  useDeleteLabelMutation,
  Label,
  useCreateLabelSetMutation,
} from '@/app/api/labelApi';
import { SchemaDefinition } from '@/app/types/schema';
import { toast } from 'sonner';
import posthog from 'posthog-js';
import { ExternalLink } from 'lucide-react';
import { useParams, useRouter } from 'next/navigation';
import { useLabelSets } from '@/providers/use-label-sets';
import { AgentRunJudgeResults } from '@/app/api/rubricApi';
import LabelSetsDialog from './LabelSetsDialog';
import { findModalResult } from '../utils/findModalResult';
import { SchemaValueRenderer } from './SchemaValueRenderer';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

// =============================================================================
// LabelSetMenuItems - Kept here as it uses context-specific hooks
// =============================================================================

interface LabelSetMenuItemsProps {
  onLabelSetCreated: (labelSetId: string) => void;
  schema: SchemaDefinition;
}

const LabelSetMenuItems = ({
  onLabelSetCreated,
  schema,
}: LabelSetMenuItemsProps) => {
  const [newLabelSetName, setNewLabelSetName] = useState('');
  const [showLabelSetsDialog, setShowLabelSetsDialog] = useState(false);

  const { collection_id: collectionId, rubric_id: rubricId } = useParams<{
    collection_id: string;
    rubric_id: string;
  }>();
  const [createLabelSet] = useCreateLabelSetMutation();
  const { setLabelSet: setActiveLabelSet } = useLabelSets(rubricId);

  const handleCreateLabelSet = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newLabelSetName.trim();
    if (!trimmed || !collectionId) return;

    await createLabelSet({
      collectionId,
      name: trimmed,
      label_schema: schema,
    })
      .unwrap()
      .then((result) => {
        const newLabelSet = {
          id: result.label_set_id,
          name: trimmed,
          description: undefined,
          label_schema: schema,
        };
        setActiveLabelSet(newLabelSet);
        onLabelSetCreated(result.label_set_id);
        setNewLabelSetName('');
      })
      .catch((error) => {
        console.error('Failed to create label set:', error);
        toast.error('Failed to create label set');
      });
  };

  const handleImportLabelSet = (labelSet: any) => {
    setActiveLabelSet(labelSet);
    onLabelSetCreated(labelSet.id);
    setShowLabelSetsDialog(false);
  };

  return (
    <>
      <div className="space-y-1">
        <button
          type="button"
          onClick={() => setShowLabelSetsDialog(true)}
          className="w-full text-xs flex gap-2 items-center hover:bg-muted rounded px-2 py-2"
        >
          Select an existing label set
          <ExternalLink className="size-3" />
        </button>
        <form onSubmit={handleCreateLabelSet}>
          <input
            type="text"
            value={newLabelSetName}
            onChange={(e) => setNewLabelSetName(e.target.value)}
            placeholder="Or create new label set..."
            className="w-full text-xs border rounded px-2 py-1"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setNewLabelSetName('');
              }
            }}
          />
        </form>
      </div>
      <LabelSetsDialog
        open={showLabelSetsDialog}
        onOpenChange={setShowLabelSetsDialog}
        onImportLabelSet={handleImportLabelSet}
        currentRubricSchema={schema}
      />
    </>
  );
};

// =============================================================================
// Normalize Labels Helper
// =============================================================================

/**
 * Normalizes label state by extracting text from citation objects.
 * If a property is defined as a string in the schema but the value is an object
 * with a 'text' property (e.g., {text: string, citations: InlineCitation[]}),
 * this function extracts just the text value.
 */
const normalizeLabelsWithCitations = (
  labelState: Record<string, any>,
  schema?: SchemaDefinition
): Record<string, any> => {
  if (!schema) return labelState;

  return Object.fromEntries(
    Object.entries(labelState).map(([key, value]) => {
      const property = schema.properties?.[key];

      // If the property is a string, and the value is an object with a text property, pull that out
      if (
        property &&
        property.type === 'string' &&
        value &&
        typeof value === 'object' &&
        'text' in (value as Record<string, any>)
      ) {
        return [key, (value as { text: string }).text];
      }

      return [key, value];
    })
  );
};

// =============================================================================
// Main Component
// =============================================================================

interface JudgeResultCardProps {
  agentRunResult: AgentRunJudgeResults;
  schema: SchemaDefinition;
  labels: Label[];
  activeLabelSetId: string | null;
  showLabels: boolean;
}

const JudgeResultCard = ({
  agentRunResult,
  schema,
  labels,
  activeLabelSetId,
  showLabels,
}: JudgeResultCardProps) => {
  const agentRunId = agentRunResult.agent_run_id;
  const firstResult = useMemo(
    () => findModalResult(agentRunResult, schema),
    [agentRunResult, schema]
  );

  const { collection_id: collectionId, rubric_id: rubricId } = useParams<{
    collection_id: string;
    rubric_id: string;
  }>();
  const router = useRouter();

  const { activeLabelSet } = useLabelSets(rubricId);
  const [createLabel] = useCreateLabelMutation();
  const hasWritePermission = useHasCollectionWritePermission();
  const canEditLabels = showLabels && hasWritePermission;

  const navigateToAgentRun = () => {
    router.push(
      `/dashboard/${collectionId}/rubric/${rubricId}/agent_run/${agentRunId}/result/${firstResult.id}`
    );
  };

  const calculateAgreement = (
    key: string
  ): { agreed: number; total: number } | undefined => {
    const results = agentRunResult.results;
    if (results.length <= 1) return undefined;

    const firstValue = firstResult.output[key];

    // Skip agreement calculation for complex types (arrays and objects)
    if (typeof firstValue === 'object' && firstValue !== null) {
      return undefined;
    }

    const agreed = results.filter(
      (result) => result.output[key] === firstValue
    ).length;

    return { agreed, total: results.length };
  };

  const normalizedJudgeRunLabels = Object.fromEntries(
    labels.map((label) => [
      label.label_set_id,
      normalizeLabelsWithCitations(label.label_value, schema),
    ])
  );

  const [formState, setFormState] = useState(normalizedJudgeRunLabels);

  // Sync local form state when the server label changes (e.g., after async fetch)
  useEffect(() => {
    setFormState(normalizedJudgeRunLabels);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentRunId, labels]);

  const [updateLabel] = useUpdateLabelMutation();
  const [deleteLabel] = useDeleteLabelMutation();

  // Helper to get label values for the active label set
  const getLabelValues = (): Record<string, any> => {
    if (!activeLabelSetId || !formState[activeLabelSetId]) return {};
    return formState[activeLabelSetId];
  };

  const clearLabelField = async (key: string) => {
    if (!activeLabelSetId || !canEditLabels) return;
    const labelSetId = activeLabelSetId;
    // Find the label for this labelSetId
    const labelForSet = labels.find((l) => l.label_set_id === labelSetId);
    if (!labelForSet || !labelForSet.id || !collectionId) return;

    // Compute the new state
    const { [key]: _removed, ...currentFields } = formState[labelSetId] || {};

    // Update local form state
    setFormState((prev) => {
      const { [key]: _, ...rest } = prev[labelSetId] || {};
      return { ...prev, [labelSetId]: rest };
    });

    try {
      // If no fields left, delete the entire label
      if (Object.keys(currentFields).length === 0) {
        await deleteLabel({
          collectionId,
          labelId: labelForSet.id,
          agentRunId,
        }).unwrap();
      } else {
        // Otherwise update the label
        await updateLabel({
          collectionId,
          labelId: labelForSet.id,
          label_value: currentFields,
          agentRunId,
        }).unwrap();
      }
    } catch (error: any) {
      console.error('Failed to clear label field:', error.data || error);
      toast.error('Failed to clear label field');
    }
  };

  // Helper to check if labeling has started (any fields are filled for active label set)
  const hasStartedLabeling = () => {
    if (!activeLabelSetId || !formState[activeLabelSetId]) return false;
    return Object.keys(formState[activeLabelSetId]).length > 0;
  };

  // Helper to check if a field is required and unfilled
  // For nested paths, we check if the field is filled using the path as key
  // Note: schema.required only applies to top-level properties
  const isRequiredAndUnfilled = (path: string): boolean => {
    // For now, only check required on top-level keys (no dots or brackets)
    const isTopLevel = !path.includes('.') && !path.includes('[');
    const isRequired = isTopLevel && (schema.required?.includes(path) ?? false);
    const labelValues = getLabelValues();
    const isFilled = labelValues[path] !== undefined;
    return isRequired && !isFilled && hasStartedLabeling();
  };

  const save = async (key: string, value: any) => {
    if (!collectionId || !activeLabelSetId || !canEditLabels) return;
    const labelSetId = activeLabelSetId;

    // Update local state
    setFormState((prev) => ({
      ...prev,
      [labelSetId]: {
        ...prev[labelSetId],
        [key]: value,
      },
    }));

    // Check whether the label exists to either update or create
    const existingLabel = labels.find((l) => l.label_set_id === labelSetId);

    try {
      const labelData = {
        ...formState[labelSetId],
        [key]: value,
      };

      if (!existingLabel) {
        // Create new label
        await createLabel({
          collectionId,
          label: {
            label_set_id: labelSetId,
            label_value: labelData,
            agent_run_id: agentRunId,
          },
        }).unwrap();
      } else if (existingLabel && existingLabel.id) {
        // Update existing label
        await updateLabel({
          collectionId,
          labelId: existingLabel.id,
          label_value: labelData,
          agentRunId,
        }).unwrap();
      } else {
        throw new Error('No existing label found');
      }

      posthog.capture('label_form_submitted', {
        num_fields_filled: Object.keys(labelData).length,
        agent_run_id: agentRunId,
        label_set_id: labelSetId,
      });
    } catch (error: any) {
      console.error('Label operation failed:', error.data || error);
      toast.error(`Failed to ${existingLabel ? 'update' : 'create'} label`);
    }
  };

  return (
    <SchemaValueRenderer
      schema={schema}
      values={firstResult.output}
      labelValues={getLabelValues()}
      activeLabelSet={activeLabelSet}
      onSaveLabel={save}
      onClearLabel={clearLabelField}
      showLabels={showLabels}
      canEditLabels={canEditLabels}
      calculateAgreement={calculateAgreement}
      isRequiredAndUnfilled={isRequiredAndUnfilled}
      renderLabelSetMenu={(onLabelSetCreated) => (
        <LabelSetMenuItems
          onLabelSetCreated={onLabelSetCreated}
          schema={schema}
        />
      )}
      onClick={navigateToAgentRun}
    />
  );
};

export default JudgeResultCard;
