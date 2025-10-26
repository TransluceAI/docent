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

interface LabelSetEditorProps {
  labelSetId: string | null;
  isCreateMode: boolean;
  collectionId?: string;
  onCreateSuccess?: (labelSetId: string) => void;
  prefillSchema?: Record<string, any>;
}

export default function LabelSetEditor({
  labelSetId,
  isCreateMode,
  collectionId,
  onCreateSuccess,
  prefillSchema,
}: LabelSetEditorProps) {
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
  const [showDescriptionButton, setShowDescriptionButton] = useState(false);
  const [showDescription, setShowDescription] = useState(false);

  useEffect(() => {
    if (name.trim().length > 0) {
      setShowDescriptionButton(true);
    } else {
      setShowDescriptionButton(false);
    }
  }, [name]);

  // Initialize form when labelSet data loads
  useEffect(() => {
    if (isCreateMode) {
      setName('');
      setDescription('');
      // Use prefill schema if provided, otherwise use default
      const defaultSchema = prefillSchema || {
        type: 'object',
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

  // Handlers
  const handleSave = async () => {
    // Validate JSON
    let parsedSchema;
    try {
      parsedSchema = JSON.parse(schemaText);
    } catch (e) {
      setSchemaError(
        `Invalid JSON: ${e instanceof Error ? e.message : 'Unknown error'}`
      );
      return;
    }

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
        <div className="text-sm font-semibold">
          {isCreateMode ? 'Create Label Set' : 'Label Set Details'}
        </div>

        {/* Name and Description */}
        <div className={showDescription ? 'space-y-2' : ''}>
          <div className="flex flex-col">
            <Label htmlFor="name" className="text-xs text-muted-foreground">
              Name
            </Label>
            <div className="relative">
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Enter label set name"
                className="text-sm"
              />
              {showDescriptionButton && (
                <button
                  className="absolute right-2 top-1/2 -translate-y-1/2 border text-xs bg-muted rounded px-2 py-0.5 text-muted-foreground hover:text-primary"
                  onClick={() => setShowDescription(!showDescription)}
                >
                  {showDescription ? 'Description -' : 'Description +'}
                </button>
              )}
            </div>
          </div>
          <div
            className={`flex flex-col transition-all duration-300 ease-in-out ${
              showDescription ? 'max-h-24 opacity-100' : '!max-h-0 opacity-0'
            }`}
          >
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
        <div className="flex flex-col">
          <Label
            htmlFor="description"
            className="text-xs text-muted-foreground"
          >
            Output Schema
          </Label>
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
                        className="bg-background border rounded p-3 space-y-1.5"
                      >
                        <div className="text-[10px] text-muted-foreground font-mono pb-1 border-b">
                          {label.agent_run_id}
                        </div>
                        <div className="space-y-1">
                          {schemaKeys.map((key) => {
                            const displayValue = String(label.label_value[key]);
                            return (
                              <div key={key} className="text-xs">
                                <span className="font-semibold">{key}:</span>{' '}
                                {label.label_value[key] ? (
                                  <span className="text-foreground">
                                    {displayValue}
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
          size="sm"
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
