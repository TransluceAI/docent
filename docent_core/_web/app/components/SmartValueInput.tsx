'use client';

import React, {
  useState,
  useRef,
  useEffect,
  useMemo,
  useCallback,
} from 'react';
import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from '@/components/ui/popover';
import { Command as CommandPrimitive } from 'cmdk';
import { useGetFieldValuesQuery } from '../api/collectionApi';
import { useDebounce } from '../../hooks/use-debounce';

interface SmartValueInputProps {
  collectionId: string;
  fieldName: string;
  value: string;
  onValueChange: (value: string) => void;
  onEnter?: () => void;
  onSelect?: (value: string) => void;
  placeholder?: string;
  className?: string;
  type?: 'text' | 'number';
}

export const SmartValueInput = React.forwardRef<
  HTMLInputElement,
  SmartValueInputProps
>(
  (
    {
      collectionId,
      fieldName,
      value,
      onValueChange,
      onEnter,
      onSelect,
      placeholder = 'Enter value...',
      className,
      type = 'text',
    },
    ref
  ) => {
    const [open, setOpen] = useState(false);
    const [inputValue, setInputValue] = useState(value);
    const [selectedValue, setSelectedValue] = useState<string>('');
    const inputRef = useRef<HTMLInputElement>(null);
    const resolvedRef = (ref as React.RefObject<HTMLInputElement>) || inputRef;

    // Debounce search to avoid too many API calls
    const debouncedSearch = useDebounce(inputValue, 300);

    // Only enable dropdown for certain field types
    const isDropdownField =
      fieldName.startsWith('metadata.') || fieldName === 'tag';

    const { data: fieldValuesData, isFetching } = useGetFieldValuesQuery(
      {
        collectionId,
        fieldName,
        search: debouncedSearch || undefined,
      },
      {
        skip: !collectionId || !fieldName || !isDropdownField,
      }
    );

    const values = fieldValuesData?.values || [];

    // Filter values client-side for immediate feedback
    const displayValues = useMemo(() => {
      if (!inputValue) return values;
      return values.filter((val) =>
        val.toLowerCase().includes(inputValue.toLowerCase())
      );
    }, [inputValue, values]);

    // Sync input value with prop
    useEffect(() => {
      setInputValue(value);
    }, [value]);

    // Close dropdown when field changes
    useEffect(() => {
      setOpen(false);
    }, [fieldName]);

    // Auto-select first item when filtered values change
    useEffect(() => {
      if (displayValues.length > 0) {
        setSelectedValue(displayValues[0]);
      } else {
        setSelectedValue('');
      }
    }, [displayValues]);

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const newValue = e.target.value;
      setInputValue(newValue);
      onValueChange(newValue);

      // Open dropdown if we're a dropdown field and have focus
      if (isDropdownField) {
        setOpen(true);
      }
    };

    const handleSelect = (selectedValue: string) => {
      setInputValue(selectedValue);
      onValueChange(selectedValue);
      setOpen(false);
      onSelect?.(selectedValue);
      // Refocus input after selection
      resolvedRef?.current?.focus();
    };

    const handleFocus = () => {
      if (isDropdownField) {
        setOpen(true);
      }
    };

    // Only close when focus leaves both input and popover
    const handleBlur = useCallback((e: React.FocusEvent) => {
      const relatedTarget = e.relatedTarget as Element | null;
      if (relatedTarget?.closest('[data-radix-popper-content-wrapper]')) {
        return;
      }
      setOpen(false);
    }, []);

    // Handle popover's onOpenChange - only allow closing via blur/escape/select
    const handleOpenChange = useCallback(
      (newOpen: boolean) => {
        if (!newOpen) {
          // Only close if input is not focused (user clicked outside)
          if (document.activeElement !== resolvedRef?.current) {
            setOpen(false);
          }
        }
      },
      [resolvedRef]
    );

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        // If dropdown is open, let cmdk handle selection first
        if (showDropdown && displayValues.length > 0) {
          // Don't prevent default - let cmdk select the highlighted item
          return;
        }
        e.preventDefault();
        setOpen(false);
        onEnter?.();
      } else if (e.key === 'Escape') {
        setOpen(false);
      }
    };

    const isSearching = isFetching || inputValue !== debouncedSearch;
    const showDropdown = open && isDropdownField;

    return (
      <CommandPrimitive
        shouldFilter={false}
        value={selectedValue}
        onValueChange={setSelectedValue}
        onKeyDown={(e) => {
          // Let cmdk handle arrow keys when dropdown is open
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            if (!showDropdown && isDropdownField) {
              setOpen(true);
            }
          }
        }}
      >
        <Popover open={showDropdown} onOpenChange={handleOpenChange}>
          <PopoverAnchor asChild>
            <Input
              ref={resolvedRef}
              value={inputValue}
              onChange={handleInputChange}
              onFocus={handleFocus}
              onBlur={handleBlur}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              type={type}
              className={cn(
                'h-7 text-xs bg-background font-mono text-muted-foreground hover:bg-secondary hover:text-primary',
                className
              )}
            />
          </PopoverAnchor>
          <PopoverContent
            className="p-0 w-[var(--radix-popover-trigger-width)]"
            align="start"
            sideOffset={4}
            onOpenAutoFocus={(e) => e.preventDefault()}
            onCloseAutoFocus={(e) => e.preventDefault()}
          >
            <CommandPrimitive.List className="max-h-48 overflow-y-auto p-1 custom-scrollbar">
              {isSearching && displayValues.length === 0 ? (
                <div className="px-2 py-3 text-xs text-muted-foreground text-center">
                  {inputValue !== debouncedSearch
                    ? 'Searching...'
                    : 'Loading...'}
                </div>
              ) : displayValues.length === 0 ? (
                <CommandPrimitive.Empty className="py-3 text-xs text-center text-muted-foreground">
                  No matches found
                </CommandPrimitive.Empty>
              ) : (
                <CommandPrimitive.Group>
                  {displayValues.map((val) => (
                    <CommandPrimitive.Item
                      key={val}
                      value={val}
                      onSelect={() => handleSelect(val)}
                      className={cn(
                        'relative flex cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs font-mono outline-none',
                        'data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground',
                        inputValue === val && 'bg-accent/50'
                      )}
                    >
                      {val}
                    </CommandPrimitive.Item>
                  ))}
                </CommandPrimitive.Group>
              )}
            </CommandPrimitive.List>
          </PopoverContent>
        </Popover>
      </CommandPrimitive>
    );
  }
);

SmartValueInput.displayName = 'SmartValueInput';
