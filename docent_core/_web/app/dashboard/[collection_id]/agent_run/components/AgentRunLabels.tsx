'use client';

import { useState, useMemo, useCallback } from 'react';
import {
  Plus,
  Tags,
  ArrowLeft,
  ToggleLeft,
  ListFilter,
  Star,
  Settings,
  Trash2,
  X,
  Loader2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Separator } from '@/components/ui/separator';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  useGetCategorizedLabelSetsQuery,
  useGetLabelsForAgentRunQuery,
  useCreateLabelSetMutation,
  useCreateLabelMutation,
  useUpdateLabelMutation,
  useDeleteLabelMutation,
  type LabelSet,
  type Label as LabelData,
} from '@/app/api/labelApi';
import { SchemaDefinition } from '@/app/types/schema';
import { SchemaValueRenderer } from '@/app/dashboard/[collection_id]/components/SchemaValueRenderer';
import { cn } from '@/lib/utils';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';
import CodeMirror, { EditorView } from '@uiw/react-codemirror';
import { json as jsonLanguage } from '@codemirror/lang-json';
import { useTheme } from 'next-themes';

interface AgentRunLabelsProps {
  agentRunId: string;
  collectionId: string;
}

// Field types supported by the visual schema builder
type FieldType = 'boolean' | 'enum' | 'number' | 'string';

interface FieldDefinition {
  id: string;
  name: string;
  type: FieldType;
  required: boolean;
  description?: string;
  enumOptions?: string[];
  minimum?: number;
  maximum?: number;
}

// Preset templates for quick start
interface Preset {
  id: string;
  name: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  fields: FieldDefinition[];
}

const PRESETS: Preset[] = [
  {
    id: 'binary',
    name: 'Binary (Yes/No)',
    description: 'Single yes/no judgment',
    icon: ToggleLeft,
    fields: [
      {
        id: crypto.randomUUID(),
        name: 'judgment',
        type: 'boolean',
        required: true,
        description: '',
      },
    ],
  },
  {
    id: 'categories',
    name: 'Categories',
    description: 'Classify into categories',
    icon: ListFilter,
    fields: [
      {
        id: crypto.randomUUID(),
        name: 'category',
        type: 'enum',
        required: true,
        description: '',
        enumOptions: [],
      },
    ],
  },
  {
    id: 'rating',
    name: 'Numerical Rating',
    description: 'Rate on a scale',
    icon: Star,
    fields: [
      {
        id: crypto.randomUUID(),
        name: 'rating',
        type: 'number',
        required: true,
        description: '',
        minimum: 1,
        maximum: 5,
      },
    ],
  },
  {
    id: 'custom',
    name: 'Custom',
    description: 'Start from scratch',
    icon: Settings,
    fields: [
      {
        id: crypto.randomUUID(),
        name: '',
        type: 'string',
        required: true,
      },
    ],
  },
];

function createEmptyField(): FieldDefinition {
  return {
    id: crypto.randomUUID(),
    name: '',
    type: 'string',
    required: true,
  };
}

// Result of parsing a JSON schema for Visual mode compatibility
type VisualSchemaParseResult = {
  fields: FieldDefinition[];
  errors: string[];
};

// Allowed keys at the top level of a visual-compatible schema
const ALLOWED_TOP_LEVEL_KEYS = new Set([
  'type',
  'properties',
  'required',
  'additionalProperties',
]);

// Allowed keys at the property level of a visual-compatible schema
const ALLOWED_PROPERTY_KEYS = new Set([
  'type',
  'description',
  'enum',
  'minimum',
  'maximum',
]);

/**
 * Parse a JSON schema and validate it for Visual mode compatibility.
 * Returns fields if compatible, or errors explaining why it's not.
 */
function parseSchemaForVisual(schema: unknown): VisualSchemaParseResult {
  const errors: string[] = [];
  const fields: FieldDefinition[] = [];

  // Top-level must be an object
  if (typeof schema !== 'object' || schema === null || Array.isArray(schema)) {
    errors.push('Schema must be an object');
    return { fields: [], errors };
  }

  const schemaObj = schema as Record<string, unknown>;

  // Check for unknown top-level keys
  for (const key of Object.keys(schemaObj)) {
    if (!ALLOWED_TOP_LEVEL_KEYS.has(key)) {
      errors.push(
        `Unknown top-level key "${key}" is not supported in Visual mode`
      );
    }
  }

  // Must have type: "object"
  if (schemaObj.type !== 'object') {
    errors.push('Schema must have type: "object"');
    return { fields: [], errors };
  }

  // Must have properties object
  const properties = schemaObj.properties;
  if (
    typeof properties !== 'object' ||
    properties === null ||
    Array.isArray(properties)
  ) {
    errors.push('Schema must have a "properties" object');
    return { fields: [], errors };
  }

  // Validate additionalProperties if present
  if (
    'additionalProperties' in schemaObj &&
    schemaObj.additionalProperties !== false
  ) {
    errors.push('additionalProperties must be false if specified');
  }

  // Validate required array if present
  const required = schemaObj.required;
  let requiredSet = new Set<string>();
  if (required !== undefined) {
    if (!Array.isArray(required)) {
      errors.push('"required" must be an array');
    } else {
      requiredSet = new Set(required as string[]);
      // Check that all required entries exist in properties
      const propKeys = new Set(Object.keys(properties as object));
      for (const req of required as string[]) {
        if (!propKeys.has(req)) {
          errors.push(`Required field "${req}" does not exist in properties`);
        }
      }
    }
  }

  // Parse each property
  for (const [name, prop] of Object.entries(
    properties as Record<string, unknown>
  )) {
    if (typeof prop !== 'object' || prop === null || Array.isArray(prop)) {
      errors.push(`Property "${name}" must be an object`);
      continue;
    }

    const propObj = prop as Record<string, unknown>;

    // Check for unknown property keys
    for (const key of Object.keys(propObj)) {
      if (!ALLOWED_PROPERTY_KEYS.has(key)) {
        errors.push(`Property "${name}" has unsupported key "${key}"`);
      }
    }

    const propType = propObj.type;

    // Check for unsupported types
    if (propType === 'array') {
      errors.push(
        `Property "${name}" has type "array" which is not supported in Visual mode`
      );
      continue;
    }
    if (propType === 'object') {
      errors.push(
        `Property "${name}" has type "object" which is not supported in Visual mode`
      );
      continue;
    }
    if (propType === 'integer') {
      // TODO(mengk): Support integer fields in visual schema builder.
      errors.push(
        `Property "${name}" has type "integer" which is not yet supported in Visual mode`
      );
      continue;
    }

    // Build field definition
    const field: FieldDefinition = {
      id: crypto.randomUUID(),
      name,
      type: 'string',
      required: requiredSet.has(name),
      description:
        typeof propObj.description === 'string'
          ? propObj.description
          : undefined,
    };

    if (propType === 'boolean') {
      if ('enum' in propObj) {
        errors.push(
          `Property "${name}" has enum constraint, but enums are only supported for string fields`
        );
        continue;
      }
      field.type = 'boolean';
    } else if (propType === 'string') {
      // Check for enum
      if ('enum' in propObj) {
        if (!Array.isArray(propObj.enum)) {
          errors.push(`Property "${name}" has invalid enum (must be an array)`);
          continue;
        }
        // Validate all enum values are strings
        const enumVals = propObj.enum as unknown[];
        if (!enumVals.every((v) => typeof v === 'string')) {
          errors.push(`Property "${name}" has enum with non-string values`);
          continue;
        }
        field.type = 'enum';
        field.enumOptions = enumVals as string[];
      } else {
        field.type = 'string';
      }
    } else if (propType === 'number') {
      if ('enum' in propObj) {
        errors.push(
          `Property "${name}" has enum constraint, but enums are only supported for string fields`
        );
        continue;
      }
      field.type = 'number';
      if (propObj.minimum !== undefined) {
        if (typeof propObj.minimum !== 'number') {
          errors.push(
            `Property "${name}" has invalid minimum (must be a number)`
          );
        } else {
          field.minimum = propObj.minimum;
        }
      }
      if (propObj.maximum !== undefined) {
        if (typeof propObj.maximum !== 'number') {
          errors.push(
            `Property "${name}" has invalid maximum (must be a number)`
          );
        } else {
          field.maximum = propObj.maximum;
        }
      }
    } else if (propType === undefined) {
      errors.push(`Property "${name}" is missing a type`);
      continue;
    } else {
      errors.push(`Property "${name}" has unsupported type "${propType}"`);
      continue;
    }

    fields.push(field);
  }

  // If there are errors, return empty fields
  if (errors.length > 0) {
    return { fields: [], errors };
  }

  return { fields, errors: [] };
}

function fieldsToSchema(fields: FieldDefinition[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];

  for (const field of fields) {
    if (!field.name) continue;

    let prop: Record<string, unknown> = {};

    switch (field.type) {
      case 'boolean':
        prop = { type: 'boolean' };
        break;
      case 'enum':
        prop = {
          type: 'string',
          enum: field.enumOptions || [],
        };
        break;
      case 'number':
        prop = { type: 'number' };
        if (field.minimum !== undefined) prop.minimum = field.minimum;
        if (field.maximum !== undefined) prop.maximum = field.maximum;
        break;
      case 'string':
        prop = { type: 'string' };
        break;
    }

    if (field.description) {
      prop.description = field.description;
    }

    properties[field.name] = prop;

    if (field.required) {
      required.push(field.name);
    }
  }

  const schema: Record<string, unknown> = {
    type: 'object',
    properties,
    additionalProperties: false,
  };

  if (required.length > 0) {
    schema.required = required;
  }

  return schema;
}

// Enum options editor component
function EnumOptionsEditor({
  options,
  onChange,
}: {
  options: string[];
  onChange: (options: string[]) => void;
}) {
  const [inputValue, setInputValue] = useState('');

  const addOption = () => {
    const trimmed = inputValue.trim();
    if (trimmed && !options.includes(trimmed)) {
      onChange([...options, trimmed]);
      setInputValue('');
    }
  };

  const removeOption = (index: number) => {
    onChange(options.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addOption();
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {options.map((option, index) => (
          <span
            key={index}
            className="inline-flex items-center gap-1 px-2 py-0.5 bg-secondary rounded text-xs"
          >
            {option}
            <button
              type="button"
              onClick={() => removeOption(index)}
              className="hover:text-red-text"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-1">
        <Input
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Add option..."
          className="h-7 text-xs"
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addOption}
          className="h-7 px-2"
        >
          Add
        </Button>
      </div>
    </div>
  );
}

// Field editor component
function FieldEditor({
  field,
  onChange,
  onRemove,
  hasNameConflict,
}: {
  field: FieldDefinition;
  onChange: (field: FieldDefinition) => void;
  onRemove: () => void;
  hasNameConflict: boolean;
}) {
  return (
    <div className="p-3 border rounded-md space-y-2 bg-secondary/30">
      <div className="flex items-start gap-3">
        <div className="flex-1 space-y-3">
          <div className="flex gap-3">
            <Input
              value={field.name}
              onChange={(e) => onChange({ ...field, name: e.target.value })}
              placeholder="Field name"
              className={cn(
                'h-7 text-xs flex-1',
                hasNameConflict && 'border-red-border'
              )}
            />
            <Select
              value={field.type}
              onValueChange={(value: FieldType) =>
                onChange({
                  ...field,
                  type: value,
                  enumOptions:
                    value === 'enum' ? field.enumOptions || [] : undefined,
                })
              }
            >
              <SelectTrigger className="h-7 w-32 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="boolean" className="text-xs">
                  Boolean
                </SelectItem>
                <SelectItem value="enum" className="text-xs">
                  Enum
                </SelectItem>
                <SelectItem value="number" className="text-xs">
                  Number
                </SelectItem>
                <SelectItem value="string" className="text-xs">
                  String
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Input
            value={field.description || ''}
            onChange={(e) =>
              onChange({ ...field, description: e.target.value })
            }
            placeholder="Description (optional)"
            className="h-7 text-xs"
          />

          {field.type === 'enum' && (
            <EnumOptionsEditor
              options={field.enumOptions || []}
              onChange={(options) =>
                onChange({ ...field, enumOptions: options })
              }
            />
          )}

          {field.type === 'number' && (
            <div className="flex gap-2">
              <div className="flex items-center gap-1">
                <Label className="text-xs text-muted-foreground">Min:</Label>
                <Input
                  type="number"
                  value={field.minimum ?? ''}
                  onChange={(e) =>
                    onChange({
                      ...field,
                      minimum: e.target.value
                        ? Number(e.target.value)
                        : undefined,
                    })
                  }
                  className="h-7 w-16 text-xs"
                />
              </div>
              <div className="flex items-center gap-1">
                <Label className="text-xs text-muted-foreground">Max:</Label>
                <Input
                  type="number"
                  value={field.maximum ?? ''}
                  onChange={(e) =>
                    onChange({
                      ...field,
                      maximum: e.target.value
                        ? Number(e.target.value)
                        : undefined,
                    })
                  }
                  className="h-7 w-16 text-xs"
                />
              </div>
            </div>
          )}

          <div className="flex items-center gap-2">
            <Checkbox
              id={`required-${field.id}`}
              checked={field.required}
              onCheckedChange={(checked) =>
                onChange({ ...field, required: checked === true })
              }
            />
            <Label htmlFor={`required-${field.id}`} className="text-xs">
              Required
            </Label>
          </div>
        </div>

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRemove}
          className="h-7 w-7 p-0 text-muted-foreground hover:text-red-text"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
      {hasNameConflict && (
        <p className="text-xs text-red-text">Field name must be unique</p>
      )}
    </div>
  );
}

// Preset selector component
function PresetSelector({
  onSelect,
}: {
  onSelect: (fields: FieldDefinition[]) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {PRESETS.map((preset) => {
        const Icon = preset.icon;
        return (
          <button
            key={preset.id}
            type="button"
            onClick={() => {
              // Create fresh fields with new IDs
              const freshFields = preset.fields.map((f) => ({
                ...f,
                id: crypto.randomUUID(),
              }));
              onSelect(freshFields);
            }}
            className="flex flex-col items-center gap-1 p-3 border rounded-md hover:bg-secondary/50 transition-colors text-left"
          >
            <Icon className="h-5 w-5 text-muted-foreground" />
            <span className="text-sm font-medium">{preset.name}</span>
            <span className="text-xs text-muted-foreground text-center">
              {preset.description}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// Visual schema builder component
function VisualSchemaBuilder({
  fields,
  onChange,
}: {
  fields: FieldDefinition[];
  onChange: (fields: FieldDefinition[]) => void;
}) {
  const fieldNameCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const field of fields) {
      if (field.name) {
        counts[field.name] = (counts[field.name] || 0) + 1;
      }
    }
    return counts;
  }, [fields]);

  const updateField = (index: number, field: FieldDefinition) => {
    const newFields = [...fields];
    newFields[index] = field;
    onChange(newFields);
  };

  const removeField = (index: number) => {
    onChange(fields.filter((_, i) => i !== index));
  };

  const addField = () => {
    onChange([...fields, createEmptyField()]);
  };

  return (
    <div className="space-y-2">
      {fields.length === 0 ? (
        <PresetSelector onSelect={onChange} />
      ) : (
        <>
          <div className="max-h-[30vh] custom-scrollbar overflow-y-auto">
            <div className="space-y-2 pr-2">
              {fields.map((field, index) => (
                <FieldEditor
                  key={field.id}
                  field={field}
                  onChange={(f) => updateField(index, f)}
                  onRemove={() => removeField(index)}
                  hasNameConflict={
                    !!field.name && fieldNameCounts[field.name] > 1
                  }
                />
              ))}
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addField}
            className="w-full"
          >
            <Plus className="h-4 w-4 mr-1" />
            Add Field
          </Button>
        </>
      )}
    </div>
  );
}

type PopoverView = 'menu' | 'create';

// Component to display a label card (both existing and draft labels)
type LabelCardProps =
  | {
      mode: 'existing';
      label: LabelData;
      labelSet: LabelSet;
      collectionId: string;
      agentRunId: string;
      hasWritePermission: boolean;
    }
  | {
      mode: 'draft';
      labelSet: LabelSet;
      values: Record<string, any>;
      onValuesChange: (values: Record<string, any>) => void;
      onSave: () => void;
      onCancel: () => void;
      isSaving: boolean;
    };

function LabelCard(props: LabelCardProps) {
  const { mode, labelSet } = props;

  // Internal state for editing existing labels
  const [isEditing, setIsEditing] = useState(false);
  const [editValues, setEditValues] = useState<Record<string, any>>(
    props.mode === 'existing' ? props.label.label_value : {}
  );
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [updateLabel, { isLoading: isUpdating }] = useUpdateLabelMutation();
  const [deleteLabel, { isLoading: isDeleting }] = useDeleteLabelMutation();

  // Derive computed values
  const isDraft = mode === 'draft';
  const showEditUI = isDraft || isEditing;
  const isSaving = isDraft ? props.isSaving : isUpdating;
  const isDisabled = isSaving || isDeleting;

  // Get current values to display
  const currentValues = (() => {
    if (props.mode === 'draft') return props.values;
    return isEditing ? editValues : props.label.label_value;
  })();

  const handleSave = async () => {
    if (props.mode === 'draft') {
      props.onSave();
    } else {
      try {
        await updateLabel({
          collectionId: props.collectionId,
          labelId: props.label.id!,
          label_value: editValues,
          agentRunId: props.agentRunId,
        }).unwrap();
        setIsEditing(false);
      } catch (error) {
        console.error('Failed to update label:', error);
      }
    }
  };

  const handleCancel = () => {
    if (props.mode === 'draft') {
      props.onCancel();
    } else {
      setEditValues(props.label.label_value);
      setIsEditing(false);
    }
  };

  const handleDelete = async () => {
    if (props.mode !== 'existing' || !props.label.id) return;
    try {
      await deleteLabel({
        collectionId: props.collectionId,
        labelId: props.label.id,
        agentRunId: props.agentRunId,
      }).unwrap();
      setIsConfirmingDelete(false);
    } catch (error) {
      console.error('Failed to delete label:', error);
    }
  };

  const handleChange = (key: string, value: any) => {
    if (props.mode === 'draft') {
      props.onValuesChange({ ...props.values, [key]: value });
    } else {
      setEditValues((prev) => ({ ...prev, [key]: value }));
    }
  };

  return (
    <div
      className={cn(
        'border rounded-lg',
        showEditUI
          ? 'border-blue-border bg-blue-bg/30'
          : 'border-border bg-card'
      )}
    >
      {/* Header */}
      <div
        className={cn(
          'flex items-center justify-between p-2 border-b bg-secondary/30',
          isDraft ? 'border-blue-border' : 'border-border'
        )}
      >
        <div className="flex items-center gap-2">
          <Tags className={cn('h-4 w-4', isDraft && 'text-blue-text')} />
          <span className="text-xs font-semibold text-primary">
            {labelSet.name}
          </span>
          {isDraft && (
            <span className="text-xs text-muted-foreground">(New)</span>
          )}
        </div>
        {!isDraft && !isEditing && props.hasWritePermission && (
          <div className="flex items-center gap-2">
            <div
              onClick={() => {
                setIsEditing(true);
                setEditValues(props.label.label_value);
              }}
              className="text-xs cursor-pointer font-medium text-muted-foreground hover:text-primary"
            >
              Edit
            </div>
            {isConfirmingDelete ? (
              <div className="flex items-center gap-1">
                <div
                  onClick={handleDelete}
                  className="text-xs cursor-pointer font-medium text-red-text hover:text-red-text/80"
                >
                  {isDeleting ? 'Deleting...' : 'Delete'}
                </div>
                <span className="text-xs text-muted-foreground">·</span>
                <div
                  onClick={() => setIsConfirmingDelete(false)}
                  className="text-xs cursor-pointer font-medium text-muted-foreground hover:text-primary"
                >
                  Cancel
                </div>
              </div>
            ) : (
              <div
                onClick={() => setIsConfirmingDelete(true)}
                className="text-xs cursor-pointer font-medium text-muted-foreground hover:text-red-text"
              >
                Delete
              </div>
            )}
          </div>
        )}
      </div>
      {/* Body */}
      <div className="p-2">
        <SchemaValueRenderer
          schema={labelSet.label_schema}
          values={currentValues}
          labelValues={{}}
          activeLabelSet={null}
          onSaveLabel={() => {}}
          onClearLabel={() => {}}
          showLabels={false}
          canEditLabels={false}
          renderLabelSetMenu={() => null}
          mode={showEditUI ? 'edit' : 'view'}
          onChange={handleChange}
        />
      </div>
      {/* Footer - shown in edit mode */}
      {showEditUI && (
        <div className="flex items-center justify-end gap-2 p-2 border-t border-border bg-secondary/30">
          <Button
            variant="outline"
            size="sm"
            onClick={handleCancel}
            disabled={isDisabled}
          >
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave} disabled={isDisabled}>
            {isSaving ? 'Saving...' : 'Save'}
          </Button>
        </div>
      )}
    </div>
  );
}

export default function AgentRunLabels({
  agentRunId,
  collectionId,
}: AgentRunLabelsProps) {
  const hasWritePermission = useHasCollectionWritePermission();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<PopoverView>('menu');

  // Form state
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [mode, setMode] = useState<'visual' | 'json'>('visual');
  const [fields, setFields] = useState<FieldDefinition[]>([]);
  const [jsonText, setJsonText] = useState('');
  const [jsonSyntaxError, setJsonSyntaxError] = useState<string | null>(null);
  const [visualSchemaError, setVisualSchemaError] = useState<string | null>(
    null
  );

  // Draft label state
  const [draftLabelSet, setDraftLabelSet] = useState<LabelSet | null>(null);
  const [draftValues, setDraftValues] = useState<Record<string, any>>({});

  const { data: categorizedLabelSets, isLoading: isLoadingLabelSets } =
    useGetCategorizedLabelSetsQuery({
      collectionId,
      agentRunId,
    });
  const {
    data: labels,
    isLoading: isLoadingLabels,
    isFetching: isFetchingLabels,
  } = useGetLabelsForAgentRunQuery({
    collectionId,
    agentRunId,
  });

  // Need both queries to complete before rendering labels
  // Include isFetchingLabels to show loading state during refetch after save
  const isLoading = isLoadingLabels || isLoadingLabelSets || isFetchingLabels;

  // Create a map of label set IDs to label sets for easy lookup
  const labelSetMap = useMemo(() => {
    if (!categorizedLabelSets) return new Map<string, LabelSet>();
    const allLabelSets = [
      ...categorizedLabelSets.available,
      ...categorizedLabelSets.filled,
    ];
    return new Map(allLabelSets.map((ls) => [ls.id, ls]));
  }, [categorizedLabelSets]);
  const [createLabelSet, { isLoading: isCreating }] =
    useCreateLabelSetMutation();
  const [createLabel, { isLoading: isCreatingLabel }] =
    useCreateLabelMutation();

  const { resolvedTheme } = useTheme();
  const codeMirrorExtensions = useMemo(
    () => [jsonLanguage(), EditorView.lineWrapping],
    []
  );

  const resetForm = useCallback(() => {
    setName('');
    setDescription('');
    setMode('visual');
    setFields([]);
    setJsonText('');
    setJsonSyntaxError(null);
    setVisualSchemaError(null);
  }, []);

  const handleOpenChange = (newOpen: boolean) => {
    setOpen(newOpen);
    if (!newOpen) {
      // Reset to menu view and form when closing
      setView('menu');
      resetForm();
    }
  };

  const handleLabelSetSelect = (labelSet: LabelSet) => {
    setDraftLabelSet(labelSet);
    setDraftValues({});
    setOpen(false);
  };

  const switchToCreate = () => {
    setView('create');
  };

  const switchToMenu = () => {
    setView('menu');
    resetForm();
  };

  // Sync between visual and JSON modes
  const handleModeChange = (newMode: 'visual' | 'json') => {
    if (newMode === 'json' && mode === 'visual') {
      // Visual -> JSON: serialize fields
      const schema = fieldsToSchema(fields);
      setJsonText(JSON.stringify(schema, null, 2));
      setJsonSyntaxError(null);
      setVisualSchemaError(null);
    } else if (newMode === 'visual' && mode === 'json') {
      // JSON -> Visual: parse and validate for visual compatibility
      let schema: unknown;
      try {
        schema = JSON.parse(jsonText || '{}');
      } catch {
        setJsonSyntaxError('Invalid JSON - cannot switch to Visual mode');
        return; // Don't switch if JSON is invalid
      }

      const { fields: parsedFields, errors } = parseSchemaForVisual(schema);
      if (errors.length > 0) {
        setVisualSchemaError(`Cannot switch to Visual: ${errors.join(' • ')}`);
        return; // Don't switch if schema has unsupported features
      }

      setFields(parsedFields);
      setJsonSyntaxError(null);
      setVisualSchemaError(null);
    }
    setMode(newMode);
  };

  const handleJsonChange = (value: string) => {
    setJsonText(value);
    // Clear visual schema error when user edits JSON (stale errors disappear as they fix them)
    setVisualSchemaError(null);
    try {
      JSON.parse(value || '{}');
      setJsonSyntaxError(null);
    } catch {
      setJsonSyntaxError('Invalid JSON syntax');
    }
  };

  // Validation
  const validationErrors = useMemo(() => {
    const errors: string[] = [];

    if (!name.trim()) {
      errors.push('Name is required');
    }

    if (mode === 'visual') {
      if (fields.length === 0) {
        errors.push('At least one field is required');
      }

      const emptyNames = fields.filter((f) => !f.name.trim());
      if (emptyNames.length > 0) {
        errors.push('All fields must have a name');
      }

      const names = fields.map((f) => f.name.trim()).filter(Boolean);
      const uniqueNames = new Set(names);
      if (names.length !== uniqueNames.size) {
        errors.push('Field names must be unique');
      }

      const enumsWithoutOptions = fields.filter(
        (f) =>
          f.type === 'enum' && (!f.enumOptions || f.enumOptions.length === 0)
      );
      if (enumsWithoutOptions.length > 0) {
        errors.push('Enum fields must have at least one option');
      }
    } else {
      // Only jsonSyntaxError affects form validation; visualSchemaError does not block saving
      if (jsonSyntaxError) {
        errors.push(jsonSyntaxError);
      } else {
        try {
          const schema = JSON.parse(jsonText || '{}');
          const props = schema.properties;
          if (!props || Object.keys(props).length === 0) {
            errors.push('Schema must have at least one property');
          }
        } catch {
          errors.push('Invalid JSON');
        }
      }
    }

    return errors;
  }, [name, mode, fields, jsonText, jsonSyntaxError]);

  const canSubmit = validationErrors.length === 0 && !isCreating;

  const handleSubmit = async () => {
    if (!canSubmit) return;

    try {
      let schema: Record<string, unknown>;
      if (mode === 'visual') {
        schema = fieldsToSchema(fields);
      } else {
        schema = JSON.parse(jsonText);
      }

      const result = await createLabelSet({
        collectionId,
        name: name.trim(),
        description: description.trim() || null,
        label_schema: schema,
      }).unwrap();

      // Create a LabelSet object from form data for the draft
      const newLabelSet: LabelSet = {
        id: result.label_set_id,
        name: name.trim(),
        description: description.trim() || null,
        label_schema: schema as SchemaDefinition,
      };

      setDraftLabelSet(newLabelSet);
      setDraftValues({});
      setOpen(false);
      setView('menu');
      resetForm();
    } catch (error) {
      console.error('Failed to create label set:', error);
    }
  };

  // Draft label handlers
  const handleDraftSave = async () => {
    if (!draftLabelSet) return;

    try {
      await createLabel({
        collectionId,
        label: {
          label_set_id: draftLabelSet.id,
          label_value: draftValues,
          agent_run_id: agentRunId,
        },
      }).unwrap();

      // Clear draft state on success
      setDraftLabelSet(null);
      setDraftValues({});
    } catch (error) {
      console.error('Failed to create label:', error);
    }
  };

  const handleDraftCancel = () => {
    setDraftLabelSet(null);
    setDraftValues({});
  };

  const handleDraftValuesChange = (values: Record<string, any>) => {
    setDraftValues(values);
  };

  // Render labels section
  const renderLabelsSection = () => {
    return (
      <div className="space-y-2 overflow-y-auto custom-scrollbar flex-1">
        {/* Draft label card - shown at top when creating new label */}
        {draftLabelSet && (
          <LabelCard
            mode="draft"
            labelSet={draftLabelSet}
            values={draftValues}
            onValuesChange={handleDraftValuesChange}
            onSave={handleDraftSave}
            onCancel={handleDraftCancel}
            isSaving={isCreatingLabel}
          />
        )}

        {/* Loading state - wait for both labels and label sets */}
        {isLoading && !draftLabelSet && (
          <div className="flex justify-center">
            <Loader2 size={16} className="animate-spin text-muted-foreground" />
          </div>
        )}

        {/* Empty state - only show if no draft and no labels */}
        {!isLoading && !draftLabelSet && (!labels || labels.length === 0) && (
          <div className="text-xs text-muted-foreground text-center">
            No labels for this agent run.
            {hasWritePermission && ' Click "Add Label" to get started.'}
          </div>
        )}

        {/* Existing labels */}
        {labels?.map((label) => {
          const labelSet = labelSetMap.get(label.label_set_id);
          if (!labelSet) return null;
          return (
            <LabelCard
              key={label.id}
              mode="existing"
              label={label}
              labelSet={labelSet}
              collectionId={collectionId}
              agentRunId={agentRunId}
              hasWritePermission={hasWritePermission}
            />
          );
        })}
      </div>
    );
  };

  return (
    <div className="space-y-3 flex-1 flex flex-col min-h-0">
      {/* Header with Add Label button */}
      <div className="flex justify-end">
        <Popover open={open} onOpenChange={handleOpenChange}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" disabled={!hasWritePermission}>
              <Plus className="h-4 w-4 mr-1" />
              Add Label
            </Button>
          </PopoverTrigger>
          <PopoverContent
            align="end"
            className={cn(
              'p-0 transition-all duration-200',
              view === 'menu' ? 'w-64' : 'w-[500px]'
            )}
          >
            {view === 'menu' ? (
              // Menu view
              <div className="p-1">
                {/* Available label sets - clickable */}
                {categorizedLabelSets &&
                  categorizedLabelSets.available.length > 0 && (
                    <>
                      <p className="px-2 pt-1.5 text-xs text-muted-foreground">
                        Add this label to an existing label set
                      </p>
                      {categorizedLabelSets.available.map((labelSet) => (
                        <button
                          key={labelSet.id}
                          type="button"
                          onClick={() => handleLabelSetSelect(labelSet)}
                          className="flex w-full items-center rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
                        >
                          {labelSet.name}
                        </button>
                      ))}
                      <Separator className="my-1" />
                    </>
                  )}

                {/* Create new label set button */}
                <p className="px-2 pt-1.5 text-xs text-muted-foreground">
                  Create a new set of labels
                </p>
                <button
                  type="button"
                  onClick={switchToCreate}
                  className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
                >
                  <Tags className="h-4 w-4" />
                  Create Label Set
                </button>

                {/* Filled label sets - non-clickable */}
                {categorizedLabelSets &&
                  categorizedLabelSets.filled.length > 0 && (
                    <>
                      <Separator className="my-1" />
                      <p className="px-2 pt-1.5 text-xs text-muted-foreground">
                        Label sets already populated for this run
                      </p>
                      {categorizedLabelSets.filled.map((labelSet) => (
                        <div
                          key={labelSet.id}
                          className="flex w-full items-center rounded-sm px-2 py-1.5 text-sm text-muted-foreground cursor-default"
                        >
                          {labelSet.name}
                        </div>
                      ))}
                    </>
                  )}
              </div>
            ) : (
              // Create view
              <div className="flex flex-col max-h-[80vh]">
                {/* Header */}
                <div className="p-3 border-b">
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={switchToMenu}
                      className="h-3 w-3 p-0"
                    >
                      <ArrowLeft className="h-2 w-2" />
                    </Button>
                    <span className="font-medium text-sm">
                      Create Label Set
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground ml-5">
                    Define a new set of labels with a shared labeling schema
                  </p>
                </div>

                {/* Form */}
                <div className="flex-1 overflow-y-auto p-3 space-y-3">
                  {/* Name */}
                  <div className="space-y-1">
                    <div className="text-xs font-medium">
                      Name <span className="text-red-text">*</span>
                    </div>
                    <Input
                      autoFocus
                      id="name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Enter name"
                      className="h-7 text-xs"
                    />
                  </div>

                  {/* Description */}
                  <div className="space-y-1">
                    <div className="text-xs font-medium">Description</div>
                    <Input
                      id="description"
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      placeholder="Enter description"
                      className="h-7 text-xs"
                    />
                  </div>

                  {/* Schema */}
                  <div className="space-y-1">
                    <div className="text-xs font-medium">
                      Schema <span className="text-red-text">*</span>
                    </div>
                    <Tabs
                      value={mode}
                      onValueChange={(v) =>
                        handleModeChange(v as 'visual' | 'json')
                      }
                    >
                      <TabsList className="w-full h-auto">
                        <TabsTrigger
                          value="visual"
                          className="flex-1 text-xs h-auto py-1"
                        >
                          Visual
                        </TabsTrigger>
                        <TabsTrigger
                          value="json"
                          className="flex-1 text-xs h-auto py-1"
                        >
                          JSON
                        </TabsTrigger>
                      </TabsList>

                      <TabsContent value="visual" className="mt-2">
                        <VisualSchemaBuilder
                          fields={fields}
                          onChange={setFields}
                        />
                      </TabsContent>

                      <TabsContent value="json" className="mt-2">
                        <div className="border rounded-md overflow-hidden">
                          <CodeMirror
                            value={jsonText}
                            height="200px"
                            theme={resolvedTheme === 'dark' ? 'dark' : 'light'}
                            extensions={codeMirrorExtensions}
                            onChange={handleJsonChange}
                            basicSetup={{
                              lineNumbers: true,
                              highlightActiveLine: true,
                              foldGutter: false,
                            }}
                          />
                        </div>
                        {jsonSyntaxError && (
                          <p className="text-xs text-red-text mt-1">
                            {jsonSyntaxError}
                          </p>
                        )}
                        {!jsonSyntaxError && visualSchemaError && (
                          <p className="text-xs text-red-text mt-1">
                            {visualSchemaError}
                          </p>
                        )}
                      </TabsContent>
                    </Tabs>
                  </div>
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between p-3 border-t bg-secondary/30">
                  <div className="text-xs text-muted-foreground">
                    {validationErrors.length > 0 && validationErrors[0]}
                  </div>
                  <div className="flex gap-3">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={switchToMenu}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      onClick={handleSubmit}
                      disabled={!canSubmit}
                    >
                      {isCreating ? 'Creating...' : 'Create'}
                    </Button>
                  </div>
                </div>
              </div>
            )}
          </PopoverContent>
        </Popover>
      </div>

      {/* Labels display section */}
      {renderLabelsSection()}
    </div>
  );
}
