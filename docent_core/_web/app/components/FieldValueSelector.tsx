'use client';

import React, { useState } from 'react';
import { Check, ChevronsUpDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useGetFieldValuesQuery } from '../api/collectionApi';

interface FieldValueSelectorProps {
  collectionId: string;
  fieldName: string;
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

export const FieldValueSelector = ({
  collectionId,
  fieldName,
  value,
  onValueChange,
  placeholder = 'Select value...',
  className,
}: FieldValueSelectorProps) => {
  const [open, setOpen] = useState(false);

  const { data: fieldValuesData, isLoading } = useGetFieldValuesQuery(
    { collectionId, fieldName },
    { skip: !collectionId || !fieldName }
  );

  const values = fieldValuesData?.values || [];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            'h-7 text-xs bg-background font-mono text-muted-foreground justify-between',
            className
          )}
        >
          {value || placeholder}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[200px] p-0">
        <Command>
          <CommandInput placeholder="Search values..." className="h-9" />
          <CommandList>
            <CommandEmpty>
              {isLoading ? 'Loading...' : 'No values found.'}
            </CommandEmpty>
            <CommandGroup>
              {values.map((val) => (
                <CommandItem
                  key={val}
                  value={val}
                  onSelect={(currentValue) => {
                    onValueChange(currentValue === value ? '' : currentValue);
                    setOpen(false);
                  }}
                  className="font-mono text-xs"
                >
                  <Check
                    className={cn(
                      'mr-2 h-4 w-4',
                      value === val ? 'opacity-100' : 'opacity-0'
                    )}
                  />
                  {val}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
};
