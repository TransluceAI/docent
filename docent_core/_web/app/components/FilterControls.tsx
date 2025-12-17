'use client';

import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  PrimitiveFilter,
  MetadataType,
  ComplexFilter,
  CollectionFilter,
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
import { toast } from 'sonner';
import { v4 as uuid4 } from 'uuid';
import { SmartValueInput } from './SmartValueInput';
import { SingleCombobox } from './Combobox';
import { StepFilter } from './StepFilter';
import { formatFilterFieldLabel } from '../utils/formatMetadataField';

const isStepEqualityPrimitiveFilter = (
  filterItem: CollectionFilter
): filterItem is PrimitiveFilter => {
  if (filterItem.type !== 'primitive') {
    return false;
  }

  const isStepField = filterItem.key_path.join('.') === 'metadata.step';
  const isEqualityOp = filterItem.op === '==';
  const isIntegerValue =
    typeof filterItem.value === 'number' && Number.isInteger(filterItem.value);

  return isStepField && isEqualityOp && isIntegerValue;
};

interface FilterControlsProps {
  filters: ComplexFilter | undefined | null;
  onFiltersChange: (filters: ComplexFilter | null) => void;
  metadataFields: TranscriptMetadataField[];
  collectionId: string;
  metadataData?: Record<string, Record<string, unknown>>;
  showStepFilter?: boolean;
  initialFilter?: PrimitiveFilter | null;
}

export const FilterControls = ({
  filters,
  onFiltersChange,
  metadataFields,
  collectionId,
  metadataData = {},
  showStepFilter = true,
  initialFilter = null,
}: FilterControlsProps) => {
  const [metadataKey, setMetadataKey] = useState('');
  const [metadataValue, setMetadataValue] = useState('');
  const [metadataType, setMetadataType] = useState<MetadataType | undefined>(
    undefined
  );
  const [metadataOp, setMetadataOp] = useState<string>('==');
  const [nullSelectOpen, setNullSelectOpen] = useState(false);
  const [stepFilterValue, setStepFilterValue] = useState<number | null>(null);
  const valueFieldRef = useRef<HTMLInputElement>(null);
  const isNullOperator = metadataOp === 'is';

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

  // Sync step filter state with existing filters
  useEffect(() => {
    if (!filters?.filters) {
      setStepFilterValue(null);
      return;
    }

    const equalityFilter = filters.filters.find(isStepEqualityPrimitiveFilter);
    if (equalityFilter) {
      setStepFilterValue(equalityFilter.value);
      return;
    }

    setStepFilterValue(null);
  }, [filters]);

  const onUpdateMetadataFilter = (value: string) => {
    if (!metadataKey.trim()) {
      toast.error('Please enter a metadata key');
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
      if (metadataOp === 'is') {
        const normalized = value.trim().toLowerCase();
        const isValidNullCheck =
          normalized === 'null' || normalized === 'not null';
        if (!isValidNullCheck) {
          toast.error('Select either "null" or "not null"');
          return;
        }
      } else if (metadataType === 'bool') {
        parsedValue = value === 'true';
      } else if (metadataType === 'int' || metadataType === 'float') {
        parsedValue = Number(value);
        if (isNaN(parsedValue)) {
          toast.error('Please enter a valid number');
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
        disabled: false,
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

  const handleOperatorChange = (value: string) => {
    setMetadataOp(value);
    if (value === 'is') {
      setMetadataValue('');
      setNullSelectOpen(true);
    }

    // Focus the value field after a short delay
    if (value !== 'is') {
      setNullSelectOpen(false);
      setTimeout(() => {
        valueFieldRef.current?.focus();
      }, 100);
    }
  };

  // Handle step filter changes
  const handleStepFilterChange = useCallback(
    (stepValue: number | null) => {
      setStepFilterValue(stepValue);

      // Remove any existing step filter
      const currentFilters =
        filters?.filters.filter((f) => !isStepEqualityPrimitiveFilter(f)) || [];

      if (stepValue === null) {
        // No step filter
        if (currentFilters.length === 0) {
          onFiltersChange(null);
        } else {
          onFiltersChange({
            ...filters!,
            filters: currentFilters,
          });
        }
      } else {
        // Add step filter
        const stepFilter: PrimitiveFilter = {
          type: 'primitive',
          key_path: ['metadata', 'step'],
          value: stepValue,
          op: '==',
          id: uuid4(),
          name: null,
          supports_sql: true,
          disabled: false,
        };

        const newComplexFilter: ComplexFilter = {
          id: uuid4(),
          name: null,
          type: 'complex',
          filters: [...currentFilters, stepFilter],
          op: 'and',
          supports_sql: true,
        };

        onFiltersChange(newComplexFilter);
      }
    },
    [filters]
  );

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
          ? ['~*', '==', '!=', '<', '<=', '>', '>=', 'is']
          : selectedField.type === 'bool'
            ? ['==', '!=', 'is']
            : ['==', '!=', '<', '<=', '>', '>=', 'is'];

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
          <SingleCombobox
            value={metadataKey || null}
            onChange={handleFieldChange}
            options={metadataFields.map((field) => ({
              value: field.name,
              label: formatFilterFieldLabel(field.name),
            }))}
            placeholder="Select field"
            searchPlaceholder="Search fields..."
            emptyMessage="No fields found."
            triggerClassName="w-full justify-between bg-background font-mono text-muted-foreground"
            commandInputClassName="h-8 text-xs"
            commandListClassName="custom-scrollbar"
            optionClassName="font-mono text-xs"
            popoverClassName="max-w-[640px]"
            popoverStyle={{
              width: 'auto',
              minWidth: 'var(--radix-popover-trigger-width)',
              maxWidth: '640px',
            }}
          />
        </div>
        {metadataType === 'int' || metadataType === 'float' ? (
          <div>
            <div className="text-xs text-muted-foreground font-mono mr-1 mb-1">
              Operator
            </div>
            <Select value={metadataOp} onValueChange={handleOperatorChange}>
              <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground w-16 hover:bg-secondary hover:text-primary">
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
                <SelectItem value="is" className="font-mono text-xs">
                  is
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
              <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground w-16 hover:bg-secondary hover:text-primary">
                <SelectValue placeholder="==" />
              </SelectTrigger>
              <SelectContent>
                {metadataType === 'str' && (
                  <>
                    <SelectItem value="~*" className="font-mono text-xs">
                      ~*
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
                  </>
                )}
                <SelectItem value="==" className="font-mono text-xs">
                  ==
                </SelectItem>
                <SelectItem value="!=" className="font-mono text-xs">
                  !=
                </SelectItem>
                <SelectItem value="is" className="font-mono text-xs">
                  is
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
        <div>
          <div className="text-xs text-muted-foreground font-mono ml-1 mb-1">
            Value{metadataType ? ` (${metadataType})` : ''}
          </div>
          {isNullOperator ? (
            <Select
              value={metadataValue}
              open={nullSelectOpen}
              onOpenChange={setNullSelectOpen}
              onValueChange={(val) => {
                setMetadataValue(val);
                onUpdateMetadataFilter(val);
                setNullSelectOpen(false);
              }}
            >
              <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground hover:bg-secondary hover:text-primary">
                <SelectValue placeholder="Select value" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="null" className="font-mono text-xs">
                  null
                </SelectItem>
                <SelectItem value="not null" className="font-mono text-xs">
                  not null
                </SelectItem>
              </SelectContent>
            </Select>
          ) : metadataType === 'bool' ? (
            <Select
              value={metadataValue}
              onValueChange={onUpdateMetadataFilter}
            >
              <SelectTrigger className="h-7 text-xs bg-background font-mono text-muted-foreground hover:bg-secondary hover:text-primary">
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
              onSelect={(value) => onUpdateMetadataFilter(value)}
              placeholder="Enter value..."
            />
          ) : (
            <Input
              ref={valueFieldRef}
              value={metadataValue}
              onChange={(e) => setMetadataValue(e.target.value)}
              placeholder={metadataType === 'int' ? 'e.g. 42' : 'e.g. value'}
              type={metadataType === 'int' ? 'number' : 'text'}
              className="h-7 text-xs bg-background font-mono text-muted-foreground hover:bg-secondary hover:text-primary"
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
              (metadataType === 'bool' && metadataOp !== 'is') // Disable button for boolean type since it auto-submits
            }
            className="h-7 text-xs whitespace-nowrap px-2"
            size="sm"
          >
            Add filter
          </Button>
        </div>
      </div>

      {/* Step Filter */}
      {showStepFilter && (
        <StepFilter
          collectionId={collectionId}
          metadataData={metadataData}
          onStepFilterChange={handleStepFilterChange}
          currentValue={stepFilterValue}
          disabled={false}
        />
      )}
    </div>
  );
};
