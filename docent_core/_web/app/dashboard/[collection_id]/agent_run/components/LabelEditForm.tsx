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
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { useParams } from 'next/navigation';

// Simple read-only value display for complex types
function ReadOnlyValueDisplay({ value }: { value: any }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground italic">null</span>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return (
        <span className="text-muted-foreground italic">(empty array)</span>
      );
    }
    return (
      <pre className="whitespace-pre-wrap break-words font-mono text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  if (typeof value === 'object') {
    if (Object.keys(value).length === 0) {
      return (
        <span className="text-muted-foreground italic">(empty object)</span>
      );
    }
    return (
      <pre className="whitespace-pre-wrap break-words font-mono text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  return <span>{String(value)}</span>;
}

interface LabelEditFormProps {
  labelSet: LabelSet;
  existingLabel?: LabelType;
  onSuccess?: () => void;
}

export default function LabelEditForm({
  labelSet,
  existingLabel,
  onSuccess,
}: LabelEditFormProps) {
  const { collection_id: collectionId, agent_run_id: agentRunId } = useParams<{
    collection_id: string;
    agent_run_id: string;
  }>();

  const [createLabel, { isLoading: isCreating }] = useCreateLabelMutation();
  const [updateLabel, { isLoading: isUpdating }] = useUpdateLabelMutation();
  const [deleteLabel, { isLoading: isDeleting }] = useDeleteLabelMutation();

  const schema = labelSet.label_schema as SchemaDefinition;
  const [formValues, setFormValues] = useState<Record<string, any>>(
    existingLabel?.label_value || {}
  );

  // Sync form values when existingLabel changes
  useEffect(() => {
    if (!existingLabel) return;
    setFormValues(existingLabel.label_value);
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

        toast.success(`Successfully updated label for "${labelSet.name}"`);
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

        toast.success(`Successfully created label for "${labelSet.name}"`);
      }

      onSuccess?.();
    } catch (error: any) {
      console.error('Failed to save label:', error);
      toast.error('Failed to save label');
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

      toast.success(`Successfully deleted label for "${labelSet.name}"`);

      onSuccess?.();
    } catch (error: any) {
      console.error('Failed to delete label:', error);
      toast.error('Failed to delete label');
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

    if (property.type === 'integer' || property.type === 'number') {
      const minimum = property.minimum ?? undefined;
      const maximum = property.maximum ?? undefined;
      return (
        <div key={key} className="flex flex-col gap-1">
          <Label htmlFor={key} className="text-xs text-muted-foreground">
            {key} {minimum && maximum && `(${minimum} - ${maximum})`}
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
            min={minimum}
            max={maximum}
            step={property.type === 'integer' ? 1 : 0.1}
            className="text-sm"
          />
        </div>
      );
    }

    // Handle array and object types as read-only display
    if (property.type === 'array' || property.type === 'object') {
      return (
        <div key={key} className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">
            {key} <span className="text-muted-foreground/70">(read-only)</span>
          </Label>
          <div className="p-2 bg-muted/50 rounded-md border text-xs">
            <ReadOnlyValueDisplay value={value} />
          </div>
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
