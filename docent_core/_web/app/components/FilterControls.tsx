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
import React, { useState } from 'react';
import { toast } from '@/hooks/use-toast';
import { v4 as uuid4 } from 'uuid';
import { FilterChips } from './FilterChips';
import { FieldValueSelector } from './FieldValueSelector';

interface FilterControlsProps {
  filters: ComplexFilter | undefined | null;
  onFiltersChange: (filters: ComplexFilter | null) => void;
  metadataFields: TranscriptMetadataField[];
  collectionId: string;
  className?: string;
  showFilterChips?: boolean;
}

export const FilterControls = ({
  filters,
  onFiltersChange,
  metadataFields,
  collectionId,
  className,
  showFilterChips = true,
}: FilterControlsProps) => {
  const [metadataKey, setMetadataKey] = useState('');
  const [metadataValue, setMetadataValue] = useState('');
  const [metadataType, setMetadataType] = useState<MetadataType | undefined>(
    undefined
  );
  const [metadataOp, setMetadataOp] = useState<string>('==');

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
      setMetadataOp(selectedField.type === 'str' ? '~*' : '==');
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
            <Select value={metadataOp} onValueChange={setMetadataOp}>
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
            <Select value={metadataOp} onValueChange={setMetadataOp}>
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
          ) : metadataType === 'str' && metadataOp === '==' ? (
            <FieldValueSelector
              collectionId={collectionId}
              fieldName={metadataKey}
              value={metadataValue}
              onValueChange={onUpdateMetadataFilter}
              placeholder={
                metadataType === 'str' ? 'Select value...' : 'Select value...'
              }
              className="w-full"
            />
          ) : (
            <Input
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
          onClearAllFilters={clearAllFilters}
          className="mb-1.5"
        />
      )}
    </div>
  );
};
