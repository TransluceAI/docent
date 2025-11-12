'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  useCreateRubricMutation,
  useStartEvaluationMutation,
  useGetJudgeModelsQuery,
  useUpdateRubricMutation,
} from '@/app/api/rubricApi';
import { useCreateOrGetRefinementSessionMutation } from '@/app/api/refinementApi';
import { toast } from '@/hooks/use-toast';
import QuickSearchBox from '../components/QuickSearchBox';
import RubricList from '../components/RubricList';
import JsonEditor from '../components/JsonEditor';
import ModelPicker from '@/components/ModelPicker';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import type { ModelOption } from '@/app/store/rubricSlice';

export default function RubricsPage() {
  const router = useRouter();
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();

  // State for schema and judge model
  const [schemaText, setSchemaText] = useState(
    JSON.stringify(
      {
        type: 'object',
        required: ['label', 'explanation'],
        properties: {
          label: { type: 'string', enum: ['match', 'no match'] },
          explanation: { type: 'string', citations: true },
        },
      },
      null,
      2
    )
  );
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const { data: availableJudgeModels } = useGetJudgeModelsQuery();
  const defaultJudgeModel = availableJudgeModels?.[0];
  const [selectedJudgeModel, setSelectedJudgeModel] = useState<
    ModelOption | undefined
  >(defaultJudgeModel);

  // Update selected judge model when available models load
  useEffect(() => {
    if (defaultJudgeModel && !selectedJudgeModel) {
      setSelectedJudgeModel(defaultJudgeModel);
    }
  }, [defaultJudgeModel, selectedJudgeModel]);

  // Mutations
  const [createRubric, { isLoading: isCreatingRubric }] =
    useCreateRubricMutation();
  const [updateRubric] = useUpdateRubricMutation();
  const [startEvaluation, { isLoading: isStartingEvaluation }] =
    useStartEvaluationMutation();
  const [createOrGetSession, { isLoading: isCreatingOrGettingSession }] =
    useCreateOrGetRefinementSessionMutation();

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

  const handleAddNewRubric = async (
    rubricText: string,
    withSchemaAndModel: boolean = false
  ) => {
    if (!collectionId) return undefined;

    try {
      const rubricId = await createRubric({
        collectionId,
        rubric: {
          rubric_text: rubricText,
        },
      }).unwrap();

      // If we have schema and model configured, update the rubric immediately
      if (withSchemaAndModel && selectedJudgeModel) {
        try {
          let parsedSchema;
          try {
            parsedSchema = JSON.parse(schemaText);
          } catch (e) {
            setSchemaError(
              `Invalid JSON: ${e instanceof Error ? e.message : 'Unknown error'}`
            );
            return rubricId;
          }

          await updateRubric({
            collectionId,
            rubricId,
            rubric: {
              id: rubricId,
              rubric_text: rubricText,
              judge_model: selectedJudgeModel,
              output_schema: parsedSchema,
            },
          }).unwrap();
        } catch (error) {
          console.error('Failed to update rubric with schema/model:', error);
          // Don't fail the whole operation, just log the error
        }
      }

      return rubricId;
    } catch (error) {
      console.error('Failed to create rubric', error);
      toast({
        title: 'Error',
        description: 'Failed to create rubric',
        variant: 'destructive',
      });
      return undefined;
    }
  };

  const handleGuidedSubmit = async (highLevelDescription: string) => {
    const rubricId = await handleAddNewRubric(highLevelDescription, true);
    if (!rubricId) return;

    await createOrGetSession({
      collectionId,
      rubricId,
      sessionType: 'guided',
    })
      .unwrap()
      .then(() => {
        router.push(`/dashboard/${collectionId}/rubric/${rubricId}`);
      })
      .catch((error) => {
        console.error('Failed to create or get session:', error);
        toast({
          title: 'Error',
          description: 'Failed to create or get session',
          variant: 'destructive',
        });
      });
  };

  const handleDirectSubmit = async (highLevelDescription: string) => {
    const rubricId = await handleAddNewRubric(highLevelDescription, true);
    if (!rubricId) return;

    await startEvaluation({
      collectionId,
      rubricId,
    }).catch((error) => {
      console.error('Failed to start full search:', error);
      toast({
        title: 'Error',
        description: 'Failed to start full search',
        variant: 'destructive',
      });
    });

    await createOrGetSession({
      collectionId,
      rubricId,
      sessionType: 'direct',
    })
      .then(() => {
        router.push(`/dashboard/${collectionId}/rubric/${rubricId}`);
      })
      .catch((error) => {
        console.error('Failed to create or get session:', error);
        toast({
          title: 'Error',
          description: 'Failed to create or get session',
          variant: 'destructive',
        });
      });
  };

  const isLoading =
    isCreatingRubric || isCreatingOrGettingSession || isStartingEvaluation;

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-background rounded-lg border space-y-3">
      <div className="flex-1 flex min-h-0">
        {/* Left Side - Input and Configuration */}
        <div className="w-1/2 flex flex-col p-3 h-full min-h-0 space-y-3">
          {/* Quick Search Box */}
          <QuickSearchBox
            onGuided={handleGuidedSubmit}
            onDirect={handleDirectSubmit}
            isLoading={isLoading}
            modelPicker={
              availableJudgeModels && selectedJudgeModel ? (
                <ModelPicker
                  selectedModel={selectedJudgeModel}
                  availableModels={availableJudgeModels}
                  onChange={setSelectedJudgeModel}
                  className="w-32"
                  borderless
                  shortenName
                />
              ) : null
            }
          />

          {/* Schema Editor */}
          <div className="flex flex-col space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">
                Output Schema
              </Label>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">
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
                  + Explanation
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
            </div>
            <JsonEditor
              schemaText={schemaText}
              setSchemaText={setSchemaText}
              schemaError={schemaError}
              editable={true}
              forceOpenSchema={true}
              showPreview={true}
              expandedContentClassName="!max-h-96"
            />
          </div>
        </div>
        <Separator orientation="vertical" className="shrink-0" />
        {/* Right Side - Rubric List */}
        <div className="w-1/2 flex p-3 flex-col h-full min-h-0">
          <RubricList />
        </div>
      </div>
    </div>
  );
}
