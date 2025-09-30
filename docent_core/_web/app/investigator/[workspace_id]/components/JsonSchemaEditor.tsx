import React, { useState, useEffect } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { json as jsonLanguage } from '@codemirror/lang-json';
import { useTheme } from 'next-themes';
import { Button } from '@/components/ui/button';
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
import { Trash2, Plus, Code2, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';

interface JsonSchemaProperty {
  type: string;
  description?: string;
  properties?: Record<string, JsonSchemaProperty>;
  items?: JsonSchemaProperty;
  enum?: string[];
}

interface JsonSchema {
  type: 'object';
  properties: Record<string, JsonSchemaProperty>;
  required: string[];
  additionalProperties?: boolean;
}

interface JsonSchemaEditorProps {
  value: JsonSchema;
  onChange: (schema: JsonSchema) => void;
  className?: string;
}

const PRIMITIVE_TYPES = ['string', 'number', 'integer', 'boolean'];
const COMPLEX_TYPES = ['object', 'array'];
const ALL_TYPES = [...PRIMITIVE_TYPES, ...COMPLEX_TYPES];

const generateId = () =>
  `prop_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

export function JsonSchemaEditor({
  value,
  onChange,
  className,
}: JsonSchemaEditorProps) {
  const [expandedProperties, setExpandedProperties] = useState<Set<string>>(
    new Set()
  );
  const [jsonEditMode, setJsonEditMode] = useState(false);
  const [jsonText, setJsonText] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [lastValidJson, setLastValidJson] = useState<JsonSchema>(value);
  const [propertyIds, setPropertyIds] = useState<Record<string, string>>({});
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const currentProps = Object.keys(value.properties);
    setPropertyIds((prev) => {
      const newIds = { ...prev };
      currentProps.forEach((propName) => {
        if (!newIds[propName]) {
          newIds[propName] = generateId();
        }
      });
      // Remove IDs for properties that no longer exist
      Object.keys(newIds).forEach((propName) => {
        if (!currentProps.includes(propName)) {
          delete newIds[propName];
        }
      });
      return newIds;
    });
  }, [value.properties]);

  // Update lastValidJson when value changes from parent
  useEffect(() => {
    if (!jsonEditMode) {
      setLastValidJson(value);
    }
  }, [value, jsonEditMode]);

  const toggleJsonEditMode = () => {
    if (!jsonEditMode) {
      // Entering JSON edit mode
      setJsonText(JSON.stringify(value, null, 2));
      setJsonError(null);
      setJsonEditMode(true);
    } else {
      // Exiting JSON edit mode - only allow if JSON is valid
      if (jsonError) {
        return; // Don't allow switching back if there's an error
      }
      setJsonEditMode(false);
    }
  };

  const handleJsonTextChange = (text: string) => {
    setJsonText(text);

    try {
      const parsed = JSON.parse(text);

      // Validate that it's a proper JSON schema object
      if (typeof parsed !== 'object' || Array.isArray(parsed)) {
        setJsonError('JSON must be an object');
        return;
      }

      if (parsed.type !== 'object') {
        setJsonError('Schema type must be "object"');
        return;
      }

      if (
        typeof parsed.properties !== 'object' ||
        Array.isArray(parsed.properties)
      ) {
        setJsonError('Properties must be an object');
        return;
      }

      if (parsed.required && !Array.isArray(parsed.required)) {
        setJsonError('Required must be an array if provided');
        return;
      }

      // Ensure required array exists (default to empty if not provided)
      const normalizedSchema = {
        type: 'object' as const,
        properties: parsed.properties || {},
        required: parsed.required || [],
        additionalProperties: parsed.additionalProperties ?? false,
      };

      // If validation passes, update the schema
      setJsonError(null);
      onChange(normalizedSchema);
      setLastValidJson(normalizedSchema);
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : 'Invalid JSON');
    }
  };

  const resetToLastValid = () => {
    setJsonText(JSON.stringify(lastValidJson, null, 2));
    setJsonError(null);
    onChange(lastValidJson);
  };

  const updateProperty = (
    propertyName: string,
    updates: Partial<JsonSchemaProperty>
  ) => {
    const newSchema = {
      ...value,
      properties: {
        ...value.properties,
        [propertyName]: {
          ...value.properties[propertyName],
          ...updates,
        },
      },
    };
    onChange(newSchema);
  };

  const addProperty = () => {
    const newPropertyName = `property_${Object.keys(value.properties).length + 1}`;
    setPropertyIds((prev) => ({
      ...prev,
      [newPropertyName]: generateId(),
    }));
    const newSchema = {
      ...value,
      properties: {
        ...value.properties,
        [newPropertyName]: {
          type: 'string',
          description: '',
        },
      },
    };
    onChange(newSchema);
  };

  const removeProperty = (propertyName: string) => {
    const { [propertyName]: removed, ...remainingProperties } =
      value.properties;
    const newRequired = value.required.filter((req) => req !== propertyName);
    const newSchema = {
      ...value,
      properties: remainingProperties,
      required: newRequired,
    };
    setPropertyIds((prev) => {
      const newIds = { ...prev };
      delete newIds[propertyName];
      return newIds;
    });
    onChange(newSchema);
  };

  const toggleRequired = (propertyName: string, isRequired: boolean) => {
    const newRequired = isRequired
      ? [...value.required, propertyName]
      : value.required.filter((req) => req !== propertyName);

    onChange({
      ...value,
      required: newRequired,
    });
  };

  const renameProperty = (oldName: string, newName: string) => {
    if (oldName === newName || !newName.trim()) return;

    const { [oldName]: property, ...otherProperties } = value.properties;
    const newRequired = value.required.map((req) =>
      req === oldName ? newName : req
    );

    onChange({
      ...value,
      properties: {
        ...otherProperties,
        [newName]: property,
      },
      required: newRequired,
    });

    setPropertyIds((prev) => {
      const newIds = { ...prev };
      newIds[newName] = newIds[oldName];
      delete newIds[oldName];
      return newIds;
    });
  };

  const toggleExpanded = (propertyName: string) => {
    const newExpanded = new Set(expandedProperties);
    if (newExpanded.has(propertyName)) {
      newExpanded.delete(propertyName);
    } else {
      newExpanded.add(propertyName);
    }
    setExpandedProperties(newExpanded);
  };

  const renderProperty = (
    propertyName: string,
    property: JsonSchemaProperty,
    depth = 0
  ) => {
    const isRequired = value.required.includes(propertyName);
    const isExpanded = expandedProperties.has(propertyName);
    const indent = depth * 20;

    return (
      <div
        key={propertyIds[propertyName] || propertyName}
        className="border rounded p-3 space-y-2"
        style={{ marginLeft: indent }}
      >
        <div className="flex items-center gap-2">
          <Input
            value={propertyName}
            onChange={(e) => renameProperty(propertyName, e.target.value)}
            className="flex-1 text-xs"
            placeholder="Property name"
          />
          <Select
            value={property.type}
            onValueChange={(type) => updateProperty(propertyName, { type })}
          >
            <SelectTrigger className="w-24 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ALL_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex items-center space-x-1">
            <Checkbox
              id={`required-${propertyName}`}
              checked={isRequired}
              onCheckedChange={(checked) =>
                toggleRequired(propertyName, !!checked)
              }
            />
            <Label htmlFor={`required-${propertyName}`} className="text-xs">
              Required
            </Label>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => removeProperty(propertyName)}
            className="h-6 w-6 p-0"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>

        <Input
          value={property.description || ''}
          onChange={(e) =>
            updateProperty(propertyName, { description: e.target.value })
          }
          placeholder="Description"
          className="text-xs"
        />

        {property.type === 'object' && (
          <div className="space-y-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => toggleExpanded(propertyName)}
              className="text-xs"
            >
              {isExpanded ? 'Collapse' : 'Expand'} Object Properties
            </Button>
            {isExpanded && (
              <div className="space-y-2 pl-4 border-l">
                {property.properties &&
                  Object.entries(property.properties).map(
                    ([subName, subProperty]) =>
                      renderProperty(
                        `${propertyName}.${subName}`,
                        subProperty,
                        depth + 1
                      )
                  )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    const newProperties = {
                      ...property.properties,
                      [`property_${Object.keys(property.properties || {}).length + 1}`]:
                        {
                          type: 'string',
                          description: '',
                        },
                    };
                    updateProperty(propertyName, { properties: newProperties });
                  }}
                  className="text-xs"
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add Property
                </Button>
              </div>
            )}
          </div>
        )}

        {property.type === 'array' && (
          <div className="space-y-2">
            <Label className="text-xs">Array Item Type</Label>
            <Select
              value={property.items?.type || 'string'}
              onValueChange={(type) =>
                updateProperty(propertyName, {
                  items: { ...property.items, type },
                })
              }
            >
              <SelectTrigger className="text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ALL_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex items-center justify-between">
        <Label className="text-xs font-medium">JSON Schema Properties</Label>
        <div className="flex gap-2">
          {!jsonEditMode && (
            <Button
              variant="outline"
              size="sm"
              onClick={addProperty}
              className="text-xs"
              type="button"
            >
              <Plus className="h-3 w-3 mr-1" />
              Add Property
            </Button>
          )}
          <Button
            type="button"
            variant={jsonEditMode ? 'default' : 'outline'}
            size="sm"
            onClick={toggleJsonEditMode}
            disabled={jsonEditMode && !!jsonError}
            title={
              jsonEditMode && jsonError
                ? 'Fix JSON errors before switching back'
                : undefined
            }
          >
            <Code2 className="h-4 w-4 mr-2" />
            {jsonEditMode ? 'Visual Editor' : 'Edit JSON'}
          </Button>
          {jsonEditMode && jsonError && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={resetToLastValid}
            >
              <RefreshCw className="h-4 w-4 mr-2" />
              Reset
            </Button>
          )}
        </div>
      </div>

      {jsonEditMode ? (
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">
            Edit the JSON schema directly. Must be a valid JSON object with type
            &quot;object&quot; and a properties field.
          </div>
          <CodeMirror
            value={jsonText}
            onChange={handleJsonTextChange}
            extensions={[jsonLanguage()]}
            theme={resolvedTheme === 'dark' ? 'dark' : 'light'}
            className={cn(
              'border rounded-md overflow-hidden text-xs',
              jsonError ? 'border-red-border' : 'border-border'
            )}
            basicSetup={{
              lineNumbers: true,
              foldGutter: true,
              bracketMatching: true,
            }}
            style={{ fontSize: '12px' }}
          />
          {jsonError && (
            <div className="text-xs text-red-text bg-red-bg/20 p-2 rounded border border-red-border">
              <strong>JSON Validation Error:</strong> {jsonError}
              <div className="mt-1 text-xs opacity-80">
                Use the Reset button to restore the last valid state.
              </div>
            </div>
          )}
          {!jsonError && (
            <div className="text-xs text-green-text">✓ Valid JSON schema</div>
          )}
        </div>
      ) : (
        <>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {Object.entries(value.properties).map(([propertyName, property]) =>
              renderProperty(propertyName, property)
            )}
          </div>

          {Object.keys(value.properties).length === 0 && (
            <div className="text-center py-8 text-muted-foreground text-xs">
              No properties defined. Click &quot;Add Property&quot; to get
              started.
            </div>
          )}
        </>
      )}
    </div>
  );
}
