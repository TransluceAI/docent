'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import {
  useCreateLabelMutation,
  useUpdateLabelMutation,
  useDeleteLabelMutation,
  type Label as LabelType,
  type LabelSet,
} from '@/app/api/labelApi';
import { SchemaDefinition, SchemaProperty } from '@/app/types/schema';
import { toast } from '@/hooks/use-toast';
import { Loader2 } from 'lucide-react';

interface LabelEditFormProps {
  labelSet: LabelSet;
  existingLabel: LabelType;
  agentRunId: string;
  collectionId: string;
  onSuccess?: () => void;
}

export default function LabelEditForm({
  labelSet,
  existingLabel,
  agentRunId,
  collectionId,
  onSuccess,
}: LabelEditFormProps) {
  const [createLabel, { isLoading: isCreating }] = useCreateLabelMutation();
  const [updateLabel, { isLoading: isUpdating }] = useUpdateLabelMutation();
  const [deleteLabel, { isLoading: isDeleting }] = useDeleteLabelMutation();

  const schema = labelSet.label_schema as SchemaDefinition;
  const [formValues, setFormValues] = useState<Record<string, any>>(
    existingLabel.label_value || {}
  );

  // Sync form values when existingLabel changes
  useEffect(() => {
    if (existingLabel) {
      setFormValues(existingLabel.label_value);
    }
  }, [existingLabel]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      if (existingLabel && existingLabel.id) {
        // Update existing label
        await updateLabel({
          collectionId,
          labelId: existingLabel.id,
          label_value: formValues,
          agentRunId,
        }).unwrap();

        toast({
          title: 'Label updated',
          description: `Successfully updated label for "${labelSet.name}"`,
        });
      } else {
        // Create new label
        await createLabel({
          collectionId,
          label: {
            label_set_id: labelSet.id,
            label_value: formValues,
            agent_run_id: agentRunId,
          },
        }).unwrap();

        toast({
          title: 'Label created',
          description: `Successfully created label for "${labelSet.name}"`,
        });
      }

      onSuccess?.();
    } catch (error: any) {
      console.error('Failed to save label:', error);
      toast({
        title: 'Error',
        description: 'Failed to save label',
        variant: 'destructive',
      });
    }
  };

  const handleDelete = async () => {
    if (!existingLabel?.id) return;

    try {
      await deleteLabel({
        collectionId,
        labelId: existingLabel.id,
        agentRunId,
      }).unwrap();

      toast({
        title: 'Label deleted',
        description: `Successfully deleted label for "${labelSet.name}"`,
      });

      onSuccess?.();
    } catch (error: any) {
      console.error('Failed to delete label:', error);
      toast({
        title: 'Error',
        description: 'Failed to delete label',
        variant: 'destructive',
      });
    }
  };

  const renderField = (key: string, property: SchemaProperty) => {
    const value = formValues[key];
    const isRequired = schema.required?.includes(key);

    if (property.type === 'string' && 'enum' in property) {
      return (
        <div key={key} className="flex flex-col gap-1">
          <Label htmlFor={key} className="text-xs text-muted-foreground">
            {key}
            {isRequired && (
              <span className="text-red-500 ml-1">(required)</span>
            )}
          </Label>
          <Select
            value={value || ''}
            onValueChange={(val) =>
              setFormValues((prev) => ({ ...prev, [key]: val }))
            }
          >
            <SelectTrigger id={key} className="text-sm">
              <SelectValue placeholder={`Select ${key}`} />
            </SelectTrigger>
            <SelectContent>
              {property.enum.map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );
    }

    if (property.type === 'string') {
      return (
        <div key={key} className="flex flex-col gap-1">
          <Label htmlFor={key} className="text-xs text-muted-foreground">
            {key}
            {isRequired && (
              <span className="text-red-500 ml-1">(required)</span>
            )}
          </Label>
          <Textarea
            id={key}
            value={value || ''}
            onChange={(e) =>
              setFormValues((prev) => ({ ...prev, [key]: e.target.value }))
            }
            placeholder={`Enter ${key}`}
            className="min-h-[80px] text-sm"
          />
        </div>
      );
    }

    if (property.type === 'boolean') {
      return (
        <div key={key} className="flex items-center space-x-2 gap-1">
          <Checkbox
            id={key}
            checked={value === true}
            onCheckedChange={(checked) =>
              setFormValues((prev) => ({ ...prev, [key]: checked === true }))
            }
          />
          <Label htmlFor={key} className="text-xs cursor-pointer">
            {key}
            {isRequired && (
              <span className="text-red-500 ml-1">(required)</span>
            )}
          </Label>
        </div>
      );
    }

    if (
      (property.type === 'integer' || property.type === 'number') &&
      'maximum' in property &&
      'minimum' in property
    ) {
      return (
        <div key={key} className="flex flex-col gap-1">
          <Label htmlFor={key} className="text-xs text-muted-foreground">
            {key} ({property.minimum} - {property.maximum})
            {isRequired && (
              <span className="text-red-500 ml-1">(required)</span>
            )}
          </Label>
          <Input
            id={key}
            type="number"
            value={value ?? ''}
            onChange={(e) => {
              const numValue =
                property.type === 'integer'
                  ? parseInt(e.target.value, 10)
                  : parseFloat(e.target.value);
              setFormValues((prev) => ({
                ...prev,
                [key]: isNaN(numValue) ? undefined : numValue,
              }));
            }}
            min={property.minimum}
            max={property.maximum}
            step={property.type === 'integer' ? 1 : 0.1}
            className="text-sm"
          />
        </div>
      );
    }

    return null;
  };

  const isLoading = isCreating || isUpdating || isDeleting;

  return (
    <div className="flex flex-col h-full space-y-3">
      {/* Scrollable Content */}
      <div className="flex-1 min-h-0 overflow-y-auto space-y-3 p-0.5 custom-scrollbar">
        <div className="flex flex-col">
          <div className="text-sm font-medium">{labelSet.name}</div>
          {labelSet.description && (
            <div className="text-xs text-muted-foreground mt-1">
              {labelSet.description}
            </div>
          )}
        </div>

        {/* Form Fields */}
        <form onSubmit={handleSubmit} id="label-form" className="space-y-3">
          {Object.entries(schema.properties).map(([key, property]) =>
            renderField(key, property)
          )}
        </form>
      </div>

      {/* Footer Actions */}
      <div className="flex items-center gap-2 pt-3 border-t">
        <div>
          {existingLabel && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={handleDelete}
              disabled={isLoading}
              className="gap-1.5"
            >
              {isDeleting ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Deleting...
                </>
              ) : (
                'Delete Label'
              )}
            </Button>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            type="submit"
            size="sm"
            form="label-form"
            disabled={isLoading}
            className="gap-1.5"
          >
            {isCreating || isUpdating ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                Saving...
              </>
            ) : existingLabel ? (
              'Save Changes'
            ) : (
              'Create Label'
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
