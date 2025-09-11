import React, { useReducer } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import {
  useCreateJudgeRunLabelMutation,
  useUpdateJudgeRunLabelMutation,
  useDeleteJudgeRunLabelMutation,
} from '@/app/api/rubricApi';
import { JudgeRunLabel } from '@/app/store/rubricSlice';
import { SchemaDefinition } from '@/app/types/schema';
import { toast } from '@/hooks/use-toast';
import posthog from 'posthog-js';

// Reducer types
type FormState = Record<string, any>;

type FormAction =
  | { type: 'SET_ENUM'; key: string; value: string }
  | { type: 'SET_BOOLEAN'; key: string; value: boolean }
  | { type: 'SET_EXPLANATION_TEXT'; key: string; value: string }
  | { type: 'SET_NUMBER'; key: string; value: number }
  | { type: 'RESET'; initialState: FormState };

// Reducer function
const formReducer = (state: FormState, action: FormAction): FormState => {
  switch (action.type) {
    case 'SET_ENUM':
      return { ...state, [action.key]: action.value };
    case 'SET_BOOLEAN':
      return { ...state, [action.key]: action.value };
    case 'SET_EXPLANATION_TEXT':
      // NOTE(cadentj): Explanation isn't directly stored as a value
      return { ...state, [action.key]: { text: action.value } };
    case 'SET_NUMBER':
      return { ...state, [action.key]: action.value };
    case 'RESET':
      return action.initialState;
    default:
      return state;
  }
};

// Components
interface EnumInputProps {
  values: string[];
  selectedValue?: string;
  onChange: (value: string) => void;
}

const EnumInput = ({ values, selectedValue, onChange }: EnumInputProps) => {
  return (
    <div className="flex flex-wrap gap-1">
      {values.map((value) => (
        <Button
          key={value}
          onClick={() => onChange(value)}
          variant="outline"
          size="sm"
          className={cn(value === selectedValue && 'border-primary')}
        >
          {value}
        </Button>
      ))}
    </div>
  );
};

// Components
interface BooleanInputProps {
  selected: boolean;
  onChange: (value: boolean) => void;
}

const BooleanInput = ({ selected, onChange }: BooleanInputProps) => {
  return (
    <div className="flex flex-wrap gap-1">
      {[true, false].map((value) => (
        <Button
          key={value.toString()}
          onClick={() => onChange(value)}
          variant="outline"
          size="sm"
          className={cn(value === selected && 'border-primary')}
        >
          {value.toString()}
        </Button>
      ))}
    </div>
  );
};

interface NumberInputProps {
  value: number;
  maximum: number;
  minimum: number;
  onChange: (value: number) => void;
}

const NumberInput = ({
  value,
  maximum,
  minimum,
  onChange,
}: NumberInputProps) => {
  return (
    <input
      type="number"
      value={value ?? minimum}
      onChange={(e) => {
        const num = parseInt(e.target.value, 10);
        if (!isNaN(num)) {
          onChange(Math.min(maximum, Math.max(minimum, num)));
        }
      }}
      className="border rounded px-2 py-1 w-16 text-xs"
      max={maximum}
      min={minimum}
    />
  );
};

interface TextInputProps {
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}

const TextInput = ({ value, placeholder, onChange }: TextInputProps) => {
  return (
    <Textarea
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="min-h-[35vh] text-xs resize-vertical"
    />
  );
};

// Main component
interface AreaProps {
  collectionId: string;
  rubricId: string;
  agentRunId: string;
  schema: SchemaDefinition;
  judgeOutput: Record<string, any>;
  judgeRunLabel: JudgeRunLabel | null;
  initialState: Record<string, any>;
}

const LabelForm = ({
  collectionId,
  rubricId,
  agentRunId,
  judgeOutput,
  schema,
  initialState = {},
  judgeRunLabel,
}: AreaProps) => {
  // Plop the initial state into the reducer as the initial reducer state
  const [formState, dispatch] = useReducer(formReducer, initialState);

  const [createJudgeRunLabel] = useCreateJudgeRunLabelMutation();
  const [updateJudgeRunLabel] = useUpdateJudgeRunLabelMutation();
  const [deleteJudgeRunLabel] = useDeleteJudgeRunLabelMutation();

  const submit = async () => {
    try {
      const payload = {
        collectionId: collectionId,
        rubricId: rubricId,
        agentRunId: agentRunId,
        label: formState,
      };

      if (!judgeRunLabel) {
        await createJudgeRunLabel(payload).unwrap();
        toast({
          title: 'Label created',
          description: 'Label created successfully',
        });
      } else {
        await updateJudgeRunLabel(payload).unwrap();
        toast({
          title: 'Label updated',
          description: 'Label updated successfully',
        });
      }

      posthog.capture('label_form_submitted', {
        num_fields_filled: Object.keys(formState).length,
        agent_run_id: agentRunId,
      });
    } catch (error) {
      toast({
        title: 'Error',
        description: `Failed to ${judgeRunLabel ? 'update' : 'create'} label`,
        variant: 'destructive',
      });
    }
  };

  const reset = async () => {
    dispatch({ type: 'RESET', initialState: judgeOutput });

    if (judgeRunLabel) {
      try {
        await deleteJudgeRunLabel({
          collectionId: collectionId,
          rubricId: rubricId,
          agentRunId: agentRunId,
        }).unwrap();

        toast({
          title: 'Label deleted',
          description: 'Label deleted successfully',
        });
      } catch (error) {
        toast({
          title: 'Error',
          description: 'Failed to delete label',
          variant: 'destructive',
        });
      }
    }
  };

  const hasChanged = JSON.stringify(judgeOutput) !== JSON.stringify(formState);

  return (
    <div className="space-y-4">
      {Object.entries(schema.properties).map(([key, property]) => {
        if (property.type === 'string' && 'citations' in property) {
          return (
            <div key={key} className="space-y-1">
              <label className="block text-xs mb-2 text-muted-foreground font-medium">
                {key}
              </label>
              <TextInput
                value={formState[key]?.text}
                placeholder={'Enter an updated explanation.'}
                onChange={(value) =>
                  dispatch({ type: 'SET_EXPLANATION_TEXT', key, value })
                }
              />
            </div>
          );
        }

        if (property.type === 'string' && 'enum' in property) {
          return (
            <div
              key={key}
              className="space-y-1 flex justify-between items-center"
            >
              <label className="block text-xs text-muted-foreground font-medium">
                {key}
              </label>
              <EnumInput
                values={property.enum}
                selectedValue={formState[key] as string | undefined}
                onChange={(value) => dispatch({ type: 'SET_ENUM', key, value })}
              />
            </div>
          );
        }

        if (property.type === 'boolean') {
          return (
            <div key={key} className="space-y-1">
              <label className="block text-xs mb-2 text-muted-foreground font-medium">
                {key}
              </label>
              <BooleanInput
                selected={formState[key] as boolean}
                onChange={(value) =>
                  dispatch({ type: 'SET_BOOLEAN', key, value })
                }
              />
            </div>
          );
        }

        if (
          property.type === 'integer' &&
          'maximum' in property &&
          'minimum' in property
        ) {
          return (
            <div
              key={key}
              className="space-y-1 flex justify-between items-center"
            >
              <label className="block text-xs text-muted-foreground font-medium">
                {key}
              </label>
              <NumberInput
                value={formState[key] as number}
                maximum={property.maximum}
                minimum={property.minimum}
                onChange={(value) =>
                  dispatch({ type: 'SET_NUMBER', key, value })
                }
              />
            </div>
          );
        }

        return null;
      })}

      {/* Fixed buttons at bottom */}
      <div className="sticky bottom-0 bg-background pt-3 border-t">
        <div className="flex flex-row gap-2 w-full">
          <Button size="sm" onClick={submit} className="w-full">
            Save
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={reset}
            disabled={!hasChanged}
            className="w-full"
          >
            Reset
          </Button>
        </div>
      </div>
    </div>
  );
};

export default LabelForm;
