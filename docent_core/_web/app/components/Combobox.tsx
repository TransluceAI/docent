'use client';

import {
  type ComponentPropsWithoutRef,
  type CSSProperties,
  type ReactNode,
  useCallback,
  useMemo,
  useState,
} from 'react';
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
import { Check, ChevronsUpDown } from 'lucide-react';
import { cn } from '@/lib/utils';

export type ComboboxOption = {
  value: string;
  label: ReactNode;
  keywords?: string[];
  disabled?: boolean;
};

type ButtonProps = ComponentPropsWithoutRef<typeof Button>;
type PopoverContentProps = ComponentPropsWithoutRef<typeof PopoverContent>;

interface ComboboxProps {
  value: string | null;
  onChange: (value: string) => void;
  options: ComboboxOption[];
  placeholder?: ReactNode;
  searchPlaceholder?: string;
  emptyMessage?: ReactNode;
  triggerProps?: Omit<ButtonProps, 'children'>;
  triggerClassName?: string;
  valueClassName?: string;
  chevronClassName?: string;
  popoverClassName?: string;
  popoverStyle?: CSSProperties;
  popoverAlign?: PopoverContentProps['align'];
  popoverSide?: PopoverContentProps['side'];
  popoverSideOffset?: PopoverContentProps['sideOffset'];
  popoverAlignOffset?: PopoverContentProps['alignOffset'];
  commandInputClassName?: string;
  commandListClassName?: string;
  optionClassName?: string;
  closeOnSelect?: boolean;
  renderOptionLabel?: (option: ComboboxOption) => ReactNode;
  renderValue?: (selected: ComboboxOption | null) => ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export const Combobox = ({
  value,
  onChange,
  options,
  placeholder = 'Select option',
  searchPlaceholder = 'Search...',
  emptyMessage = 'No results found.',
  triggerProps,
  triggerClassName,
  valueClassName,
  chevronClassName,
  popoverClassName,
  popoverStyle,
  popoverAlign,
  popoverSide,
  popoverSideOffset,
  popoverAlignOffset,
  commandInputClassName,
  commandListClassName,
  optionClassName,
  closeOnSelect = true,
  renderOptionLabel,
  renderValue,
  open,
  onOpenChange,
}: ComboboxProps) => {
  const [internalOpen, setInternalOpen] = useState(false);
  const isControlled = open !== undefined;
  const isOpen = isControlled ? Boolean(open) : internalOpen;

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!isControlled) {
        setInternalOpen(nextOpen);
      }
      onOpenChange?.(nextOpen);
    },
    [isControlled, onOpenChange]
  );

  const selectedOption = useMemo(() => {
    if (value === null || value === undefined) {
      return null;
    }
    return options.find((option) => option.value === value) ?? null;
  }, [options, value]);

  const {
    className: triggerPropsClassName,
    variant = 'outline',
    ...restTriggerProps
  } = triggerProps ?? {};

  const displayValue = useMemo(() => {
    if (renderValue) {
      return renderValue(selectedOption);
    }
    return selectedOption?.label ?? placeholder;
  }, [placeholder, renderValue, selectedOption]);

  const handleSelect = useCallback(
    (nextValue: string) => {
      onChange(nextValue);
      if (closeOnSelect) {
        handleOpenChange(false);
      }
    },
    [closeOnSelect, handleOpenChange, onChange]
  );

  return (
    <Popover open={isOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant={variant}
          size="sm"
          role="combobox"
          aria-expanded={isOpen}
          {...restTriggerProps}
          className={cn(
            'w-full justify-between',
            triggerPropsClassName,
            triggerClassName
          )}
        >
          <span className={cn('flex-1 truncate text-left', valueClassName)}>
            {displayValue}
          </span>
          <ChevronsUpDown
            className={cn('ml-2 h-4 w-4 shrink-0 opacity-50', chevronClassName)}
            aria-hidden="true"
          />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className={cn('p-0', popoverClassName)}
        style={popoverStyle}
        align={popoverAlign}
        side={popoverSide}
        sideOffset={popoverSideOffset}
        alignOffset={popoverAlignOffset}
      >
        <Command>
          <CommandInput
            placeholder={searchPlaceholder}
            className={cn('h-8 text-xs', commandInputClassName)}
          />
          <CommandList className={cn('custom-scrollbar', commandListClassName)}>
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            <CommandGroup>
              {options.map((option) => {
                const isSelected = option.value === value;
                return (
                  <CommandItem
                    key={option.value}
                    value={option.value}
                    keywords={option.keywords}
                    disabled={option.disabled}
                    onSelect={() => handleSelect(option.value)}
                    className={cn('flex items-center text-xs', optionClassName)}
                  >
                    {renderOptionLabel
                      ? renderOptionLabel(option)
                      : option.label}
                    <Check
                      aria-hidden="true"
                      className={cn(
                        'ml-auto h-4 w-4',
                        isSelected ? 'opacity-100' : 'opacity-0'
                      )}
                    />
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
};
