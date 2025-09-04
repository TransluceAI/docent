'use client';

import {
  PrimitiveFilter,
  MetadataType,
  ComplexFilter,
} from '@/app/types/collectionTypes';
import { TranscriptMetadataField } from '@/app/types/experimentViewerTypes';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import React, { useState, useRef, useEffect } from 'react';
import { toast } from '@/hooks/use-toast';
import { v4 as uuid4 } from 'uuid';
import { FilterChips } from './FilterChips';
import { SmartValueInput } from './SmartValueInput';

interface FilterControlsProps {
  filters: ComplexFilter | undefined | null;
  onFiltersChange: (filters: ComplexFilter | null) => void;
  metadataFields: TranscriptMetadataField[];
  collectionId: string;
  showFilterChips?: boolean;
  initialFilter?: PrimitiveFilter | null;
}

export const FilterControls = ({
  filters,
  onFiltersChange,
  metadataFields,
  collectionId,
  showFilterChips = true,
  initialFilter = null,
}: FilterControlsProps) => {
  const [metadataKey, setMetadataKey] = useState('');
  const [metadataValue, setMetadataValue] = useState('');
  const [metadataType, setMetadataType] = useState<MetadataType | undefined>(
    undefined
  );
  const [metadataOp, setMetadataOp] = useState<string>('==');
  const valueFieldRef = useRef<HTMLInputElement>(null);

  // Populate form when initialFilter is provided
  useEffect(() => {
    if (initialFilter) {
      setMetadataKey(initialFilter.key_path.join('.'));
      setMetadataValue(String(initialFilter.value));
      setMetadataOp(initialFilter.op || '==');

      // Set the metadata type based on the value type
      if (typeof initialFilter.value === 'boolean') {
        setMetadataType('bool');
      } else if (typeof initialFilter.value === 'number') {
        setMetadataType(
          Number.isInteger(initialFilter.value) ? 'int' : 'float'
        );
      } else {
        setMetadataType('str');
      }
    }
  }, [initialFilter]);

  const onUpdateMetadataFilter = (value: string) => {
    if (!metadataKey.trim()) {
      toast({
        title: 'Missing key',
        description: 'Please enter a metadata key',
        variant: 'destructive',
      });
      return;
    }

    let parsedKey;
    let parsedValue;
    if (!value) {
      parsedKey = null;
      parsedValue = null;
    } else {
      parsedKey = metadataKey.trim();
      parsedValue = value;
      if (metadataType === 'bool') {
        parsedValue = value === 'true';
      } else if (metadataType === 'int' || metadataType === 'float') {
        parsedValue = Number(value);
        if (isNaN(parsedValue)) {
          toast({
            title: 'Invalid number',
            description: 'Please enter a valid number',
            variant: 'destructive',
          });
          return;
        }
      }

      const newFilter: PrimitiveFilter = {
        type: 'primitive',
        key_path: parsedKey.split('.'),
        value: parsedValue,
        op: metadataOp,
        id: uuid4(),
        name: null,
        supports_sql: true,
      };

      const newComplexFilter: ComplexFilter = filters
        ? {
            ...filters,
            filters: [...filters.filters, newFilter],
          }
        : {
            id: uuid4(),
            name: null,
            type: 'complex',
            filters: [newFilter],
            op: 'and',
            supports_sql: true,
          };

      onFiltersChange(newComplexFilter);
    }
    setMetadataKey('');
    setMetadataValue('');
    setMetadataType(undefined);
    setMetadataOp('==');
  };

  const removeFilter = (filterId: string) => {
    if (!filters) return;

    const updatedFilters = filters.filters.filter((f) => f.id !== filterId);

    if (updatedFilters.length === 0) {
      onFiltersChange(null);
    } else {
      onFiltersChange({
        ...filters,
        filters: updatedFilters,
      });
    }
  };

  const editFilter = (filter: PrimitiveFilter) => {
    // Remove the filter first
    removeFilter(filter.id);

    // Populate the form with the filter's values
    setMetadataKey(filter.key_path.join('.'));
    setMetadataValue(String(filter.value));
    setMetadataOp(filter.op || '==');

    // Set the metadata type based on the value type
    if (typeof filter.value === 'boolean') {
      setMetadataType('bool');
    } else if (typeof filter.value === 'number') {
      setMetadataType(Number.isInteger(filter.value) ? 'int' : 'float');
    } else {
      setMetadataType('str');
    }

    // Focus the value field after a short delay to ensure the form is updated
    setTimeout(() => {
      valueFieldRef.current?.focus();
    }, 100);
  };

  const handleOperatorChange = (value: string) => {
    setMetadataOp(value);

    // Focus the value field after a short delay
    setTimeout(() => {
      valueFieldRef.current?.focus();
    }, 100);
  };

  const clearAllFilters = () => {
    onFiltersChange(null);
  };

  // Auto-select type and op when field changes
  const handleFieldChange = (value: string) => {
    setMetadataKey(value);
    const selectedField = metadataFields?.find((f) => f.name === value);
    if (selectedField) {
      setMetadataType(selectedField.type);
      setMetadataValue('');

      // Preserve the current operator if it's valid for the new field type
      const currentOp = metadataOp;
      const validOpsForType =
        selectedField.type === 'str'
          ? ['~*', '==', '!=']
          : ['==', '!=', '<', '<=', '>', '>='];

      if (validOpsForType.includes(currentOp)) {
        // Keep the current operator if it's valid for the new field type
        setMetadataOp(currentOp);
      } else {
        // Set default operator for the field type
        setMetadataOp(selectedField.type === 'str' ? '~*' : '==');
      }

      // Focus the value field after a short delay
      setTimeout(() => {
        valueFieldRef.current?.focus();
      }, 100);
    }
  };

  return (
    <div className="space-y-1.5">
      {/* Input form */}
      <div className="grid grid-cols-[1fr_auto_1fr_auto] gap-1.5">
        <div>
          <div className="text-xs text-muted-foreground font-mono ml-1 mb-1">
            Filter by
          </div>
          <Select value={metadataKey} onValueChange={handleFieldChange}>
            <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground">
              <SelectValue placeholder="Select field" />
            </SelectTrigger>
            <SelectContent>
              {metadataFields?.map((field: TranscriptMetadataField) => (
                <SelectItem
                  key={field.name}
                  value={field.name}
                  className="font-mono text-muted-foreground text-xs"
                >
                  {field.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {metadataType === 'int' || metadataType === 'float' ? (
          <div>
            <div className="text-xs text-muted-foreground font-mono mr-1 mb-1">
              Operator
            </div>
            <Select value={metadataOp} onValueChange={handleOperatorChange}>
              <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground w-16">
                <SelectValue placeholder="==" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="==" className="font-mono text-xs">
                  ==
                </SelectItem>
                <SelectItem value="!=" className="font-mono text-xs">
                  !=
                </SelectItem>
                <SelectItem value="<" className="font-mono text-xs">
                  &lt;
                </SelectItem>
                <SelectItem value="<=" className="font-mono text-xs">
                  &lt;=
                </SelectItem>
                <SelectItem value=">" className="font-mono text-xs">
                  &gt;
                </SelectItem>
                <SelectItem value=">=" className="font-mono text-xs">
                  &gt;=
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        ) : (
          <div>
            <div className="text-xs text-muted-foreground font-mono mr-1 mb-1">
              Operator
            </div>
            <Select value={metadataOp} onValueChange={handleOperatorChange}>
              <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground w-16">
                <SelectValue placeholder="==" />
              </SelectTrigger>
              <SelectContent>
                {metadataType === 'str' && (
                  <SelectItem value="~*" className="font-mono text-xs">
                    ~*
                  </SelectItem>
                )}
                <SelectItem value="==" className="font-mono text-xs">
                  ==
                </SelectItem>
                <SelectItem value="!=" className="font-mono text-xs">
                  !=
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
        <div>
          <div className="text-xs text-muted-foreground font-mono ml-1 mb-1">
            Value{metadataType ? ` (${metadataType})` : ''}
          </div>
          {metadataType === 'bool' ? (
            <Select
              value={metadataValue}
              onValueChange={onUpdateMetadataFilter}
            >
              <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground">
                <SelectValue placeholder="Select value" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="true" className="font-mono text-xs">
                  true
                </SelectItem>
                <SelectItem value="false" className="font-mono text-xs">
                  false
                </SelectItem>
              </SelectContent>
            </Select>
          ) : metadataType === 'str' ? (
            <SmartValueInput
              ref={valueFieldRef}
              collectionId={collectionId}
              fieldName={metadataKey}
              value={metadataValue}
              onValueChange={setMetadataValue}
              onEnter={() => onUpdateMetadataFilter(metadataValue)}
              placeholder="Enter value..."
            />
          ) : (
            <Input
              ref={valueFieldRef}
              value={metadataValue}
              onChange={(e) => setMetadataValue(e.target.value)}
              placeholder={metadataType === 'int' ? 'e.g. 42' : 'e.g. value'}
              type={metadataType === 'int' ? 'number' : 'text'}
              className="h-7 text-xs bg-background font-mono text-muted-foreground"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  onUpdateMetadataFilter(metadataValue);
                }
              }}
            />
          )}
        </div>
        <div>
          <div className="text-xs text-muted-foreground mb-1">&nbsp;</div>
          <Button
            onClick={() => onUpdateMetadataFilter(metadataValue)}
            disabled={
              !metadataKey.trim() ||
              !metadataValue.trim() ||
              metadataType === 'bool' // Disable button for boolean type since it auto-submits
            }
            className="h-7 text-xs whitespace-nowrap px-2"
            size="sm"
          >
            Add Filter
          </Button>
        </div>
      </div>

      {/* Current filters */}
      {showFilterChips && (
        <FilterChips
          filters={filters}
          onRemoveFilter={removeFilter}
          onEditFilter={editFilter}
          onClearAllFilters={clearAllFilters}
          className="mb-1.5"
        />
      )}
    </div>
  );
};
