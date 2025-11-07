'use client';

import { useState, useEffect, useMemo } from 'react';

import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  useGetLabelSetQuery,
  useGetLabelsInLabelSetQuery,
  useUpdateLabelSetMutation,
  useCreateLabelSetMutation,
} from '@/app/api/labelApi';
import JsonEditor from './JsonEditor';
import { useParams } from 'next/navigation';
import { useRouter } from 'next/navigation';
import { setAgentRunSidebarTab } from '@/app/store/transcriptSlice';
import { useAppDispatch } from '@/app/store/hooks';
import { useLabelSets } from '@/providers/use-label-sets';

interface LabelSetEditorProps {
  labelSetId: string | null;
  isCreateMode: boolean;
  onCreateSuccess?: (labelSetId: string) => void;
  prefillSchema?: Record<string, any>;
}

export default function LabelSetEditor({
  labelSetId,
  isCreateMode,
  onCreateSuccess,
  prefillSchema,
}: LabelSetEditorProps) {
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();
  const router = useRouter();
  const dispatch = useAppDispatch();

  // Fetch label set data if not in create mode
  const { data: labelSet, isLoading: isLoadingLabelSet } = useGetLabelSetQuery(
    { collectionId: collectionId!, labelSetId: labelSetId! },
    { skip: !labelSetId || isCreateMode || !collectionId }
  );

  // Fetch labels in this set
  const { data: labels, isLoading: isLoadingLabels } =
    useGetLabelsInLabelSetQuery(
      { collectionId: collectionId!, labelSetId: labelSetId! },
      { skip: !labelSetId || isCreateMode || !collectionId }
    );

  // Mutations
  const [updateLabelSet, { isLoading: isUpdating }] =
    useUpdateLabelSetMutation();
  const [createLabelSet, { isLoading: isCreating }] =
    useCreateLabelSetMutation();

  // Local state for editing
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [schemaText, setSchemaText] = useState('');
  const [schemaError, setSchemaError] = useState<string | null>(null);

  // Initialize form when labelSet data loads
  useEffect(() => {
    if (isCreateMode) {
      setName('');
      setDescription('');
      // Use prefill schema if provided, otherwise use default
      const defaultSchema = prefillSchema || {
        type: 'object',
        required: [],
        properties: {},
      };
      setSchemaText(JSON.stringify(defaultSchema, null, 2));
      setSchemaError(null);
    } else if (labelSet) {
      setName(labelSet.name);
      setDescription(labelSet.description || '');
      setSchemaText(JSON.stringify(labelSet.label_schema, null, 2));
      setSchemaError(null);
    }
  }, [labelSet, isCreateMode, prefillSchema]);

  const hasChanges = useMemo(() => {
    if (isCreateMode) {
      return name.trim().length > 0;
    }
    if (!labelSet) return false;
    return (
      name !== labelSet.name ||
      description !== (labelSet.description || '') ||
      schemaText !== JSON.stringify(labelSet.label_schema, null, 2)
    );
  }, [name, description, schemaText, labelSet, isCreateMode]);

  const { setLabelSet: setActiveLabelSet } = useLabelSets(collectionId);

  const navigateToRun = (agentRunId: string) => {
    dispatch(setAgentRunSidebarTab('labels'));
    setActiveLabelSet(labelSet ?? null);
    router.push(`/dashboard/${collectionId}/agent_run/${agentRunId}`);
  };

  // Helper function to add a field to the schema
  const handleAddField = (
    fieldType: 'number' | 'boolean' | 'explanation' | 'enum'
  ) => {
    try {
      // Parse the current schema
      const parsedSchema = JSON.parse(schemaText);

      // Validate schema structure
      if (
        !parsedSchema.properties ||
        typeof parsedSchema.properties !== 'object'
      ) {
        setSchemaError(
          'Invalid schema: Must have a "properties" field with an object value'
        );
        return;
      }

      // Generate a unique field name
      const existingKeys = Object.keys(parsedSchema.properties);
      let fieldIndex = 1;
      let fieldName = `field_${fieldIndex}`;
      while (existingKeys.includes(fieldName)) {
        fieldIndex++;
        fieldName = `field_${fieldIndex}`;
      }

      // Create the field definition based on type
      let fieldDefinition: any;
      switch (fieldType) {
        case 'number':
          fieldDefinition = { type: 'number', minimum: 0, maximum: 10 };
          break;
        case 'boolean':
          fieldDefinition = { type: 'boolean' };
          break;
        case 'explanation':
          fieldDefinition = { type: 'string', citations: true };
          break;
        case 'enum':
          fieldDefinition = { type: 'string', enum: ['option1', 'option2'] };
          break;
      }

      // Add the new field to properties
      parsedSchema.properties[fieldName] = fieldDefinition;

      // Update the schema text with proper formatting
      setSchemaText(JSON.stringify(parsedSchema, null, 2));
      setSchemaError(null);
    } catch (e) {
      setSchemaError(
        `Cannot add field: Invalid JSON - ${e instanceof Error ? e.message : 'Unknown error'}`
      );
    }
  };

  // Handlers
  const handleSave = async () => {
    // 1) Raise an error if the JSON is invalid
    let parsedSchema;
    try {
      parsedSchema = JSON.parse(schemaText);
    } catch (e) {
      setSchemaError(
        `Invalid JSON: ${e instanceof Error ? e.message : 'Unknown error'}`
      );
      return;
    }

    // 2) Raise an error if the JSON does not have any properties
    if (Object.keys(parsedSchema.properties).length === 0) {
      setSchemaError('Invalid schema: Must have at least one property');
      return;
    }

    // 3) If all is good, clear any existing errors
    setSchemaError(null);

    if (isCreateMode) {
      // Create new label set
      try {
        const result = await createLabelSet({
          collectionId: collectionId!,
          name,
          description: description || null,
          label_schema: parsedSchema,
        }).unwrap();
        if (onCreateSuccess) {
          onCreateSuccess(result.label_set_id);
        }
      } catch (error) {
        console.error('Failed to create label set:', error);
        setSchemaError('Failed to create label set');
      }
    } else if (labelSetId && collectionId) {
      // Update existing label set
      try {
        await updateLabelSet({
          collectionId,
          labelSetId,
          name,
          description: description || null,
          label_schema: parsedSchema,
        }).unwrap();
      } catch (error) {
        console.error('Failed to update label set:', error);
        setSchemaError('Failed to update label set');
      }
    }
  };

  if (isLoadingLabelSet) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-2">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            Loading label set...
          </span>
        </div>
      </div>
    );
  }

  if (!isCreateMode && !labelSetId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center text-sm text-muted-foreground">
          Select a label set to view details
        </div>
      </div>
    );
  }

  // Normal mode layout
  return (
    <div className="flex flex-col h-full w-full -m-0.5">
      {/* Scrollable Content */}
      <div className="flex-1 min-h-0 p-0.5 overflow-y-auto space-y-3 custom-scrollbar">
        <div className="font-semibold">
          {isCreateMode ? 'Create Label Set' : 'Label Set Details'}
        </div>

        {/* Name and Description */}
        <div className="space-y-2">
          <div className="flex flex-col space-y-2">
            <Label htmlFor="name" className="text-xs text-muted-foreground">
              Name
            </Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Enter label set name"
              className="text-sm"
            />
          </div>
          <div className="flex flex-col space-y-2">
            <Label
              htmlFor="description"
              className="text-xs text-muted-foreground"
            >
              Description
            </Label>
            <Input
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Enter description (optional)"
              className="text-sm"
            />
          </div>
        </div>

        {/* Schema Editor */}
        <div className="flex flex-col space-y-2">
          <div className="flex items-center justify-between">
            <Label
              htmlFor="description"
              className="text-xs text-muted-foreground"
            >
              Output Schema
            </Label>
            {isCreateMode && (
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground ">
                  Add Field:
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => handleAddField('number')}
                  className="h-6 px-2 text-xs"
                >
                  + Number
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => handleAddField('boolean')}
                  className="h-6 px-2 text-xs"
                >
                  + Bool
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => handleAddField('explanation')}
                  className="h-6 px-2 text-xs"
                >
                  Explanation
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => handleAddField('enum')}
                  className="h-6 px-2 text-xs"
                >
                  + Enum
                </Button>
              </div>
            )}
          </div>
          <JsonEditor
            schemaText={schemaText}
            setSchemaText={setSchemaText}
            schemaError={schemaError}
            editable={isCreateMode}
            forceOpenSchema={isCreateMode}
            showPreview={true}
          />
        </div>

        {/* Labels List */}
        {!isCreateMode && (
          <div className="flex-1 flex flex-col min-h-0 space-y-1">
            <Label className="text-xs text-muted-foreground">
              Labels ({labels?.length || 0})
            </Label>
            <div className="flex-1 min-h-0 rounded-md border overflow-y-auto custom-scrollbar bg-secondary/30">
              {isLoadingLabels ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : labels && labels.length > 0 ? (
                <div className="p-2 space-y-2">
                  {labels.map((label) => {
                    const schema = labelSet?.label_schema || { properties: {} };
                    const schemaKeys = Object.keys(schema.properties || {});

                    return (
                      <div
                        key={label.id}
                        className="bg-background border rounded p-3 space-y-1.5 cursor-pointer hover:bg-muted"
                        onClick={() => navigateToRun(label.agent_run_id)}
                      >
                        <div className="text-[10px] text-muted-foreground font-mono pb-1 border-b">
                          {label.agent_run_id}
                        </div>
                        <div className="space-y-1">
                          {schemaKeys.map((key) => {
                            return (
                              <div key={key} className="text-xs">
                                <span className="font-semibold">{key}:</span>{' '}
                                {label.label_value[key] ? (
                                  <span className="text-foreground">
                                    {String(label.label_value[key])}
                                  </span>
                                ) : (
                                  <span className="text-muted-foreground italic">
                                    (empty)
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="flex items-center justify-center py-8 text-xs text-muted-foreground">
                  No labels in this set yet
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer Actions */}
      <div className="flex items-center justify-end gap-2 pt-2">
        <Button
          onClick={handleSave}
          disabled={!hasChanges || isUpdating || isCreating}
          className="gap-1.5"
        >
          {isUpdating || isCreating ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              Saving...
            </>
          ) : isCreateMode ? (
            'Create Label Set'
          ) : (
            'Save Changes'
          )}
        </Button>
      </div>
    </div>
  );
}
