'use client';

import { CircleX, RefreshCw } from 'lucide-react';
import {
  PrimitiveFilter,
  MetadataType,
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
import React, { useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { RootState, AppDispatch } from '../store/store';
import {
  clearSearch,
  addBaseFilter,
  clearBaseFilters,
  removeBaseFilter,
} from '../store/searchSlice';
import { toast } from '@/hooks/use-toast';
import { v4 as uuid4 } from 'uuid';

export const TranscriptFilterControls = () => {
  const dispatch = useDispatch<AppDispatch>();
  const baseFilter = useSelector((state: RootState) => state.collection.baseFilter);
  const agentRunMetadataFields =
    useSelector((state: RootState) => state.collection.agentRunMetadataFields) || [];
  const collectionId = useSelector(
    (state: RootState) => state.collection.collectionId
  );

  const [metadataKey, setMetadataKey] = useState('');
  const [metadataValue, setMetadataValue] = useState('');
  const [metadataType, setMetadataType] = useState<MetadataType | undefined>(
    undefined
  );
  const [metadataOp, setMetadataOp] = useState<string>('==');

  const onUpdateMetadataFilter = (value: string) => {
    if (!collectionId) return;
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
      dispatch(clearSearch());
      dispatch(
        addBaseFilter({
          type: 'primitive',
          key_path: parsedKey.split('.'),
          value: parsedValue,
          op: metadataOp,
          id: uuid4(),
          name: null,
          supports_sql: true,
        } as PrimitiveFilter)
      );
    }
    setMetadataKey('');
    setMetadataValue('');
    setMetadataType(undefined);
    setMetadataOp('==');
  };

  // Auto-select type and op when field changes
  const handleFieldChange = (value: string) => {
    setMetadataKey(value);
    const selectedField = agentRunMetadataFields?.find((f) => f.name === value);
    if (selectedField) {
      setMetadataType(selectedField.type);
      setMetadataValue('');
      setMetadataOp(selectedField.type === 'str' ? '~*' : '==');
    }
  };

  return (
    <div className="border rounded-sm bg-secondary p-1.5 space-y-1.5">
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
              {agentRunMetadataFields?.map((field: TranscriptMetadataField) => (
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
              !collectionId ||
              !metadataKey.trim() ||
              !metadataValue.trim() ||
              metadataType === 'bool' // Disable button for boolean type since it auto-submits
            }
            className="h-7 text-xs whitespace-nowrap px-2"
            size="sm"
          >
            Add filter
          </Button>
        </div>
      </div>

      {/* Current filters */}
      {baseFilter && baseFilter.filters.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-1.5">
          {baseFilter.filters.map((subFilter: CollectionFilter) => (
            <div
              key={subFilter.id}
              className="inline-flex items-center gap-x-1 text-[11px] bg-indigo-bg text-primary border border-indigo-border pl-1.5 pr-1 py-0 rounded-md"
            >
              {(() => {
                if (subFilter.type === 'primitive') {
                  const filterCast = subFilter as PrimitiveFilter;
                  return (
                    <>
                      <span className="font-mono">
                        {filterCast.key_path.join('.')}
                      </span>
                      <span className="text-indigo-400 font-mono">
                        {filterCast.op || '=='}
                      </span>
                      <span className="font-mono">
                        {String(filterCast.value)}
                      </span>
                    </>
                  );
                } else {
                  return `${subFilter.type} filter`;
                }
              })()}
              <button
                onClick={() => dispatch(removeBaseFilter(subFilter.id))}
                className="p-0.5 text-primary hover:text-primary/50 transition-colors"
              >
                <CircleX size={10} />
              </button>
            </div>
          ))}
          <button
            onClick={() => dispatch(clearBaseFilters())}
            className="inline-flex items-center gap-x-1 text-[11px] bg-red-bg text-primary border border-red-border px-1.5 py-0.5 rounded-md hover:bg-red-bg/50 transition-colors"
          >
            Clear
            <RefreshCw size={10} />
          </button>
        </div>
      )}
    </div>
  );
};
